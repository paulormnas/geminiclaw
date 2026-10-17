"""Objetivo proposto no plano (v18.7-exploration-limits, tarefa 5.2; ``specs/hypothesis-loop``). Sem LLM real."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator.agent import ValidationResult, ValidatorAgent
from src.knowledge.hypotheses import split_plan
from src.knowledge.metric_definition import MetricDecl
from src.knowledge.objective_definition import FRONTEIRA_RECUSADA, objective_issues, parse_objective
from src.llm.base import LLMResponse
from src.orchestration.exploration import ExplorationSession
from tests.support.exploration_world import LoopHarness, hyp, plan, task
from tests.support.hypothesis_world import PESQUISADOR

pytestmark = pytest.mark.unit

METRICA = {"nome": "R2", "sentido": "maior_melhor", "limiar": 0.9, "delta_min": 0.05, "justificativa": "contínuo"}
DISC = {
    "tipo": "discriminacao", "justificativa": "duas explicações rivais",
    "hipoteses_concorrentes": [{"ref": "h1", "predicao": "A"}, {"ref": "h2", "predicao": "B"}],
}
APPROVED = ValidationResult(
    is_valid=True, status="approved", reason="ok", metrics_approved=True, objective_approved=True
)
STEPS = [{"agent_id": "developer", "task_name": "t", "prompt": "p", "validation_criteria": ["r2 >= 0.8"]}]


# --- leitura e conferência ---------------------------------------------------------------------------------------


def test_objetivo_vem_no_extras_do_plano():
    _, extras = split_plan({"subtarefas": [], "objetivo": DISC})
    assert extras.objetivo.tipo == "discriminacao" and [c.ref for c in extras.objetivo.concorrentes] == ["h1", "h2"]
    assert split_plan({"subtarefas": [], "hipoteses": []})[1].objetivo is None
    assert parse_objective("lixo") is None


def test_politica_do_plano_e_marcada_como_ignorada():
    decl = parse_objective({**DISC, "ao_atingir_objetivo": "continuar"})
    assert decl.politica_ignorada and "ao_atingir_objetivo" not in decl.as_dict()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "Objetivo ausente"),
        ({"tipo": "fronteira"}, FRONTEIRA_RECUSADA),
        ({"tipo": "maximo"}, "'tipo' deve ser um de"),
        ({"tipo": "discriminacao", "hipoteses_concorrentes": [{"ref": "h1", "predicao": "A"}]}, "ao menos duas"),
        ({"tipo": "discriminacao", "hipoteses_concorrentes": [{"ref": "h1", "predicao": "A"},
                                                              {"ref": "h9", "predicao": "B"}]}, "não está declarada"),
        ({"tipo": "discriminacao", "hipoteses_concorrentes": [{"ref": "h1", "predicao": "A"},
                                                              {"ref": "h2", "predicao": ""}]}, "exige 'predicao'"),
        ({"tipo": "cobertura", "hipoteses_concorrentes": [{"ref": "h1", "predicao": "A"}]}, "não leva"),
    ],
)
def test_reprovacoes_deterministicas(raw, expected):
    issues = objective_issues(parse_objective(raw), declared_refs={"h1", "h2"}, criterion={}, metrics=[])
    assert issues and expected in " ".join(issues)


def test_limiar_exige_metrica_e_delta_min():
    decl = parse_objective({"tipo": "limiar"})
    assert "métrica" in objective_issues(decl, declared_refs=set(), criterion={}, metrics=[])[0]
    no_delta = [MetricDecl("R2", "maior_melhor", 0.9, "j")]
    assert "delta_min" in objective_issues(decl, declared_refs=set(), criterion={}, metrics=no_delta)[0]
    ok = [MetricDecl("R2", "maior_melhor", 0.9, "j", delta_min=0.05)]
    assert objective_issues(decl, declared_refs=set(), criterion={}, metrics=ok) == []
    assert objective_issues(decl, declared_refs=set(), criterion={"metrica_id": "m", "delta_min": 0.1}, metrics=[]) == []


# --- Validator -----------------------------------------------------------------------------------------------------


def agent_with(reply: str):
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text=reply))
    return ValidatorAgent(provider=provider), provider


@pytest.mark.asyncio
async def test_plano_sem_objetivo_ou_com_fronteira_e_reprovado_sem_llm():
    """Scenarios: Plano sem objetivo exigido / Fronteira recusada."""
    for issues in (["Objetivo ausente: ..."], [FRONTEIRA_RECUSADA]):
        agent, provider = agent_with('{"status": "approved"}')
        result = await agent.validate_plan(
            STEPS, "t", objective_definition={"problema": {}, "objetivo": None, "problemas": issues}
        )
        assert not result.is_valid and result.deterministic and not result.objective_approved
        assert issues[0] in result.issues
        provider.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_validator_llm_aprova_ou_reprova_o_objetivo():
    definition = {"problema": {"titulo": "T"}, "objetivo": DISC, "problemas": []}
    base = '"status": "approved", "reason": "ok", "issues": []'

    async def run(extra: str) -> ValidationResult:
        agent, _ = agent_with("{" + base + extra + "}")
        with patch("src.agents.validator.agent.record_llm_call"):
            return await agent.validate_plan(STEPS, "t", objective_definition=definition)

    ok = await run(', "objetivo_status": "approved"')
    assert ok.is_valid and ok.objective_approved
    bad = await run(', "objetivo_status": "revision_needed", "objetivo_issues": ["predições iguais"]')
    assert not bad.is_valid and "Objetivo: predições iguais" in bad.issues
    silent = await run("")
    assert not silent.is_valid and not silent.objective_approved


# --- laço ------------------------------------------------------------------------------------------------------------


def auto_without_objective(tmp_path, plans, validator=None):
    h = LoopHarness(tmp_path, plans=plans, validator=validator or AsyncMock(return_value=APPROVED))
    h.w.store.update_node(h.w.problem.id, {"criterio_sucesso": {}}, actor=PESQUISADOR)
    return h


@pytest.mark.asyncio
async def test_objetivo_aprovado_no_auto_e_gravado_com_as_concorrentes(tmp_path):
    """Scenarios: Objetivo aprovado no auto / Política vinda do plano é ignorada."""
    p = plan([task("t1", "h1"), task("t2", "h2")], [hyp("h1", "Explicação A"), hyp("h2", "Explicação B muito diferente")],
             metricas=[METRICA], objetivo={**DISC, "ao_atingir_objetivo": "continuar"})
    h = auto_without_objective(tmp_path, [p, p])
    events: list[tuple[str, dict]] = []
    with patch.object(ExplorationSession, "_emit", autospec=True,
                      side_effect=lambda self, kind, payload: events.append((kind, payload))):
        await h.run()
    node = h.w.raw.get_node(h.w.problem.id)
    crit = node.properties["criterio_sucesso"]
    assert crit["tipo"] == "discriminacao" and crit["definido_por"] == "agente"
    assert "ao_atingir_objetivo" not in crit and "alvo" not in crit and "delta_min" not in crit
    rivals = [h.w.raw.get_node(i["hipotese_id"]) for i in crit["hipoteses_concorrentes"]]
    assert [r.properties["concorrente"] for r in rivals] == [True, True]
    assert {r.properties["predicao"] for r in rivals} == {"A", "B"}
    (defined,) = [p for k, p in events if k == "objetivo_definido"]
    assert defined["tipo"] == "discriminacao" and defined["politica_ignorada"] is True
    assert "DEFINIÇÃO DE OBJETIVO" in h.planner_prompts[0]


@pytest.mark.asyncio
async def test_objetivo_reprovado_nao_e_gravado(tmp_path):
    p = plan([task("t1", "h1")], [hyp("h1")], metricas=[METRICA], objetivo={"tipo": "cobertura"})
    rejected = ValidationResult(is_valid=False, status="revision_needed", reason="no", issues=["Objetivo: ruim"],
                                signature="s")
    h = auto_without_objective(tmp_path, [p], validator=AsyncMock(return_value=rejected))
    with patch("src.orchestration.orchestrator.MAX_PLANNING_ITERATIONS", 1), patch("src.config.MAX_PLAN_RETRIES", 1), \
            patch("src.orchestration.autonomous_loop.MAX_PLAN_RETRIES", 1):
        await h.run()
    assert "tipo" not in h.w.raw.get_node(h.w.problem.id).properties["criterio_sucesso"]


@pytest.mark.asyncio
async def test_revisao_no_semi_vira_pedido_e_nao_muda_o_objetivo(tmp_path):
    """Scenario: Revisão no modo semi."""
    requests: list[tuple] = []

    class Gate:
        def request(self, *args, **kwargs):
            requests.append((args, kwargs))

    p = plan([task("t1", "h1")], [hyp("h1")], objetivo={"tipo": "cobertura", "justificativa": "explorar"})
    h = LoopHarness(tmp_path, mode="semi", plans=[p])
    with patch("src.gate.persistent_gate.session_gate", return_value=Gate()):
        await h.run()
    assert h.w.raw.get_node(h.w.problem.id).properties["criterio_sucesso"]["tipo"] == "limiar"
    assert requests and requests[0][0][0] == "confirmar_problema" and requests[0][1]["motivo"] == "revisao_objetivo"
    assert "cobertura" in requests[0][0][2]


@pytest.mark.asyncio
async def test_objetivo_valido_do_pesquisador_nao_e_exigido_nem_substituido(tmp_path):
    p = plan([task("t1", "h1")], [hyp("h1")], objetivo={"tipo": "cobertura"})
    h = LoopHarness(tmp_path, plans=[p])
    await h.run()
    assert "DEFINIÇÃO DE OBJETIVO" not in h.planner_prompts[0]
    assert h.w.raw.get_node(h.w.problem.id).properties["criterio_sucesso"]["tipo"] == "limiar"
