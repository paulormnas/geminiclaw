"""Campos do plano e conferência das predições na revisão (v18.7-exploration-limits, tarefa 5.3). Sem LLM real."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_runtime.types import AgentTask
from src.agents.validator.agent import ValidatorAgent
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.ingestion import SubtaskInput
from src.knowledge.objective import parse_discrimina
from src.knowledge.projects import create_project
from src.llm.base import LLMResponse
from src.orchestration.autonomous_loop import AutonomousLoop
from src.orchestration.orchestrator import AgentResult
from src.orchestration.subtask_ingestion import ingest_subtask
from tests.unit.test_structural_fact_contracts import _orch

pytestmark = pytest.mark.unit

RIVALS = [{"hipotese_id": "h-a", "predicao": "A"}, {"hipotese_id": "h-b", "predicao": ""}, {"hipotese_id": "h-c", "predicao": "C"}]
REVIEW_TEXT = json.dumps({
    "status": "pass", "feedback": "ok", "issues": [],
    "predicoes": [
        {"hipotese_id": "h-a", "conferencia": "confirma", "justificativa": "bate"},
        {"hipotese_id": "h-b", "conferencia": "contraria", "justificativa": "x"},
        {"hipotese_id": "h-c", "conferencia": "contraria", "justificativa": "fora de discrimina"},
    ],
})


def test_parse_discrimina():
    assert parse_discrimina(["h1", " h2 ", "h1", "", 3]) == ["h1", "h2"]
    assert parse_discrimina("h1") == [] and parse_discrimina(None) == []


def test_campos_do_plano_vao_para_a_subtarefa():
    """O plano com ``discrimina`` e ``experimento_fisico`` chega à ``AgentTask``; a ausência não reprova."""
    task = AgentTask(agent_id="developer", prompt="p", discrimina=parse_discrimina(["h1", "h2"]), experimento_fisico=True)
    assert task.discrimina == ["h1", "h2"] and task.experimento_fisico is True
    plain = AgentTask(agent_id="developer", prompt="p")
    assert plain.discrimina == [] and plain.experimento_fisico is False


async def review(tmp_path, task):
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text=REVIEW_TEXT))
    agent = ValidatorAgent(provider=provider)
    with patch("src.agents.validator.agent.record_llm_call"):
        return await agent.review_result(task=task, response_text="ok", output_dir=tmp_path), provider


@pytest.mark.asyncio
async def test_revisao_traz_predicoes_das_listadas(tmp_path):
    task = AgentTask(agent_id="developer", prompt="x", task_name="t", validation_criteria=["gera relatório"],
                     discrimina=["h-a", "h-b"], concorrentes_contexto=RIVALS)
    result, provider = await review(tmp_path, task)
    assert [p["hipotese_id"] for p in result.predicoes] == ["h-a", "h-b", "h-c"]  # filtro é do critério
    assert "predicoes" in provider.generate.call_args.kwargs["system"]
    prompt = repr(provider.generate.call_args.kwargs["messages"])
    assert "PREDIÇÕES DAS HIPÓTESES CONCORRENTES" in prompt and "h-a" in prompt and "h-c" not in prompt


@pytest.mark.asyncio
async def test_revisao_comum_nao_pede_predicoes(tmp_path):
    task = AgentTask(agent_id="developer", prompt="x", task_name="t", validation_criteria=["gera relatório"])
    result, provider = await review(tmp_path, task)
    assert result.predicoes == [] and "predicoes" not in provider.generate.call_args.kwargs["system"]


@pytest.mark.asyncio
async def test_ingestao_grava_a_conferencia_normalizada(tmp_path):
    """Scenario: Concorrente sem predição — ``h-b`` fica inconclusiva mesmo com ``contraria`` no parecer."""
    store = InMemoryGraphStore()
    pid = create_project(store, "P", "O", [])
    orch = _orch(tmp_path, store)
    session_dir = orch.output_manager.base_dir / "s1" / "treinar"
    session_dir.mkdir(parents=True)
    (session_dir / "metrics.json").write_text(json.dumps({"metrics": {"r2": 0.8}, "baselines": {"r2": 0.7}}))
    (session_dir / "params.json").write_text(json.dumps({"seed": 1, "parameters": {"n": 5, "seed": 1}}))
    ingestor = orch._start_ingestor("s1", pid, "auto", "2026-10-06T10:00:00+00:00", None)
    ingestor.session_start()
    task = AgentTask(agent_id="developer", prompt="p", task_name="treinar", subtask_id="sub-9",
                     validation_criteria=["r2 >= 0.75"], discrimina=["h-a", "h-b"], concorrentes_contexto=RIVALS)
    ok = AgentResult(agent_id="developer", session_id="x", status="success", response={})
    review_dict = {"status": "pass", "verified": True, "predicoes": json.loads(REVIEW_TEXT)["predicoes"]}
    await ingest_subtask(AutonomousLoop(orch).orchestrator, task, ok, review_dict, "s1")
    (exp,) = store.find_nodes("Experimento", {})
    assert exp.properties["conferencia_predicoes"] == {"h-a": "confirma", "h-b": "inconclusiva"}


def test_subtask_input_valida_a_conferencia_da_fila():
    base = {"task_name": "t", "conferencia_predicoes": {"h1": "confirma", "h2": "talvez", 3: "contraria"}}
    assert SubtaskInput.from_dict(base).conferencia_predicoes == {"h1": "confirma"}
    assert SubtaskInput.from_dict({"task_name": "t", "conferencia_predicoes": "x"}).conferencia_predicoes is None
