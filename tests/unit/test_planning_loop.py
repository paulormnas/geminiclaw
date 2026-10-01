"""Ciclo de planejamento: o Researcher gera o plano e o ValidatorAgent (corrotina em processo) o avalia.

O Validator é substituído por um dublê em todos os testes: o real chamaria o provedor LLM e gastaria
créditos. Só o Researcher passa por ``_execute_agent`` (também simulado).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator_agent import ValidationResult
from src.orchestrator import AgentResult, Orchestrator


def approved() -> ValidationResult:
    return ValidationResult(is_valid=True, status="approved", reason="ok")


def revision(reason: str = "vazio") -> ValidationResult:
    return ValidationResult(is_valid=False, status="revision_needed", reason=reason, issues=[reason])


def planner_result(text: str) -> AgentResult:
    return AgentResult(agent_id="researcher", session_id="s", status="success", response={"text": text})


@pytest.fixture
def orchestrator():
    orch = Orchestrator(session_manager=MagicMock(), output_manager=MagicMock())
    orch.validator = MagicMock()
    orch.validator.validate_plan = AsyncMock()
    return orch


@pytest.mark.asyncio
async def test_planning_loop_success(orchestrator):
    """Plano aprovado de imediato."""
    orchestrator.validator.validate_plan.return_value = approved()
    plan = '[{"agent_id": "researcher", "task_name": "task1", "prompt": "search X"}]'

    with patch.object(orchestrator, "_execute_agent", AsyncMock(return_value=planner_result(plan))) as mock_exec:
        tasks = await orchestrator._run_planning_loop("De uma volta no quarteirão", "master_s")

    assert len(tasks) == 1
    assert tasks[0].agent_id == "researcher"
    assert mock_exec.call_count == 1
    assert orchestrator.validator.validate_plan.await_count == 1


@pytest.mark.asyncio
async def test_planning_loop_revision_needed(orchestrator):
    """Uma revisão pedida pelo Validator antes da aprovação."""
    orchestrator.validator.validate_plan.side_effect = [revision(), approved()]
    plans = [planner_result("[]"), planner_result('[{"agent_id": "base", "task_name": "t2"}]')]

    with patch.object(orchestrator, "_execute_agent", AsyncMock(side_effect=plans)) as mock_exec:
        tasks = await orchestrator._run_planning_loop("Prompt", "master_s")

    assert len(tasks) == 1
    assert tasks[0].agent_id == "base"
    assert mock_exec.call_count == 2
    # O replan recebe o problema apontado pelo Validator.
    second_prompt = mock_exec.call_args_list[1].args[0].prompt
    assert "vazio" in second_prompt


@pytest.mark.asyncio
async def test_planning_loop_max_iterations(orchestrator):
    """O ciclo para ao atingir o limite de iterações."""
    orchestrator.validator.validate_plan.return_value = revision("ainda ruim")

    with patch("src.orchestrator.MAX_PLANNING_ITERATIONS", 3):
        with patch.object(orchestrator, "_execute_agent", AsyncMock(return_value=planner_result("[]"))) as mock_exec:
            tasks = await orchestrator._run_planning_loop("Prompt", "master_s")

    assert tasks == []
    assert mock_exec.call_count == 3
    assert orchestrator.validator.validate_plan.await_count == 3


@pytest.mark.asyncio
async def test_planning_loop_with_new_fields(orchestrator):
    """validation_criteria e preferred_model são lidos do plano."""
    orchestrator.validator.validate_plan.return_value = approved()
    plan_json = """
    [
        {
            "agent_id": "researcher",
            "task_name": "task1",
            "prompt": "search X",
            "validation_criteria": ["Criterio 1", "Criterio 2"],
            "preferred_model": "gemini-3.8-flash"
        }
    ]
    """

    with patch.object(orchestrator, "_execute_agent", AsyncMock(return_value=planner_result(plan_json))):
        tasks = await orchestrator._run_planning_loop("Prompt", "master_s")

    assert len(tasks) == 1
    assert tasks[0].validation_criteria == ["Criterio 1", "Criterio 2"]
    assert tasks[0].preferred_model == "gemini-3.8-flash"
