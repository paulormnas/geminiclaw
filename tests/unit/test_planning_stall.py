"""Laço de reprovação do plano com fim (v16-pipeline-robustness §1)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator_agent import ValidationResult, ValidatorAgent
from src.llm.base import LLMResponse
from src.orchestrator import AgentResult, Orchestrator
from src.pipeline_errors import PlanningStalled

pytestmark = pytest.mark.unit

PLAN = '[{"agent_id": "developer", "task_name": "t", "prompt": "p", "validation_criteria": ["c"]}]'


def planner(text=PLAN):
    return AgentResult(agent_id="researcher", session_id="s", status="success", response={"text": text})


def rejection(signature, deterministic):
    return ValidationResult(is_valid=False, status="revision_needed", reason="r", issues=["problema"],
                            signature=signature, deterministic=deterministic)


@pytest.fixture
def orch():
    o = Orchestrator(session_manager=MagicMock(), output_manager=MagicMock())
    o.validator = MagicMock()
    o.validator.validate_plan = AsyncMock()
    return o


@pytest.mark.asyncio
async def test_reprovacao_deterministica_repetida_termina_com_erro(orch):
    """Scenario: Reprovação determinística repetida."""
    orch.validator.validate_plan.return_value = rejection("sig", True)
    with patch("src.orchestrator.PLAN_REJECTION_STALL_LIMIT", 2):
        with patch.object(orch, "_execute_agent", AsyncMock(return_value=planner())) as execute:
            with pytest.raises(PlanningStalled) as err:
                await orch._run_planning_loop("p", "s")
    assert execute.call_count == 2 and "problema" in str(err.value)


@pytest.mark.asyncio
async def test_reprovacao_diferente_nao_conta_como_repeticao(orch):
    """Scenario: Reprovação diferente não conta como repetição."""
    orch.validator.validate_plan.side_effect = [
        rejection("a", True), rejection("b", True),
        ValidationResult(is_valid=True, status="approved", reason="ok"),
    ]
    with patch.object(orch, "_execute_agent", AsyncMock(return_value=planner())):
        tasks = await orch._run_planning_loop("p", "s")
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_validator_llm_consultivo_aprova_com_avisos(orch):
    """Scenario: Validator LLM consultivo."""
    orch.validator.validate_plan.return_value = rejection("llm", False)
    with patch.object(orch, "_execute_agent", AsyncMock(return_value=planner())):
        with patch("src.orchestrator.get_telemetry") as tel:
            tasks = await orch._run_planning_loop("p", "s")
    assert len(tasks) == 1
    payloads = [c.kwargs["payload"] for c in tel.return_value.record_agent_event.call_args_list
                if c.kwargs.get("event_type") == "plan_validation"]
    assert payloads[-1]["approved_with_warnings"] is True and payloads[-1]["issues"] == ["problema"]


@pytest.mark.asyncio
async def test_primeira_reprovacao_do_validator_llm_vale(orch):
    """Scenario: Primeira reprovação do Validator LLM vale."""
    orch.validator.validate_plan.side_effect = [
        rejection("llm", False), ValidationResult(is_valid=True, status="approved", reason="ok"),
    ]
    with patch.object(orch, "_execute_agent", AsyncMock(return_value=planner())) as execute:
        await orch._run_planning_loop("p", "s")
    assert execute.call_count == 2


@pytest.mark.asyncio
async def test_normalizador_repara_plano_antes_do_validator_e_emite_evento(orch):
    orch.validator.validate_plan.return_value = ValidationResult(is_valid=True, status="approved", reason="ok")
    wrapped = '{"tasks": [{"agent_id": "developer", "task_name": "T 1", "prompt": "p", "validation_criteria": "c"}]}'
    with patch.object(orch, "_execute_agent", AsyncMock(return_value=planner(wrapped))):
        with patch("src.orchestrator.get_telemetry") as tel:
            tasks = await orch._run_planning_loop("p", "s")
    assert tasks[0].task_name == "t_1" and tasks[0].validation_criteria == ["c"]
    events = [c.kwargs for c in tel.return_value.record_agent_event.call_args_list]
    assert any(e["event_type"] == "plan_normalized" for e in events)
    seen = orch.validator.validate_plan.call_args.kwargs["plan"]
    assert isinstance(seen, list) and seen[0]["task_name"] == "t_1"


@pytest.mark.asyncio
async def test_normalizador_desligado_nao_repara(orch):
    """Scenario: Normalizador desligado."""
    orch.validator.validate_plan.return_value = ValidationResult(is_valid=True, status="approved", reason="ok")
    plan = '[{"agent_id": "developer", "task_name": "t", "prompt": "p", "depends_on": "a, b"}]'
    with patch("src.orchestrator.PLAN_NORMALIZER_ENABLED", False):
        with patch.object(orch, "_execute_agent", AsyncMock(return_value=planner(plan))):
            await orch._run_planning_loop("p", "s")
    assert orch.validator.validate_plan.call_args.kwargs["plan"][0]["depends_on"] == "a, b"


@pytest.mark.asyncio
async def test_assinatura_deterministica_do_validator_real_e_estavel():
    provider = MagicMock()
    provider.generate = AsyncMock(return_value=LLMResponse(text='{"status": "approved"}'))
    agent = ValidatorAgent(provider=provider)
    bad = [{"agent_id": "developer", "task_name": "avaliar", "prompt": "p", "task_type": "validation",
            "validation_criteria": ["modelos comparados"]}]
    r1 = await agent.validate_plan(bad, "x")
    r2 = await agent.validate_plan(bad, "y")
    assert r1.deterministic and r1.signature and r1.signature == r2.signature
