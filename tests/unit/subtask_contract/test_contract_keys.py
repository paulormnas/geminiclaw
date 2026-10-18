"""Chaves de métrica, ``criterio_ambiguo``, devolução da tentativa e observações (v18.7-subtask-contract §5.4–5.6).

Sem rede nem provedor pago. Os testes do laço usam o harness de exploração (``ContractHarness``) com o revisor real
(a ambiguidade é decidida sem chamar LLM) e ``ON_PLAN_REJECTIONS=parar`` por cautela.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.agent_runtime.types import AgentResult, AgentTask
from src.agents.subtask_contract import build_developer_contract
from src.agents.validator.agent import ReviewResult, ValidatorAgent
from src.knowledge.metric_criteria import _evaluate_metric_criteria, _metric_criteria, criterion_ambiguities
from src.observability.telemetry import TelemetryCollector
from src.orchestration.usage import UsageBudget, UsageTracker
from tests.support.exploration_world import hyp, plan, task
from tests.support.fake_recording_provider import FakeRecordingProvider
from tests.unit.subtask_contract.test_contract_dispatch import ContractHarness

pytestmark = pytest.mark.unit

TASK = "treinar_modelo_a"
CRITERION = "acurácia no teste >= 0.90"
QUALIFIED = {"modelo_a.acuracia": 0.91, "modelo_b.acuracia": 0.95}


def _eval(criterion, metrics, *, contract_keys=True):
    crits = _metric_criteria([criterion])
    return _evaluate_metric_criteria(crits, metrics, contract_keys=contract_keys), crits


# --- Tabela de chaves (design §5) --------------------------------------------------------------------------------


def test_chave_sem_qualificador_presente():
    """Scenario: Chave sem qualificador presente."""
    (ok, detail), = _eval(CRITERION, {"acuracia": 0.91, **QUALIFIED})[0]
    assert ok is True and "'acuracia' valor real = 0.91" in detail


def test_ambiguidade_com_so_chaves_qualificadas():
    """Scenario: Grupo não nomeado (contrato): critério ambíguo, não vai ao LLM."""
    results, crits = _eval(CRITERION, QUALIFIED)
    assert results[0][0] is None
    (crit, keys), = criterion_ambiguities(crits, QUALIFIED)
    assert keys == ["modelo_a.acuracia", "modelo_b.acuracia"] and crit.text == CRITERION


def test_sem_o_contrato_o_grupo_nao_nomeado_continua_indecidido():
    results, _ = _eval(CRITERION, QUALIFIED, contract_keys=False)
    assert results[0][0] is None


def test_grupo_nomeado_pelo_criterio():
    """Scenario: Grupo nomeado."""
    metrics = {"logistic_regression.accuracy": 0.93, "random_forest.accuracy": 0.97}
    (ok, detail), = _eval("acurácia do Random Forest >= 0.95", metrics)[0]
    assert ok is True and "0.97" in detail
    assert criterion_ambiguities(_metric_criteria(["acurácia do Random Forest >= 0.95"]), metrics) == []


def test_criterio_cita_a_chave_qualificada():
    """Scenario: Critério cita a chave qualificada."""
    (ok, detail), = _eval("modelo_b.acuracia >= 0.93", {"acuracia": 0.5, **QUALIFIED})[0]
    assert ok is True and "'modelo_b.acuracia' valor real = 0.95" in detail


def test_chave_qualificada_citada_ausente_reprova_listando_as_existentes():
    (ok, detail), = _eval("modelo_c.acuracia >= 0.93", QUALIFIED)[0]
    assert ok is False and "modelo_c.acuracia" in detail and "modelo_a.acuracia" in detail


def test_unica_chave_qualificada_nao_exige_escolha():
    (ok, _), = _eval(CRITERION, {"modelo_a.acuracia": 0.91})[0]
    assert ok is True


def test_nenhuma_chave_reprova_por_ausencia():
    (ok, detail), = _eval(CRITERION, {"auc": 0.9})[0]
    assert ok is False and "não está em metrics.json" in detail


# --- Revisão ---------------------------------------------------------------------------------------------------


def _write(root: Path, rel: str, content) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


async def _review(tmp_path, metrics, criteria=(CRITERION,), reply='{"status": "pass", "issues": []}'):
    t = AgentTask(agent_id="developer", prompt="x", task_name=TASK, validation_criteria=list(criteria))
    contract = build_developer_contract(t, [t], None, "tarefa", researcher_tainted=False)
    _write(tmp_path, f"{TASK}/metrics.json", {"metrics": metrics})
    provider = FakeRecordingProvider(script=[reply])
    with patch("src.agents.validator.agent.record_llm_call"):
        review = await ValidatorAgent(provider=provider).review_result(
            task=t, response_text="ok", output_dir=tmp_path, contract=contract
        )
    return review, provider


@pytest.mark.asyncio
async def test_revisao_registra_criterio_ambiguo_sem_chamar_o_llm(tmp_path):
    """Scenario: Ambiguidade."""
    review, provider = await _review(tmp_path, QUALIFIED)
    assert review.outcome == "criterio_ambiguo" and review.status == "fail" and not review.is_approved
    assert review.verified is False and provider.calls == []
    assert review.ambiguities == [
        {"criterio": "c1", "texto": CRITERION, "chaves": ["modelo_a.acuracia", "modelo_b.acuracia"]}
    ]
    assert review.issues == ["critério c1 de `treinar_modelo_a` é ambíguo: modelo_a.acuracia, modelo_b.acuracia"]
    assert review.contract_sha256


@pytest.mark.asyncio
async def test_chave_sem_qualificador_aprova_sem_levar_o_criterio_ao_llm(tmp_path):
    with patch("src.config.REVIEW_INTEGRITY_ALWAYS", False):
        review, provider = await _review(tmp_path, {"acuracia": 0.91, **QUALIFIED})
    assert review.status == "pass" and provider.calls == []


@pytest.mark.asyncio
async def test_falha_real_de_outro_criterio_prevalece_sobre_a_ambiguidade(tmp_path):
    review, _ = await _review(tmp_path, {"f1": 0.5, **QUALIFIED}, criteria=[CRITERION, "f1 >= 0.8"])
    assert review.outcome == "reprovado" and review.ambiguities == []


@pytest.mark.asyncio
async def test_sem_contrato_o_grupo_nao_nomeado_vai_ao_llm(tmp_path):
    t = AgentTask(agent_id="developer", prompt="x", task_name=TASK, validation_criteria=[CRITERION])
    _write(tmp_path, f"{TASK}/metrics.json", {"metrics": QUALIFIED})
    provider = FakeRecordingProvider(script=['{"status": "pass", "issues": []}'])
    with patch("src.agents.validator.agent.record_llm_call"):
        review = await ValidatorAgent(provider=provider).review_result(task=t, response_text="ok", output_dir=tmp_path)
    assert review.outcome != "criterio_ambiguo" and len(provider.calls) == 1


# --- Devolução da tentativa ------------------------------------------------------------------------------------


def test_devolucao_uma_vez_por_subtarefa():
    tracker = UsageTracker(UsageBudget.from_config(), "e1")
    assert tracker.record_task_attempt(TASK) == 1
    assert tracker.refund_task_attempt(TASK) is True and tracker.task_attempts(TASK) == 0
    assert tracker.record_task_attempt(TASK) == 1
    assert tracker.refund_task_attempt(TASK) is False and tracker.task_attempts(TASK) == 1
    assert tracker.refund_task_attempt("sem_tentativa") is False


# --- Laço ------------------------------------------------------------------------------------------------------


class AmbiguousHarness(ContractHarness):
    """O Developer grava só chaves qualificadas (e o laço revisa com o Validator real)."""

    async def _run(self, task_: Any, ctx: Any) -> AgentResult:
        result = await super()._run(task_, ctx)
        if task_.agent_id == "developer":
            folder = self.session_dir / task_.task_name
            (folder / "metrics.json").write_text(json.dumps({"metrics": QUALIFIED}), encoding="utf-8")
        return result


def _events(h):
    seen: list[dict] = []
    h.extra_patches += [
        patch("src.config.REVIEW_ENABLED", True),
        patch("src.config.REVIEW_MODE", "per_subtask"),
        patch("src.config.ON_PLAN_REJECTIONS", "parar"),
        patch.object(TelemetryCollector, "record_agent_event", autospec=True,
                     side_effect=lambda self, **kw: seen.append(kw)),
    ]
    return seen


@pytest.mark.asyncio
async def test_laco_devolve_a_tentativa_uma_vez_e_leva_o_caso_ao_researcher(tmp_path):
    """Scenarios: Ambiguidade, Ambiguidade repetida e Observação no replanejamento (criterio_ambiguo)."""
    p = plan([task(TASK, validation_criteria=[CRITERION], expected_artifacts=[])], [hyp("h1")])
    h = AmbiguousHarness(tmp_path, plans=[p, p, p])
    seen = _events(h)
    await h.run(budget=UsageBudget.from_config(max_task_retries=3))
    reviews = [e["payload"] for e in seen if e.get("event_type") == "subtask_review"]
    assert len(reviews) >= 2 and all(r["outcome"] == "criterio_ambiguo" for r in reviews)
    assert reviews[0]["criterio_ambiguo"] == [{"criterio": "c1", "chaves": ["modelo_a.acuracia", "modelo_b.acuracia"]}]
    assert reviews[0]["devolucao_recusada"] is False and reviews[1]["devolucao_recusada"] is True
    assert "critério c1 de `treinar_modelo_a` é ambíguo" in h.planner_prompts[1]
    assert "PROBLEMAS ENCONTRADOS" in h.planner_prompts[1]  # subtarefa não concluída: replanejamento de correção
    state = next(t for t in h.checkpoint().subtarefas if t.task_name == TASK)
    assert state.status in ("falhou", "abandonada") and state.causa_falha == "ambigua"


@pytest.mark.asyncio
async def test_laco_leva_observacoes_do_revisor_ao_replanejamento(tmp_path):
    """Scenario: Observação no replanejamento."""
    p = plan([task(TASK, validation_criteria=["relatório salvo"])], [hyp("h1")])
    h = ContractHarness(tmp_path, plans=[p, p])
    note = "o critério deveria exigir validação cruzada"
    h.orch.validator.review_result = AsyncMock(return_value=ReviewResult(
        is_approved=True, status="pass", feedback="ok", observations=[note, note]))
    _events(h)
    await h.run()
    prompt = h.planner_prompts[1]
    assert f"{TASK}: {note}" in prompt and prompt.count(note) == 1  # sem repetir texto igual
    assert prompt.index("RESULTADO DO CICLO ANTERIOR") < prompt.index(note)


@pytest.mark.asyncio
async def test_observacoes_limitadas_por_ciclo(tmp_path):
    from src.orchestration.exploration_feedback import review_observations_feedback

    items = [("t", f"obs {i}") for i in range(30)]
    with patch("src.config.REVIEW_OBSERVATIONS_MAX", 3):
        text = review_observations_feedback(items)
    assert "obs 2" in text and "obs 3" not in text
    assert review_observations_feedback([]) == "" and review_observations_feedback([("t", "  ")]) == ""
