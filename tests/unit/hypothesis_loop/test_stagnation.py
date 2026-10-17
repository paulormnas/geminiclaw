"""Estagnação, intervenção e saturação (v18.7-exploration-limits, seção 6; ``specs/hypothesis-loop``). Sem LLM."""

from __future__ import annotations

import math
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from src.knowledge.objective import CycleView, ObjectiveMemory, ObjectiveState, evaluate
from src.knowledge.suggestions import StallContext, SuggestionStore, suggest_paths
from src.orchestration.autonomous_loop import AutonomousLoop
from src.orchestration.exploration import ExplorationSession
from src.orchestration.objective_tracking import Achievement, ObjectiveTracker
from src.orchestration.stagnation import STEP_CLOSE, STEP_INTERVENTION, StagnationPolicy, patience
from tests.support.exploration_world import LoopHarness, hyp, plan, task
from tests.support.fake_gate import FakeGate
from tests.support.hypothesis_world import PESQUISADOR
from tests.unit.hypothesis_loop.test_objective import LIMIAR, FakeReader, res

pytestmark = pytest.mark.unit


class Rig:
    """Rastreador + política com eventos e pedidos capturados; os ciclos usam ``evaluate`` de verdade."""

    def __init__(self, *, mode="auto", fraction=0.0, criterion=None):
        self.events: list[tuple[str, dict]] = []
        self.requests: list[tuple[str, str]] = []
        self.criterion = criterion or LIMIAR
        self.tracker = ObjectiveTracker(
            lambda: None, "p", "s", mode=mode, emit=lambda k, p: self.events.append((k, p)),
            confirmer=lambda a: None, requester=lambda m, ref, o, q: self.requests.append((m, ref)),
        )
        self.policy = StagnationPolicy(
            self.tracker, mode=mode, emit=lambda k, p: self.events.append((k, p)),
            requester=lambda m, ref, o, q: self.requests.append((m, ref)), fraction=lambda: fraction,
        )
        self.reader = FakeReader()

    def cycle(self, *values, hip="h1"):
        """Fim de um ciclo com os resultados novos; devolve o passo da política."""
        self.reader.results = [*self.reader.results, *(res(v, hip) for v in values)]
        state = evaluate(self.reader, self.criterion, self.tracker.memory, CycleView(1))
        self.tracker.memory = state.memory
        return self.policy.observe(state, self.criterion)

    def kinds(self):
        return [k for k, _ in self.events]


def seed(rig, *values):
    """Resultados já existentes, com melhor valor e EP conhecidos (primeiro ciclo conta como avanço)."""
    assert rig.cycle(*values) is None


# --- paciência --------------------------------------------------------------------------------------------------------


def test_paciencia_cresce_com_intervencoes_e_consumo():
    assert patience(5, 0.5, 0, 0.0) == 5
    assert patience(5, 0.5, 1, 0.5) == 12  # ceil(5 × 1,5 × 1,5)
    assert patience(5, 0.5, 3, 0.0) == 13  # ceil(5 × 2,5)
    assert patience(5, 0.0, 2, 0.0) == 5


# --- intervenção ------------------------------------------------------------------------------------------------------


def test_primeira_intervencao_no_quinto_ciclo_sem_avanco(monkeypatch):
    """Scenario: Primeira intervenção — 5 ciclos sem avanço; contagem e intervenção atualizadas, sessão não fecha."""
    rig = Rig()
    seed(rig, 0.90, 0.91, 0.90)
    steps = [rig.cycle() for _ in range(4)]
    assert steps == [None] * 4 and rig.tracker.memory.cycles_without_advance == 4
    step = rig.cycle()
    assert step.kind == STEP_INTERVENTION and step.intervencao == 1 and step.paciencia == 5
    assert step.ciclos_sem_avanco == 5
    assert rig.tracker.memory.interventions == 1 and rig.tracker.memory.cycles_without_advance == 0


def test_avanco_acima_do_erro_zera_a_contagem_e_as_intervencoes():
    """Scenario: Avanço zera a contagem — 0.93 acima de 0.90 + 1.0 × EP."""
    rig = Rig()
    seed(rig, 0.89, 0.91, 0.90)  # melhor 0.91, EP = s/√3
    best = rig.tracker.memory.best_value
    for _ in range(4):
        assert rig.cycle() is None
    assert rig.tracker.memory.cycles_without_advance == 4
    assert rig.cycle(best + 0.1) is None
    assert rig.tracker.memory.cycles_without_advance == 0 and rig.tracker.memory.interventions == 0


def test_melhora_dentro_do_erro_nao_e_avanco():
    """Scenario: Melhora dentro do erro não é avanço — a contagem chega a 5 e a primeira intervenção é feita."""
    rig = Rig()
    seed(rig, 0.88, 0.92, 0.90)
    for _ in range(3):
        assert rig.cycle() is None
    se = 0.02 / math.sqrt(3)
    step = rig.cycle()  # contagem 4
    assert step is None
    small = rig.tracker.memory.best_value + se / 4
    step = rig.cycle(small)  # melhora minúscula, dentro do erro
    assert step is not None and step.kind == STEP_INTERVENTION and step.ciclos_sem_avanco == 5


def test_negativos_e_ciclos_sem_resultado_nao_zeram_a_contagem():
    rig = Rig()
    seed(rig, 0.90, 0.91)
    rig.cycle(0.40)  # resultado pior (negativo) não é avanço
    rig.cycle(0.30)
    assert rig.tracker.memory.cycles_without_advance == 2


def test_estagnacao_desligada_nao_registra_nada(monkeypatch):
    """Scenario: Estagnação desligada — 30 ciclos sem avanço e nenhum evento."""
    monkeypatch.setattr("src.config.EXPLORATION_STALL_CYCLES", 0)
    rig = Rig()
    seed(rig, 0.90, 0.91)
    assert [rig.cycle() for _ in range(30)] == [None] * 30
    assert "estagnacao_intervencao" not in rig.kinds() and "saturacao_avaliada" not in rig.kinds()


def test_politica_continuar_com_objetivo_atingido_nao_interveem():
    """Scenario: Continuar além do alvo — a política ``continuar`` suspende a estagnação."""
    rig = Rig(criterion={**LIMIAR, "ao_atingir_objetivo": "continuar"})
    rig.tracker.achievement = Achievement("r-1", "limiar", politica="continuar")
    seed(rig, 0.90, 0.91)
    assert [rig.cycle() for _ in range(10)] == [None] * 10
    assert rig.tracker.memory.interventions == 0


def test_paciencia_usa_a_fracao_consumida():
    rig = Rig(fraction=0.5)
    seed(rig, 0.90, 0.91)
    # ceil(5 × 1 × 1,5) = 8 ciclos sem avanço para a primeira intervenção
    assert [rig.cycle() for _ in range(7)] == [None] * 7
    assert rig.cycle().kind == STEP_INTERVENTION


def test_assisted_registra_pedido_de_estagnacao():
    rig = Rig(mode="assisted")
    seed(rig, 0.90, 0.91)
    step = [rig.cycle() for _ in range(5)][-1]
    rig.policy.request_stagnation(step)
    assert rig.requests == [("estagnacao", "estagnacao:1")]
    auto = Rig(mode="auto")
    auto.policy.request_stagnation(step)
    assert auto.requests == []


# --- saturação --------------------------------------------------------------------------------------------------------


def exhaust_interventions(rig):
    """Três intervenções sem avanço (paciência 5, 8, 10) e devolve o passo da última."""
    seed(rig, 0.940, 0.950, 0.945)
    last = None
    for needed in (5, 8, 10):
        for i in range(needed):
            last = rig.cycle()
            assert (last is None) == (i < needed - 1)
        assert last.kind == STEP_INTERVENTION
    return last


def test_saturacao_no_auto_fecha_quando_confirmada():
    """Scenario: Saturação no auto — 3 réplicas, nenhuma melhora acima de SE × EP."""
    rig = Rig(mode="auto")
    exhaust_interventions(rig)
    needed = patience(5, 0.5, 3, 0.0)  # 13
    steps = [rig.cycle() for _ in range(needed)]
    assert steps[:-1] == [None] * (needed - 1) and steps[-1].kind == STEP_CLOSE
    (payload,) = [p for k, p in rig.events if k == "saturacao_avaliada"]
    assert payload["resultado"] == "confirmada" and payload["melhor_valor"] == 0.95 and payload["replicas"] == 3
    assert payload["erro_padrao"] == pytest.approx(0.005 / math.sqrt(3), abs=1e-5)


def test_saturacao_no_semi_registra_pedido_e_segue():
    """Scenario: Saturação no semi — pedido ``saturacao``, sessão não fecha."""
    rig = Rig(mode="semi")
    exhaust_interventions(rig)
    steps = [rig.cycle() for _ in range(patience(5, 0.5, 3, 0.0))]
    assert all(step is None for step in steps)
    assert ("saturacao", "saturacao") in rig.requests
    assert [rig.cycle() for _ in range(3)] == [None] * 3 and rig.requests.count(("saturacao", "saturacao")) == 1


def test_replicas_insuficientes_geram_intervencoes_esgotadas():
    """Scenario: Réplicas insuficientes — evento e pedido ``intervencoes_esgotadas``; a sessão não fecha."""
    rig = Rig(mode="auto")
    seed(rig, 0.94, 0.95)  # só 2 réplicas
    for needed in (5, 8, 10):
        for _ in range(needed):
            step = rig.cycle()
        assert step.kind == STEP_INTERVENTION
    steps = [rig.cycle() for _ in range(patience(5, 0.5, 3, 0.0))]
    assert all(step is None for step in steps)
    assert "intervencoes_esgotadas" in rig.kinds()
    assert ("intervencoes_esgotadas", "intervencoes_esgotadas") in rig.requests
    assert rig.kinds().count("intervencoes_esgotadas") == 1  # o relato não se repete a cada ciclo


def test_resposta_continuar_zera_e_reabre_o_relato():
    """Scenario: Resposta continuar — intervenções e ciclos sem avanço voltam a 0."""
    rig = Rig(mode="semi")
    exhaust_interventions(rig)
    for _ in range(patience(5, 0.5, 3, 0.0)):
        rig.cycle()
    rig.policy.reset()
    assert rig.tracker.memory.interventions == 0 and rig.tracker.memory.cycles_without_advance == 0
    assert not any(k.startswith("estagnacao:") for k in rig.tracker.reported)


def test_cobertura_so_avisa_e_nunca_fecha():
    cover = {"tipo": "cobertura"}
    rig = Rig(mode="auto", criterion=cover)
    steps = []
    for _ in range(40):
        state = evaluate(rig.reader, cover, rig.tracker.memory, CycleView(1, 0))
        rig.tracker.memory = state.memory
        steps.append(rig.policy.observe(state, cover))
    assert all(s is None or s.kind == STEP_INTERVENTION for s in steps)
    assert ("cobertura_saturada", "cobertura") in rig.requests


def test_discriminacao_nao_fecha_por_saturacao():
    """Scenario (varias_compativeis): o pedido do desfecho já existe; a saturação não fecha a sessão."""
    rig = Rig(mode="auto")
    memory = replace(ObjectiveMemory(), interventions=3, cycles_without_advance=20)
    rig.tracker.memory = memory
    state = ObjectiveState("discriminacao", False, "varias_compativeis", False, "confirmada", {}, memory)
    assert rig.policy.observe(state, {"tipo": "discriminacao"}) is None
    assert any(k == "saturacao_avaliada" for k in rig.kinds())


# --- Curator em modo intervenção -------------------------------------------------------------------------------------


def test_intervencao_do_curator_traz_diversificacao_antes_das_fontes_comuns(tmp_path):
    from tests.support.hypothesis_world import HypothesisWorld

    world = HypothesisWorld()
    fresh = suggest_paths(
        world.store, world.pid, tmp_path, intervencao=StallContext(1, 5, 0.9, None), max_suggestions=5
    )
    assert fresh and fresh[0].tipo == "diversificacao" and "5 ciclos sem avanço" in fresh[0].texto
    again = suggest_paths(world.store, world.pid, tmp_path, intervencao=StallContext(1, 5, 0.9, None))
    assert again == []  # a mesma intervenção não repete a sugestão
    second = suggest_paths(world.store, world.pid, tmp_path, intervencao=StallContext(2, 6, 0.9, None))
    assert [s.tipo for s in second] == ["diversificacao"]
    assert len(SuggestionStore(tmp_path).pending()) == 2


# --- laço -------------------------------------------------------------------------------------------------------------


def stuck_state(tipo="limiar", saturacao="nao_avaliavel", atingido=False):
    """Cada ciclo é sem avanço: a memória só conta."""

    def fake(reader, criterion, previous, cycle):
        memory = replace(previous, cycles_without_advance=previous.cycles_without_advance + 1)
        details = {"melhor_valor": 0.9, "resultado_id": "r-1", "hipotese_id": "h-1", "valor": 0.9}
        return ObjectiveState(tipo, atingido, None, False, saturacao, details, memory)

    return patch("src.orchestration.objective_tracking.evaluate", side_effect=fake)


def events_patch():
    events: list[tuple[str, dict]] = []
    return events, patch.object(
        ExplorationSession, "_emit", autospec=True, side_effect=lambda self, k, p: events.append((k, p))
    )


@pytest.mark.asyncio
async def test_laco_aciona_o_curator_na_estagnacao_e_nao_fecha_por_ela(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.EXPLORATION_STALL_CYCLES", 2)
    monkeypatch.setattr("src.config.EXPLORATION_MAX_INTERVENTIONS", 9)
    plans = [plan([task(f"t{i}")], [hyp(f"h{i}")]) for i in range(1, 5)]
    h = LoopHarness(tmp_path, plans=plans)
    h.orch.curator_suggest = AsyncMock(return_value=[])
    events, emit = events_patch()
    h.extra_patches += [
        stuck_state(), emit, patch("src.gate.persistent_gate.session_gate", return_value=FakeGate()),
        patch.object(AutonomousLoop, "_usage_fraction", return_value=0.0),
    ]
    await h.run()
    assert h.stop_reason != "saturacao"
    calls = [c for c in h.orch.curator_suggest.await_args_list if len(c.args) > 1 and c.args[1] is not None]
    assert calls and calls[0].args[1].intervencao == 1 and calls[0].args[1].melhor_valor == 0.9
    first = next(p for k, p in events if k == "estagnacao_intervencao")
    assert first["intervencao"] == 1 and first["paciencia"] == 2 and first["ciclos_sem_avanco"] == 2


@pytest.mark.asyncio
async def test_laco_continuar_alem_do_alvo_nao_interveem(tmp_path, monkeypatch):
    """Scenario: Continuar além do alvo — sem ``estagnacao_intervencao`` e com um único ``objetivo_atingido``."""
    monkeypatch.setattr("src.config.EXPLORATION_STALL_CYCLES", 1)
    plans = [plan([task(f"t{i}")], [hyp(f"h{i}")]) for i in range(1, 5)]
    h = LoopHarness(tmp_path, plans=plans)
    crit = dict(h.w.problem.properties["criterio_sucesso"], ao_atingir_objetivo="continuar")
    h.w.store.update_node(h.w.problem.id, {"criterio_sucesso": crit}, actor=PESQUISADOR)
    h.orch.curator_suggest = AsyncMock(return_value=[])
    events, emit = events_patch()
    h.extra_patches += [
        stuck_state(atingido=True), emit, patch("src.gate.persistent_gate.session_gate", return_value=FakeGate()),
        patch.object(AutonomousLoop, "_usage_fraction", return_value=0.0),
    ]
    await h.run()
    kinds = [k for k, _ in events]
    assert "estagnacao_intervencao" not in kinds and kinds.count("objetivo_atingido") == 1
    assert h.stop_reason == "sem_caminhos_promissores"


@pytest.mark.asyncio
async def test_laco_fecha_com_saturacao_no_auto(tmp_path, monkeypatch):
    """Scenario: Saturação no auto — fecha com ``motivo_parada = saturacao`` e checkpoint."""
    monkeypatch.setattr("src.config.EXPLORATION_STALL_CYCLES", 1)
    monkeypatch.setattr("src.config.EXPLORATION_MAX_INTERVENTIONS", 1)
    plans = [plan([task(f"t{i}")], [hyp(f"h{i}")]) for i in range(1, 8)]
    h = LoopHarness(tmp_path, plans=plans)
    h.orch.curator_suggest = AsyncMock(return_value=[])
    h.extra_patches += [
        stuck_state(saturacao="confirmada"), patch("src.gate.persistent_gate.session_gate", return_value=FakeGate()),
    ]
    await h.run()
    assert h.stop_reason == "saturacao"
    assert h.checkpoint().exploracao_estado["memoria"]["interventions"] == 1


@pytest.mark.asyncio
async def test_laco_aplica_a_resposta_parar(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.EXPLORATION_STALL_CYCLES", 50)
    h = LoopHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])])
    gate = FakeGate()
    request = gate.request(
        "decidir_continuidade", "estagnacao:1", "p", ("continuar", "orientar", "parar"), motivo="estagnacao",
        session_id=h.w.sid,
    )
    gate.respond(request.id, resposta={"acao": "parar"})
    h.extra_patches += [stuck_state(), patch("src.gate.persistent_gate.session_gate", return_value=gate)]
    await h.run()
    assert h.stop_reason == "encerrada_pesquisador" and gate.get(request.id).consumido


def test_estado_do_checkpoint_invalido_e_descartado_com_evento():
    """Scenario: Estado inválido na retomada — ``intervencoes = -4`` começa do zero e registra o evento."""
    events: list[tuple[str, dict]] = []
    tracker = ObjectiveTracker(
        lambda: None, "p", "s", mode="auto", emit=lambda k, p: events.append((k, p)), confirmer=lambda a: None,
        requester=lambda *a: None,
    )
    tracker.restore({"memoria": {"interventions": -4, "cycles_without_advance": 3}})
    assert tracker.memory.interventions == 0 and tracker.memory.cycles_without_advance == 0
    assert events == [("exploracao_estado_descartado", {"campo": "interventions"})]


def test_estado_do_checkpoint_valido_preserva_intervencoes():
    """Scenario: Retomada preserva intervenções — 2 intervenções e 3 ciclos sem avanço."""
    tracker = ObjectiveTracker(
        lambda: None, "p", "s", mode="auto", emit=lambda *a: None, confirmer=lambda a: None,
        requester=lambda *a: None,
    )
    tracker.memory = ObjectiveMemory(interventions=2, cycles_without_advance=3)
    state = tracker.snapshot()
    other = ObjectiveTracker(
        lambda: None, "p", "s", mode="auto", emit=lambda *a: None, confirmer=lambda a: None,
        requester=lambda *a: None,
    )
    other.restore(state)
    assert other.memory.interventions == 2 and other.memory.cycles_without_advance == 3


@pytest.mark.parametrize("bad", [
    {"memoria": {"cycles_without_advance": True}}, {"memoria": {"best_value": float("nan")}},
    {"memoria": {"novelty": ["a"]}}, {"memoria": "x"}, {"memoria": {}, "relatados": [1]},
    {"memoria": {"interventions": 10**9}},
])
def test_validacao_de_tipos_e_faixas(bad):
    from src.orchestration.objective_tracking import invalid_state_field

    assert invalid_state_field(bad) is not None
    assert invalid_state_field({"memoria": {"interventions": 2, "best_value": 0.5}, "relatados": ["x"]}) is None
