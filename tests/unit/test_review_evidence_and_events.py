"""Revisor com evidência de conteúdo, modo herdado pelo planejamento e eventos de comunicação."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator_agent import ValidatorAgent, build_artifact_evidence
from src.llm.base import LLMResponse
from src.orchestrator import AgentResult, AgentTask, Orchestrator

pytestmark = pytest.mark.unit


def test_evidence_lists_relative_path_size_and_head(tmp_path):
    (tmp_path / "eda").mkdir()
    (tmp_path / "eda" / "metrics.json").write_text('{"accuracy": 0.95}')
    (tmp_path / "eda" / "plot.png").write_bytes(b"\x89PNG" * 10)
    (tmp_path / "eda" / "script.py").write_text("print(1)")
    text = build_artifact_evidence(tmp_path, ["metrics.json", "plot.png"])
    assert 'eda/metrics.json (18 bytes): {"accuracy": 0.95}' in text
    assert "eda/plot.png (40 bytes, binário)" in text
    assert "script.py" not in text


def test_evidence_without_session_dir():
    assert "sem diretório" in build_artifact_evidence(None, ["x"])


@pytest.mark.asyncio
async def test_reviewer_prompt_carries_evidence_and_path_rule(tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "metrics.json").write_text('{"accuracy": 0.95}')
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text='{"status": "pass", "feedback": "ok", "issues": []}'))
    agent = ValidatorAgent(provider=provider)
    task = AgentTask(agent_id="developer", prompt="x", task_name="t", expected_artifacts=["metrics.json"],
                     validation_criteria=["A acurácia é reportada"])
    with patch("src.agents.validator_agent.record_llm_call"):
        review = await agent.review_result(
            task=task, response_text="salvei /outputs/metrics.json", output_dir=tmp_path
        )
    assert review.status == "pass"
    kwargs = provider.generate.call_args.kwargs
    assert 't/metrics.json (18 bytes): {"accuracy": 0.95}' in kwargs["messages"][0]["content"]
    assert "prefixo" in kwargs["system"]


@pytest.mark.asyncio
async def test_planning_task_inherits_session_mode():
    orch = Orchestrator(session_manager=MagicMock(), output_manager=MagicMock())
    orch._session_modes["sess"] = "auto"
    orch.agent_runtime = MagicMock()
    orch.agent_runtime.run = AsyncMock(
        return_value=AgentResult(agent_id="researcher", session_id="s", status="success", response={})
    )
    orch.session_manager.create.return_value = MagicMock(id="agent-session")
    orch.output_manager.base_dir = MagicMock()
    with patch("src.orchestrator.get_telemetry"):
        await orch._execute_agent(AgentTask(agent_id="researcher", prompt="planeje"), "sess")
    ctx = orch.agent_runtime.run.call_args.args[1]
    assert ctx.mode == "auto"


@pytest.mark.asyncio
async def test_ask_researcher_in_auto_mode_records_the_question():
    from src.agent_runtime.context import AgentContext, current_context
    from src.skills.human_feedback.skill import HumanFeedbackSkill

    ctx = AgentContext(session_id="s", agent_session_id="a", agent_id="researcher", task_name="t", mode="auto",
                       output_dir=None, model="m", enable_thinking=False, execution_id="e1")
    token = current_context.set(ctx)
    try:
        with patch("src.telemetry.get_telemetry") as tel:
            result = await HumanFeedbackSkill().run(
                question="Qual split?", why_cant_proceed="ambíguo", options=["80/20"]
            )
    finally:
        current_context.reset(token)
    assert result.success and "suposição" in result.output
    kwargs = tel.return_value.record_agent_event.call_args.kwargs
    assert kwargs["event_type"] == "ask_researcher" and kwargs["payload"]["question"] == "Qual split?"
    assert kwargs["payload"]["blocked"] is False


@pytest.mark.asyncio
async def test_plan_rejection_message_is_actionable_and_llm_is_told_not_to_reject_thresholds():
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text='{"status": "approved"}'))
    agent = ValidatorAgent(provider=provider)
    bad = [{"agent_id": "developer", "task_name": "avaliar", "prompt": "p", "task_type": "validation",
            "validation_criteria": ["modelos comparados"]}]
    result = await agent.validate_plan(bad, "tarefa")
    assert not result.is_valid and "Correção" in result.issues[0] and "model_impl" in result.issues[0]

    good = [{"agent_id": "developer", "task_name": "avaliar", "prompt": "p", "task_type": "validation",
             "validation_criteria": ["acurácia >= 0.80"]}]
    with patch("src.agents.validator_agent.record_llm_call"):
        await agent.validate_plan(good, "tarefa")
    assert "Não reprove por causa de limiares" in provider.generate.call_args.kwargs["system"]
