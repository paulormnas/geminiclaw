import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.autonomous_loop import AutonomousLoop
from src.orchestrator import AgentResult, AgentTask, OrchestratorResult

@pytest.mark.asyncio
async def test_autonomous_loop_simple_path():
    orchestrator = MagicMock()
    orchestrator._execute_agent = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    
    # Mock base execution result
    base_result = AgentResult(agent_id="base", session_id="s2", status="success", response={"text": "Hello"})
    orchestrator._execute_agent.side_effect = [base_result]
    
    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=False)):
        loop = AutonomousLoop(orchestrator)
        result = await loop.run("Hi", "m1")
    
    assert result.total == 1
    assert result.succeeded == 1
    assert result.results[0].agent_id == "base"
    assert orchestrator._execute_agent.call_count == 1

@pytest.mark.asyncio
async def test_autonomous_loop_complex_path_success():
    orchestrator = MagicMock()
    orchestrator._execute_agent = AsyncMock()
    orchestrator._run_planning_loop = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    
    # planning
    task1 = AgentTask(agent_id="researcher", image="img", prompt="search")
    orchestrator._run_planning_loop.return_value = [task1]
    
    # execution success
    success_result = AgentResult(agent_id="researcher", session_id="s2", status="success", response={"text": "data"})
    
    # promotion
    promo_result = AgentResult(agent_id="planner", session_id="s3", status="success", response={})

    orchestrator._execute_agent.side_effect = [success_result, promo_result]
    
    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)):
        loop = AutonomousLoop(orchestrator)
        result = await loop.run("Complex task", "m1")
    
    assert result.total == 1
    assert result.succeeded == 1
    assert orchestrator._execute_agent.call_count == 2 # task1 + promotion

@pytest.mark.asyncio
async def test_autonomous_loop_complex_path_retry_success():
    orchestrator = MagicMock()
    orchestrator._execute_agent = AsyncMock()
    orchestrator._run_planning_loop = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    
    # planning
    task1 = AgentTask(agent_id="researcher", image="img", prompt="search")
    orchestrator._run_planning_loop.return_value = [task1]
    
    # execution: fail, then success
    fail_result = AgentResult(agent_id="researcher", session_id="s2", status="error", response={}, error="timeout")
    success_result = AgentResult(agent_id="researcher", session_id="s2", status="success", response={"text": "data"})
    
    # promotion
    promo_result = AgentResult(agent_id="planner", session_id="s3", status="success", response={})

    orchestrator._execute_agent.side_effect = [fail_result, success_result, promo_result]
    
    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)):
        loop = AutonomousLoop(orchestrator)
        loop.max_retries = 2
        # Mock sleep to speed up test
        with patch("asyncio.sleep", AsyncMock()):
            result = await loop.run("Complex task", "m1")
    
    assert result.total == 1
    assert result.succeeded == 1
    assert orchestrator._execute_agent.call_count == 3 # 2 attempts + promotion

@pytest.mark.asyncio
async def test_autonomous_loop_complex_path_fail_after_retries():
    orchestrator = MagicMock()
    orchestrator._execute_agent = AsyncMock()
    orchestrator._run_planning_loop = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    
    # planning
    task1 = AgentTask(agent_id="researcher", image="img", prompt="search")
    orchestrator._run_planning_loop.return_value = [task1]
    
    # execution: fail twice
    fail_result = AgentResult(agent_id="researcher", session_id="s2", status="error", response={}, error="timeout")
    
    orchestrator._execute_agent.side_effect = [fail_result, fail_result]
    
    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)):
        loop = AutonomousLoop(orchestrator)
        loop.max_retries = 2
        with patch("asyncio.sleep", AsyncMock()):
            result = await loop.run("Complex task", "m1")
    
    assert result.total == 1
    assert result.succeeded == 0
    assert orchestrator._execute_agent.call_count == 2 # 2 attempts
