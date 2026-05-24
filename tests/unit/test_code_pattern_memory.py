import pytest
import json
import os
from unittest.mock import MagicMock, AsyncMock, patch

from src.autonomous_loop import AutonomousLoop
from src.orchestrator import AgentTask, AgentResult

@pytest.fixture
def mock_orchestrator():
    orchestrator = MagicMock()
    # Mocking the _execute_agent to return success and a JSON string
    result = AgentResult(
        agent_id="planner",
        session_id="test_session",
        status="success",
        response={"text": '{"domain": "pandas", "pattern": "usar read_csv", "pitfall": "na_values default", "fix": "keep_default_na=False"}'}
    )
    orchestrator._execute_agent = AsyncMock(return_value=result)
    return orchestrator

@pytest.fixture
def autonomous_loop(mock_orchestrator):
    loop = AutonomousLoop(orchestrator=mock_orchestrator)
    return loop

@pytest.mark.asyncio
async def test_extract_code_patterns(autonomous_loop, tmp_path):
    # Prepare fake manifest.json
    output_dir = tmp_path / "outputs"
    os.environ["OUTPUT_DIR"] = str(output_dir)
    session_dir = output_dir / "test_session"
    session_dir.mkdir(parents=True, exist_ok=True)
    
    manifest_data = {
        "steps": [
            {"step": 1, "status": "success", "summary": "Carregou CSV com pandas"}
        ]
    }
    with open(session_dir / "manifest.json", "w") as f:
        json.dump(manifest_data, f)
        
    result = AgentResult(
        agent_id="code",
        session_id="test_session",
        status="success",
        response={}
    )
    
    with patch("src.skills.__init__.registry.get") as mock_registry_get:
        mock_memory_skill = AsyncMock()
        mock_registry_get.return_value = mock_memory_skill
        
        await autonomous_loop._extract_code_patterns(result, "test_session")
        
        # Verify memory skill was called with the correct parameters
        mock_memory_skill.run.assert_called_once()
        kwargs = mock_memory_skill.run.call_args.kwargs
        assert kwargs["action"] == "memorize"
        assert kwargs["key"].startswith("code_pattern:pandas:")
        assert "pandas" in kwargs["tags"]
        
def test_enrich_task_prompt_with_lessons(autonomous_loop):
    task = AgentTask(
        agent_id="code",
        image="geminiclaw-code",
        prompt="Faça um EDA com pandas",
        task_name="eda"
    )
    
    with patch("src.skills.__init__.registry.get") as mock_registry_get:
        mock_memory_skill = MagicMock()
        mock_registry_get.return_value = mock_memory_skill
        
        # Mock long_term.search returning a lesson
        mock_lesson = MagicMock()
        mock_lesson.value = json.dumps({
            "domain": "pandas",
            "pattern": "usar read_csv",
            "pitfall": "None",
            "fix": "None"
        })
        mock_memory_skill.long_term.search.return_value = [mock_lesson]
        
        enriched_task = autonomous_loop._enrich_task_prompt(task)
        
        # Ensure it inferred "pandas" and injected the pattern
        mock_memory_skill.long_term.search.assert_called_once_with(tags=["pandas"], limit=3)
        assert "[PADRÕES DE CÓDIGO CONHECIDOS PARA ESTE DOMÍNIO]" in enriched_task.prompt
        assert "usar read_csv" in enriched_task.prompt

def test_enrich_task_prompt_different_domain(autonomous_loop):
    task = AgentTask(
        agent_id="code",
        image="geminiclaw-code",
        prompt="Plote um gráfico com matplotlib",
        task_name="plot"
    )
    
    with patch("src.skills.__init__.registry.get") as mock_registry_get:
        mock_memory_skill = MagicMock()
        mock_registry_get.return_value = mock_memory_skill
        
        # Mock long_term.search returning empty for matplotlib
        mock_memory_skill.long_term.search.return_value = []
        
        enriched_task = autonomous_loop._enrich_task_prompt(task)
        
        # Ensure it inferred "matplotlib" and DID NOT inject pandas pattern
        mock_memory_skill.long_term.search.assert_called_once_with(tags=["matplotlib"], limit=3)
        assert "[PADRÕES DE CÓDIGO CONHECIDOS PARA ESTE DOMÍNIO]" not in enriched_task.prompt
