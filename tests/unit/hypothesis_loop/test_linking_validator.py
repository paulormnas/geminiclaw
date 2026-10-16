"""``v18.7-hypothesis-linking``: papel no plano (delta ``pipeline-robustness``) e revisão de hipótese do sistema."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_runtime.types import AgentTask
from src.agents.validator.agent import ValidatorAgent
from src.llm.base import LLMResponse
from src.orchestration.orchestrator import AgentResult, Orchestrator
from tests.support.linking_world import sub

pytestmark = pytest.mark.unit


def _agent(reply: str = '{"status": "approved", "reason": "ok", "issues": []}'):
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text=reply))
    return ValidatorAgent(provider=provider)


def _plan(**over):
    task = {"agent_id": "developer", "task_name": "baseline_majoritario", "prompt": "p",
            "task_type": "validation", "validation_criteria": ["baseline documentado"]}
    task.update(over)
    return [task]


# -- delta pipeline-robustness ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_baseline_declarado_como_referencia():
    """Scenario: Baseline declarado como referência (sem aviso; o papel vai ao evento ``plan_validation``)."""
    with patch("src.agents.validator.agent.record_llm_call"):
        result = await _agent().validate_plan(_plan(papel="referencia"), "x")
    assert result.is_valid and result.warnings == []


@pytest.mark.asyncio
async def test_validation_sem_hipotese_e_sem_papel_passa_com_aviso():
    """Scenario: Validation sem hipótese e sem papel."""
    with patch("src.agents.validator.agent.record_llm_call"):
        result = await _agent().validate_plan(_plan(task_name="diagnostico_classes"), "x")
    assert result.is_valid and result.warnings == ["validation_sem_hipotese"]


@pytest.mark.asyncio
async def test_teste_de_hipotese_sem_limiar_continua_reprovando():
    """Scenario: Teste de hipótese sem limiar."""
    result = await _agent().validate_plan(_plan(hypothesis_ref="h1", papel="teste"), "x")
    assert not result.is_valid and result.deterministic and "Correção" in result.issues[0]


@pytest.mark.asyncio
async def test_papel_invalido_nao_reprova():
    """Scenario: Papel inválido não reprova (também o plano em que nenhuma subtarefa tem ``papel``)."""
    plan = [sub("a", papel="exploratoria"), sub("b")]
    with patch("src.agents.validator.agent.record_llm_call"):
        result = await _agent().validate_plan(plan, "x")
    assert result.is_valid


@pytest.mark.asyncio
async def test_evento_plan_validation_registra_os_papeis_declarados():
    orch = Orchestrator(session_manager=MagicMock(), output_manager=MagicMock())
    plan = json.dumps([
        {"agent_id": "developer", "task_name": "baseline_majoritario", "prompt": "p", "task_type": "validation",
         "validation_criteria": ["c"], "papel": "referencia"},
        {"agent_id": "developer", "task_name": "outra", "prompt": "p", "validation_criteria": ["c"],
         "papel": "exploratoria"},
    ])
    reply = AgentResult(agent_id="researcher", session_id="s", status="success", response={"text": plan})
    with patch.object(orch, "_execute_agent", AsyncMock(return_value=reply)), \
            patch("src.agents.validator.agent.record_llm_call"), \
            patch("src.orchestration.orchestrator.get_telemetry") as tel:
        orch.validator = _agent()
        tasks = await orch._run_planning_loop("p", "s")
    payload = [c.kwargs["payload"] for c in tel.return_value.record_agent_event.call_args_list
               if c.kwargs.get("event_type") == "plan_validation"][-1]
    assert payload["papeis_declarados"] == {"baseline_majoritario": "referencia"}
    assert {t.task_name: t.papel for t in tasks}["baseline_majoritario"] == "referencia"


# -- revisão: hipótese do sistema -------------------------------------------------------------------------------


def _write(root: Path, rel: str, content) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


async def _review(root: Path, criteria: list[str], *, hypothesis_id="hs1", origin="sistema", expected=None,
                  reply='{"status": "pass", "feedback": "ok", "issues": []}', papel=""):
    task = AgentTask(agent_id="developer", prompt="x", task_name="treinar_rf", validation_criteria=criteria,
                     hypothesis_id=hypothesis_id, hypothesis_origin=origin, expected_artifacts=expected or [],
                     papel_decidido=papel)
    with patch("src.agents.validator.agent.record_llm_call"):
        return await _agent(reply).review_result(task=task, response_text="ok", output_dir=root)


@pytest.mark.asyncio
async def test_resultado_negativo_de_hipotese_do_sistema(tmp_path):
    """Scenario: Resultado negativo de hipótese do sistema."""
    _write(tmp_path, "treinar_rf/metrics.json", {"metrics": {"accuracy": 0.80}})
    review = await _review(tmp_path, ["acurácia no teste >= 0.9"])
    assert review.outcome == "resultado_negativo" and review.motivos == ["hipotese_do_sistema"]


@pytest.mark.asyncio
async def test_hipotese_do_sistema_com_artefato_ausente(tmp_path):
    """Scenario: Hipótese do sistema com artefato ausente."""
    _write(tmp_path, "treinar_rf/metrics.json", {"metrics": {"accuracy": 0.80}})
    review = await _review(tmp_path, ["acurácia no teste >= 0.9"], expected=["modelo_rf.joblib"])
    assert review.outcome == "reprovado" and review.motivos == ["hipotese_do_sistema"]


@pytest.mark.asyncio
async def test_hipotese_do_sistema_com_criterio_qualitativo_reprovado(tmp_path):
    """Scenario: Hipótese do sistema com critério qualitativo reprovado."""
    _write(tmp_path, "treinar_rf/metrics.json", {"metrics": {"accuracy": 0.80}})
    review = await _review(tmp_path, ["acurácia no teste >= 0.9", "gráfico de importância gerado"],
                           reply='{"status": "fail", "feedback": "sem gráfico", "issues": ["sem gráfico"]}')
    assert review.outcome == "reprovado"


@pytest.mark.asyncio
async def test_hipotese_do_sistema_aprovada_tambem_registra_o_motivo(tmp_path):
    _write(tmp_path, "treinar_rf/metrics.json", {"metrics": {"accuracy": 0.95}})
    review = await _review(tmp_path, ["acurácia no teste >= 0.9"])
    assert review.status == "pass" and review.motivos == ["hipotese_do_sistema"]


@pytest.mark.asyncio
async def test_hipotese_de_agente_nao_leva_o_motivo(tmp_path):
    _write(tmp_path, "treinar_rf/metrics.json", {"metrics": {"accuracy": 0.80}})
    review = await _review(tmp_path, ["acurácia no teste >= 0.9"], origin="researcher")
    assert review.motivos == []


@pytest.mark.asyncio
async def test_preparacao_com_limiar_nao_atingido_segue_reprovada_sem_motivo(tmp_path):
    """Scenario: Preparação com limiar não atingido."""
    _write(tmp_path, "treinar_rf/metrics.json", {"metrics": {"proporcao_nulos": 0.1}})
    # grandeza fora da tabela de métricas conhecidas: o critério vai ao revisor LLM (provedor falso reprova)
    review = await _review(tmp_path, ["proporção de nulos <= 0"], hypothesis_id="", origin="", papel="preparacao",
                           reply='{"status": "fail", "feedback": "há nulos", "issues": ["há nulos"]}')
    assert review.outcome == "reprovado" and review.motivos == []


@pytest.mark.asyncio
async def test_falha_de_execucao_da_hipotese_do_sistema_nao_refuta(tmp_path):
    """Scenario: Falha de execução não é resultado negativo (``Experimento`` ``falha`` e nenhum ``REFUTA``)."""
    from src.knowledge.ingestion import SubtaskInput, ingest_subtask
    from tests.support.linking_world import LinkingCycle

    c = LinkingCycle(tmp_path)
    c.run([sub("treinar_rf", approach={"nome": "random forest", "tipo": "algoritmo"})])
    (hs,) = c.system_hypotheses()
    exp = ingest_subtask(
        c.w.store, c.w.ctx, tmp_path / "out",
        SubtaskInput(task_name="treinar_rf", subtask_id="x", agent_id="developer", task_type="model_impl",
                     agent_status="error", hypothesis_id=hs.id, papel="teste"),
    )
    assert exp is not None and c.w.store.get_node(exp).properties["status"] == "falha"
    refuted = [e for e in c.w.store.neighbors(hs.id, ["REFUTA"], direction="in", depth=1).edges]
    assert refuted == []
