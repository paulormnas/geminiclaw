"""Proteções contra falha (v18.7-exploration-limits, seção 8; ``specs/pipeline-robustness``). Sem LLM.

A espera por pedido do pesquisador fora dos contadores (8.2) é coberta em
``tests/unit/persistent_gate/test_session_readers.py`` (``idle_cycles`` e disjuntor não mudam na espera).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.knowledge.hypothesis_cycle import ApprovalDecision
from src.orchestration.autonomous_loop import AutonomousLoop, CycleProgress
from src.orchestration.exploration import ExplorationSession
from tests.support.exploration_world import APPROVED, REJECTED, LoopHarness, hyp, plan, task
from tests.support.fake_gate import FakeGate

pytestmark = pytest.mark.unit


# --- 8.1 disjuntor pelo grafo ----------------------------------------------------------------------------------------


def progress(experiments=None, results=None, sigs=(), ok=()):
    return CycleProgress(frozenset(ok), frozenset(sigs), experiments, results)


def test_experimento_ou_resultado_novo_e_progresso():
    assert progress(2, 1).advanced_from(progress(1, 1))
    assert progress(1, 2).advanced_from(progress(1, 1))


def test_sem_experimento_nem_resultado_novo_e_sem_progresso_mesmo_com_sucessos_novos():
    assert not progress(1, 1, ok=("a", "b")).advanced_from(progress(1, 1, ok=("a",)))


def test_erro_diferente_e_progresso():
    assert progress(1, 1, sigs=("x",)).advanced_from(progress(1, 1, sigs=("y",)))


def test_sem_projeto_vale_a_regra_por_nomes():
    assert progress(ok=("a", "b")).advanced_from(progress(ok=("a",)))
    assert not progress(ok=("a",)).advanced_from(progress(ok=("a",)))


@pytest.mark.asyncio
async def test_contagem_do_grafo_pela_sessao(tmp_path):
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])])
    await h.run()
    experiments, results = ExplorationSession.session_progress(
        type("S", (), {"store": h.w.raw, "ctx": type("C", (), {"session_id": h.w.sid})()})()
    )
    assert experiments >= 1 and results >= 1


# --- 8.3 planos rejeitados -------------------------------------------------------------------------------------------


def sequence(*verdicts):
    """Validator que devolve os veredictos em ordem e depois aprova."""
    calls = iter(verdicts)

    async def validate(*args, **kwargs):
        return next(calls, APPROVED)

    return AsyncMock(side_effect=validate)


def harness(tmp_path, rejections, *, mode="auto"):
    """Os primeiros ``rejections`` planos são reprovados pelo Validator; o seguinte é aprovado."""
    ok = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(
        tmp_path, mode=mode, plans=["[]"] * rejections + [ok], validator=sequence(*[REJECTED] * rejections),
        approver=lambda items: {i.id: ApprovalDecision("aprovar") for i in items},
    )
    h.orch.curator_suggest = AsyncMock(return_value=[])
    return h


def run_patches(h, **extra):
    events: list[tuple[str, dict]] = []
    h.extra_patches += [
        patch("src.config.MAX_PLAN_RETRIES", 2), patch("src.orchestration.autonomous_loop.MAX_PLAN_RETRIES", 2),
        patch("src.orchestration.orchestrator.MAX_PLANNING_ITERATIONS", 1),
        patch.object(ExplorationSession, "_emit", autospec=True,
                     side_effect=lambda self, k, p: events.append((k, p))),
        patch.object(AutonomousLoop, "_usage_fraction", return_value=0.0),
        *[patch(name, value) for name, value in extra.items()],
    ]
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "assisted"])
async def test_explorar_aciona_o_curator_e_nao_fecha(tmp_path, mode):
    """Scenario: Planos rejeitados com a política explorar — intervenção com as issues; sem pedido nem fechamento."""
    h = harness(tmp_path, 2, mode=mode)
    gate = FakeGate()
    events = run_patches(h)
    h.extra_patches.append(patch("src.gate.persistent_gate.session_gate", return_value=gate))
    await h.run()
    assert h.stop_reason != "planos_rejeitados"
    (intervention,) = [p for k, p in events if k == "estagnacao_intervencao"]
    assert intervention["origem"] == "planos_rejeitados" and intervention["intervencao"] == 1
    context = next(c.args[1] for c in h.orch.curator_suggest.await_args_list if len(c.args) > 1 and c.args[1])
    assert context.intervencao == 1 and context.issues
    assert not [r for r in gate.requests if r.motivo == "planos_rejeitados"]
    assert h.ran == ["t1"]  # depois da intervenção o plano aprovado executa


@pytest.mark.asyncio
async def test_explorar_com_intervencoes_esgotadas_pede_sem_bloquear(tmp_path):
    """Scenario: intervenções esgotadas — evento e pedido ``intervencoes_esgotadas``; a sessão segue."""
    h = harness(tmp_path, 4)
    gate = FakeGate()
    events = run_patches(h, **{"src.config.EXPLORATION_MAX_INTERVENTIONS": 1})
    h.extra_patches.append(patch("src.gate.persistent_gate.session_gate", return_value=gate))
    await h.run()
    kinds = [k for k, _ in events]
    assert kinds.count("estagnacao_intervencao") == 1 and "intervencoes_esgotadas" in kinds
    assert [r.motivo for r in gate.requests] == ["intervencoes_esgotadas"]
    assert h.stop_reason != "planos_rejeitados" and h.ran == ["t1"]


@pytest.mark.asyncio
async def test_explorar_com_estagnacao_desligada_so_zera(tmp_path):
    h = harness(tmp_path, 2)
    events = run_patches(h, **{"src.config.EXPLORATION_STALL_CYCLES": 0})
    h.extra_patches.append(patch("src.gate.persistent_gate.session_gate", return_value=FakeGate()))
    await h.run()
    assert "estagnacao_intervencao" not in [k for k, _ in events] and h.ran == ["t1"]


@pytest.mark.asyncio
async def test_parar_no_auto_fecha_com_planos_rejeitados(tmp_path):
    """Scenario: política parar no auto — fecha com ``planos_rejeitados`` e checkpoint."""
    h = harness(tmp_path, 4)
    run_patches(h, **{"src.config.ON_PLAN_REJECTIONS": "parar"})
    await h.run()
    assert h.stop_reason == "planos_rejeitados" and h.checkpoint().estado == "fechado" and h.ran == []


def answering(gate, action):
    async def wait(self, master_session_id, decisoes):
        (request,) = [r for r in gate.requests if r.motivo == "planos_rejeitados"]
        gate.respond(request.id, resposta={"acao": action})
        return "respondido"

    return patch.object(AutonomousLoop, "_wait_for_researcher", autospec=True, side_effect=wait)


@pytest.mark.asyncio
@pytest.mark.parametrize("action,stop", [("parar", "planos_rejeitados"), ("continuar", None)])
async def test_parar_no_assisted_pede_e_aplica_a_resposta(tmp_path, action, stop):
    """Scenario: política parar no assistido — pedido ``planos_rejeitados``; ``continuar`` zera, ``parar`` fecha."""
    h = harness(tmp_path, 2, mode="assisted")
    gate = FakeGate()
    run_patches(h, **{"src.config.ON_PLAN_REJECTIONS": "parar"})
    h.extra_patches += [patch("src.gate.persistent_gate.session_gate", return_value=gate), answering(gate, action)]
    # o pedido nasce com a sessão da cadeia: o FakeGate recebe session_id pelo `_request_continuity`
    await h.run()
    (request,) = [r for r in gate.requests if r.motivo == "planos_rejeitados"]
    assert request.consumido and "rejeitou 2 planos" in request.pergunta
    if stop:
        assert h.stop_reason == stop and h.ran == []
    else:
        assert h.stop_reason != "planos_rejeitados" and h.ran == ["t1"]


@pytest.mark.asyncio
async def test_parar_no_semi_pede_e_suspende(tmp_path):
    h = harness(tmp_path, 2, mode="semi")
    gate = FakeGate()
    run_patches(h, **{"src.config.ON_PLAN_REJECTIONS": "parar"})
    h.extra_patches.append(patch("src.gate.persistent_gate.session_gate", return_value=gate))
    await h.run()
    assert [r.motivo for r in gate.requests] == ["planos_rejeitados"]
    assert h.stop_reason == "aguarda_pesquisador" and h.ran == []


def test_valor_invalido_de_on_plan_rejections(monkeypatch):
    """Scenario: Valor inválido de ON_PLAN_REJECTIONS — a inicialização falha citando a variável e os valores."""
    import importlib

    import src.config as config

    monkeypatch.setenv("ON_PLAN_REJECTIONS", "sempre")
    try:
        with pytest.raises(config.ConfigurationError, match="ON_PLAN_REJECTIONS.*explorar.*parar"):
            importlib.reload(config)
    finally:
        monkeypatch.delenv("ON_PLAN_REJECTIONS")
        importlib.reload(config)
