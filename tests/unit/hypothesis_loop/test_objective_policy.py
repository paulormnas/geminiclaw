"""Política ao atingir o objetivo no laço (v18.7-exploration-limits, tarefa 5.4; ``specs/hypothesis-loop``). Sem LLM."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.knowledge.objective import ObjectiveMemory, ObjectiveState
from src.orchestration.exploration import ExplorationSession
from src.orchestration.objective_tracking import Achievement, ObjectiveTracker
from src.session.continuity import Checkpoint, CheckpointError
from tests.support.exploration_world import LoopHarness, hyp, plan, task
from tests.support.hypothesis_world import PESQUISADOR

pytestmark = pytest.mark.unit

DETAILS = {"resultado_id": "r-1", "hipotese_id": "h-1", "valor": 0.9}


def reached(desfecho=None, tipo="limiar", details=None, atingido=True):
    state = ObjectiveState(tipo, atingido, desfecho, atingido, "nao_avaliavel", details or DETAILS, ObjectiveMemory())
    return patch("src.orchestration.objective_tracking.evaluate", return_value=state)


def capture_events():
    events: list[tuple[str, dict]] = []
    return events, patch.object(
        ExplorationSession, "_emit", autospec=True, side_effect=lambda self, kind, payload: events.append((kind, payload))
    )


def set_policy(h, policy):
    crit = dict(h.w.problem.properties["criterio_sucesso"])
    crit["ao_atingir_objetivo"] = policy
    h.w.store.update_node(h.w.problem.id, {"criterio_sucesso": crit}, actor=PESQUISADOR)


def marks(h):
    return h.w.raw.get_node(h.w.problem.id).properties.get("objetivo_atingido") or []


@pytest.mark.asyncio
async def test_padrao_do_modo_automatico_para_e_registra_evento_e_marco(tmp_path):
    """Scenario: Padrão do modo automático — fecha com solucao_encontrada; evento com politica = parar."""
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])])
    events, emit = capture_events()
    h.extra_patches += [reached(), emit]
    await h.run()
    assert h.stop_reason == "solucao_encontrada"
    (payload,) = [p for kind, p in events if kind == "objetivo_atingido"]
    assert payload["politica"] == "parar" and payload["resultado_id"] == "r-1" and payload["tipo"] == "limiar"
    (mark,) = marks(h)
    assert mark["sessao_id"] == h.w.sid and mark["resultado_id"] == "r-1" and mark["valor"] == 0.9


@pytest.mark.asyncio
async def test_continuar_alem_do_alvo_registra_uma_vez_e_nao_fecha(tmp_path):
    """Scenario: Continuar além do alvo — o evento e o marco aparecem uma única vez."""
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first, first])
    set_policy(h, "continuar")
    events, emit = capture_events()
    h.extra_patches += [reached(), emit]
    await h.run()
    assert h.stop_reason == "sem_caminhos_promissores"
    assert [k for k, _ in events].count("objetivo_atingido") == 1 and len(marks(h)) == 1


@pytest.mark.asyncio
async def test_perguntar_no_auto_sem_resposta_segue_com_o_pedido_pendente(tmp_path):
    """Scenario: política ``perguntar`` fora do assisted — segue explorando; o pedido continua pendente."""
    asked: list[Achievement] = []

    def confirmer(achievement):
        asked.append(achievement)

    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first, first], confirmer=confirmer)
    set_policy(h, "perguntar")
    h.extra_patches.append(reached())
    await h.run()
    assert h.stop_reason == "sem_caminhos_promissores" and len(asked) >= 1 and asked[0].politica == "perguntar"


@pytest.mark.asyncio
async def test_resposta_encerrar_no_auto_com_perguntar_fecha(tmp_path):
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])], confirmer=lambda a: "encerrar")
    set_policy(h, "perguntar")
    h.extra_patches.append(reached())
    await h.run()
    assert h.stop_reason == "solucao_encontrada"


@pytest.mark.asyncio
async def test_estado_do_objetivo_vai_para_o_checkpoint(tmp_path):
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])])
    h.extra_patches.append(reached())
    await h.run()
    state = h.checkpoint().exploracao_estado
    assert state["atingido"]["resultado_id"] == "r-1" and "memoria" in state


def test_restauracao_do_estado_e_tolerante():
    tracker = ObjectiveTracker(
        lambda: None, "p", "s", mode="auto", emit=lambda *a: None, confirmer=lambda a: None,
        requester=lambda *a: None,
    )
    tracker.restore({"memoria": {"best_value": 0.7}, "atingido": {"referencia": "r-9", "tipo": "limiar"},
                     "politica_sessao": "continuar", "relatados": ["x", 3]})
    assert tracker.memory.best_value == 0.7 and tracker.achievement.reference == "r-9"
    assert tracker.session_policy == "continuar" and tracker.reported == {"x"}
    assert tracker.decision() == "seguir"  # a política efetiva da sessão é continuar
    tracker.restore("lixo")  # não levanta nem apaga o que já havia
    assert tracker.achievement.reference == "r-9"


def test_checkpoint_recusa_estado_enorme():
    from src.session.continuity import _exploration_state

    with pytest.raises(CheckpointError):
        _exploration_state({"x": "a" * 30_000})
    with pytest.raises(CheckpointError):
        _exploration_state([1])
    assert _exploration_state(None) == {}
    assert Checkpoint.__dataclass_fields__["exploracao_estado"]


@pytest.mark.asyncio
async def test_todas_contrariadas_registra_e_pede_hipoteses_novas_sem_fechar(tmp_path):
    """Scenario: Todas contrariadas — evento objetivo_desfecho, sessão aberta e feedback ao Researcher."""
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first, first])
    events, emit = capture_events()
    h.extra_patches += [reached("todas_contrariadas", "discriminacao", {"contrariadas": ["a", "b"]}, atingido=False), emit]
    await h.run()
    assert h.stop_reason == "sem_caminhos_promissores"
    assert [p["desfecho"] for k, p in events if k == "objetivo_desfecho"] == ["todas_contrariadas"]
    assert any("OBJETIVO DE DISCRIMINAÇÃO" in p for p in h.planner_prompts[1:])


@pytest.mark.asyncio
async def test_varias_compativeis_registra_o_pedido_uma_vez(tmp_path):
    requests: list[tuple] = []
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first, first])
    state = {"compativeis": ["a", "b"]}
    h.extra_patches += [
        reached("varias_compativeis", "discriminacao", state, atingido=False),
        patch.object(ExplorationSession, "_request_continuity",
                     autospec=True, side_effect=lambda self, *args: requests.append(args)),
    ]
    await h.run()
    assert len(requests) == 1 and requests[0][0] == "varias_compativeis" and "aceitar_conjunto" in requests[0][2]


@pytest.mark.asyncio
async def test_experimento_fisico_nao_executa_no_sandbox(tmp_path):
    """Scenario: Experimento físico — a subtarefa é retirada com o código ``experimento_fisico``."""
    p = plan([task("fisico", "h1", experimento_fisico=True, discrimina=["h1"]), task("sim", "h1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[p, p])
    events, emit = capture_events()
    h.extra_patches.append(emit)
    await h.run()
    assert "fisico" not in h.ran and "sim" in h.ran
    cycle = next(p for k, p in events if k == "hypothesis_cycle")
    assert cycle["retiradas_por_motivo"] == {"experimento_fisico": 1}
    assert all(n.properties["status"] != "abandonada" for n in h.hypotheses())


@pytest.mark.asyncio
async def test_cobertura_com_novidade_baixa_avisa_e_pede_sem_fechar(tmp_path):
    """Scenario: Aviso de novidade baixa — evento ``cobertura_aviso`` e pedido ``cobertura_saturada``."""
    requests: list[tuple] = []
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first, first])
    events, emit = capture_events()
    state = ObjectiveState("cobertura", False, None, False, "so_aviso", {"taxa": 0.2}, ObjectiveMemory())
    h.extra_patches += [
        patch("src.orchestration.objective_tracking.evaluate", return_value=state), emit,
        patch.object(ExplorationSession, "_request_continuity", autospec=True,
                     side_effect=lambda self, *args: requests.append(args)),
    ]
    await h.run()
    assert h.stop_reason == "sem_caminhos_promissores"
    assert [p["taxa"] for k, p in events if k == "cobertura_aviso"] == [0.2]
    assert len(requests) == 1 and requests[0][0] == "cobertura_saturada" and "objetivo_atingido" in requests[0][2]


@pytest.mark.asyncio
async def test_aguarda_experimento_fisico_registra_o_desfecho_com_a_subtarefa_e_o_pedido(tmp_path):
    """Scenario: Experimento físico — desfecho com o nome da subtarefa e pedido ``aguarda_experimento_fisico``."""
    requests: list[tuple] = []
    first = plan([task("t1")], [hyp("h1")])
    h = LoopHarness(tmp_path, plans=[first, first])
    events, emit = capture_events()
    h.extra_patches += [
        reached("aguarda_experimento_fisico", "discriminacao", {"subtarefa": "bancada"}, atingido=False), emit,
        patch.object(ExplorationSession, "_request_continuity", autospec=True,
                     side_effect=lambda self, *args: requests.append(args)),
    ]
    await h.run()
    (outcome,) = [p for k, p in events if k == "objetivo_desfecho"]
    assert outcome["desfecho"] == "aguarda_experimento_fisico" and outcome["subtarefa"] == "bancada"
    assert [r[0] for r in requests] == ["aguarda_experimento_fisico"]
