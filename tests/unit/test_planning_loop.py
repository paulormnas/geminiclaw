import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.orchestrator import Orchestrator, AgentTask, AgentResult

@pytest.fixture
def mock_deps():
    return {
        "runner": MagicMock(),
        "ipc": MagicMock(),
        "session_manager": MagicMock(),
        "output_manager": MagicMock(),
    }

@pytest.mark.asyncio
async def test_planning_loop_success(mock_deps):
    """Testa o ciclo de planejamento com aprovação imediata."""
    orchestrator = Orchestrator(**mock_deps)
    
    # Mock do _execute_agent para o Planner
    planner_response = {
        "status": "success",
        "response": {"text": '[{"agent_id": "researcher", "task_name": "task1", "prompt": "search X"}]'}
    }
    
    # Mock do _execute_agent para o Validator
    validator_response = {
        "status": "success",
        "response": {"text": '{"status": "approved"}'}
    }
    
    with patch.object(orchestrator, "_execute_agent") as mock_exec:
        mock_exec.side_effect = [
            AgentResult(agent_id="planner", session_id="s1", **planner_response),
            AgentResult(agent_id="validator", session_id="s2", **validator_response)
        ]
        
        tasks = await orchestrator._run_planning_loop("De uma volta no quarteirão")
        
        assert len(tasks) == 1
        assert tasks[0].agent_id == "researcher"
        assert mock_exec.call_count == 2

@pytest.mark.asyncio
async def test_planning_loop_revision_needed(mock_deps):
    """Testa o ciclo de planejamento com uma revisão antes da aprovação."""
    orchestrator = Orchestrator(**mock_deps)
    
    with patch.object(orchestrator, "_execute_agent") as mock_exec:
        mock_exec.side_effect = [
            # 1. Planner gera plano 1
            AgentResult(agent_id="planner", session_id="s1", status="success", response={"text": "[]"}),
            # 2. Validator pede revisão
            AgentResult(agent_id="validator", session_id="s2", status="success", response={"text": '{"status": "revision_needed", "reason": "vazio"}'}),
            # 3. Planner gera plano 2
            AgentResult(agent_id="planner", session_id="s3", status="success", response={"text": '[{"agent_id": "base", "task_name": "t2"}]'}),
            # 4. Validator aprova
            AgentResult(agent_id="validator", session_id="s4", status="success", response={"text": '{"status": "approved"}'})
        ]
        
        tasks = await orchestrator._run_planning_loop("Prompt")
        
        assert len(tasks) == 1
        assert tasks[0].agent_id == "base"
        assert mock_exec.call_count == 4

@pytest.mark.asyncio
async def test_planning_loop_max_iterations(mock_deps):
    """Testa se o loop para após 3 tentativas de revisão."""
    orchestrator = Orchestrator(**mock_deps)
    
    with patch.object(orchestrator, "_execute_agent") as mock_exec:
        # Sempre pede revisão
        mock_exec.return_value = AgentResult(
            agent_id="x", session_id="s", status="success", 
            response={"text": '{"status": "revision_needed"}'} 
        )
        
        tasks = await orchestrator._run_planning_loop("Prompt")
        
        assert tasks == []
        # Para cada iteração: 1 planner + 1 validator = 2 chamadas. 
        # Total 3 iterações = 6 chamadas.
        assert mock_exec.call_count == 6
