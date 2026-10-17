"""Critérios por tipo do objetivo (v18.7-exploration-limits, tarefa 5.3; ``specs/hypothesis-loop``). Sem LLM."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.knowledge import objective as obj
from src.knowledge.objective import (
    Competitor,
    CycleView,
    DiscriminatingTask,
    EligibleResult,
    GraphObjectiveReader,
    ObjectiveError,
    ObjectiveMemory,
    PredictionCheck,
    evaluate,
    normalize_predictions,
)
from src.knowledge.service import KnowledgeService
from tests.support import exploration_graph as eg
from tests.support.hypothesis_world import HypothesisWorld

pytestmark = pytest.mark.unit

LIMIAR = {"tipo": "limiar", "metrica": "acuracia", "sentido": "maior_melhor", "alvo": 0.95, "delta_min": 0.01}


@dataclass
class FakeReader:
    results: list[EligibleResult] = field(default_factory=list)
    rivals: list[Competitor] = field(default_factory=list)
    checks: list[PredictionCheck] = field(default_factory=list)

    def sentido(self) -> str | None:
        return "maior_melhor"

    def eligible_results(self):
        return self.results

    def competitors(self):
        return self.rivals

    def prediction_checks(self):
        return self.checks


def res(valor, hip="h1", exp=None, baseline=0.33):
    return EligibleResult(f"r-{hip}-{valor}", exp or f"e-{hip}-{valor}", hip, valor, baseline)


CYCLE = CycleView(1)


# --- limiar ----------------------------------------------------------------------------------------------------------


def test_tipo_efetivo_sem_tipo_e_limiar():
    """Scenario: Problema antigo sem tipo."""
    assert obj.effective_type({"metrica": "acuracia", "alvo": 0.95, "delta_min": 0.01}) == "limiar"
    assert obj.effective_type({"tipo": "cobertura"}) == "cobertura"
    assert obj.effective_type({}) is None


def test_fronteira_recusada():
    with pytest.raises(ObjectiveError, match="V19"):
        evaluate(FakeReader(), {"tipo": "fronteira"}, ObjectiveMemory(), CYCLE)


def test_resultado_validado_atinge_o_alvo():
    """Scenario: Resultado validado atinge o alvo com veredito baixo (o veredito nem é lido)."""
    state = evaluate(FakeReader(results=[res(1.0)]), LIMIAR, ObjectiveMemory(), CYCLE)
    assert state.atingido and state.detalhes["valor"] == 1.0


def test_alvo_atingido_sem_o_ganho_minimo():
    """Scenario: Alvo atingido sem o ganho mínimo."""
    criterion = {**LIMIAR, "alvo": 0.90, "delta_min": 0.05}
    assert not evaluate(FakeReader(results=[res(0.92, baseline=0.89)]), criterion, ObjectiveMemory(), CYCLE).atingido


def test_so_delta_min_sem_alvo():
    criterion = {"tipo": "limiar", "metrica": "m", "sentido": "maior_melhor", "delta_min": 0.05}
    assert evaluate(FakeReader(results=[res(0.80, baseline=0.70)]), criterion, ObjectiveMemory(), CYCLE).atingido
    assert not evaluate(FakeReader(results=[res(0.72, baseline=0.70)]), criterion, ObjectiveMemory(), CYCLE).atingido


def test_menor_melhor():
    criterion = {"tipo": "limiar", "metrica": "erro", "sentido": "menor_melhor", "alvo": 0.1}
    assert evaluate(FakeReader(results=[res(0.08, baseline=None)]), criterion, ObjectiveMemory(), CYCLE).atingido
    assert not evaluate(FakeReader(results=[res(0.2, baseline=None)]), criterion, ObjectiveMemory(), CYCLE).atingido


def test_avanco_sem_replicas_e_qualquer_melhora():
    reader = FakeReader(results=[res(0.5)])
    first = evaluate(reader, LIMIAR, ObjectiveMemory(), CYCLE)
    assert first.avanco and first.memory.best_value == 0.5
    reader.results.append(res(0.51, hip="h2", exp="e2"))
    second = evaluate(reader, LIMIAR, first.memory, CYCLE)
    assert second.avanco and second.detalhes["avanco_sem_incerteza"] is True


def test_melhora_dentro_do_erro_nao_e_avanco(monkeypatch):
    monkeypatch.setattr("src.config.SATURATION_SE_MULTIPLIER", 1.0)
    reader = FakeReader(results=[res(0.80, exp="a"), res(0.70, exp="b"), res(0.90, exp="c")])
    memory = ObjectiveMemory(best_value=0.89)  # melhora de 0.01, EP = 0.1/√3 ≈ 0.058
    state = evaluate(reader, LIMIAR, memory, CYCLE)
    assert not state.avanco and state.memory.cycles_without_advance == 1 and state.memory.best_value == 0.89
    assert state.detalhes["replicas"] == 3 and state.saturacao == "confirmada"


def test_saturacao_nao_avaliavel_com_poucas_replicas():
    state = evaluate(FakeReader(results=[res(0.5)]), LIMIAR, ObjectiveMemory(best_value=0.5), CYCLE)
    assert not state.avanco and state.saturacao == "nao_avaliavel"


def test_memoria_vai_e_volta_do_checkpoint():
    memory = ObjectiveMemory(0.7, 2, 1, (1, 0), frozenset({"e1"}), frozenset({"h2"}))
    assert ObjectiveMemory.from_dict(memory.to_dict()) == memory
    assert ObjectiveMemory.from_dict("lixo") == ObjectiveMemory()


# --- discriminacao ---------------------------------------------------------------------------------------------------

RIVALS = [Competitor("h1", "A"), Competitor("h2", "B"), Competitor("h3", "C")]
DISC = {"tipo": "discriminacao"}


def check(exp, hip, valor, validado=True):
    return PredictionCheck(exp, hip, valor, validado)


def test_uma_compativel():
    """Scenario: Uma compatível."""
    reader = FakeReader(rivals=RIVALS, checks=[check("e1", "h1", "confirma"), check("e1", "h2", "contraria"),
                                               check("e1", "h3", "contraria")])
    state = evaluate(reader, DISC, ObjectiveMemory(), CYCLE)
    assert state.atingido and state.desfecho == "uma_compativel" and state.detalhes["hipotese_id"] == "h1"
    assert state.avanco


def test_todas_contrariadas():
    """Scenario: Todas contrariadas."""
    reader = FakeReader(rivals=RIVALS[:2], checks=[check("e1", "h1", "contraria"), check("e1", "h2", "contraria")])
    state = evaluate(reader, DISC, ObjectiveMemory(), CYCLE)
    assert not state.atingido and state.desfecho == "todas_contrariadas"


def test_conferencia_nao_validada_nao_conta():
    reader = FakeReader(rivals=RIVALS[:2], checks=[check("e1", "h1", "confirma", False),
                                                    check("e1", "h2", "contraria", False)])
    state = evaluate(reader, DISC, ObjectiveMemory(), CYCLE)
    assert not state.atingido and state.desfecho is None and not state.avanco


def test_varias_compativeis_sem_experimento_que_distinga():
    """Scenario: Várias compatíveis."""
    reader = FakeReader(rivals=RIVALS[:2], checks=[check("e1", "h1", "confirma"), check("e1", "h2", "confirma")])
    state = evaluate(reader, DISC, ObjectiveMemory(), CYCLE)
    assert state.desfecho == "varias_compativeis" and state.saturacao == "confirmada" and not state.atingido


def test_subtarefa_que_discrimina_impede_a_saturacao():
    reader = FakeReader(rivals=RIVALS[:2], checks=[check("e1", "h1", "confirma"), check("e1", "h2", "confirma")])
    cycle = CycleView(2, discriminating=(DiscriminatingTask("distingue", ("h1", "h2")),))
    state = evaluate(reader, DISC, ObjectiveMemory(), cycle)
    assert state.desfecho is None and state.saturacao == "nao_confirmada"


def test_experimento_fisico():
    """Scenario: Experimento físico."""
    reader = FakeReader(rivals=RIVALS[:2], checks=[check("e1", "h1", "confirma"), check("e1", "h2", "confirma")])
    cycle = CycleView(2, discriminating=(DiscriminatingTask("bancada", ("h1", "h2"), fisico=True),))
    state = evaluate(reader, DISC, ObjectiveMemory(), cycle)
    assert state.desfecho == "aguarda_experimento_fisico" and state.detalhes["subtarefa"] == "bancada"
    assert state.saturacao != "confirmada"


def test_avanco_ao_contrariar_uma_nova_concorrente():
    memory = ObjectiveMemory(seen_experiments=frozenset({"e1"}), contradicted=frozenset({"h2"}))
    reader = FakeReader(rivals=RIVALS, checks=[check("e1", "h2", "contraria"), check("e2", "h3", "contraria")])
    assert evaluate(reader, DISC, memory, CYCLE).avanco
    again = evaluate(reader, DISC, evaluate(reader, DISC, memory, CYCLE).memory, CYCLE)
    assert not again.avanco  # nada novo no ciclo seguinte


def test_concorrente_sem_predicao_e_inconclusiva():
    """Scenario: Concorrente sem predição (mesmo que o parecer diga contraria)."""
    rivals = [Competitor("h1", "A"), Competitor("h2", None)]
    items = [
        {"hipotese_id": "h1", "conferencia": "confirma", "justificativa": "j"},
        {"hipotese_id": "h2", "conferencia": "contraria", "justificativa": "j"},
        {"hipotese_id": "fora", "conferencia": "confirma"},
    ]
    assert normalize_predictions(rivals, ("h1", "h2"), items) == {"h1": "confirma", "h2": "inconclusiva"}
    assert normalize_predictions(rivals, ("h1",), items) == {"h1": "confirma"}  # fora de discrimina é descartado
    assert normalize_predictions(rivals, ("h1",), [{"hipotese_id": "h1", "conferencia": "talvez"}]) == {
        "h1": "inconclusiva"
    }
    assert normalize_predictions(rivals, ("h1",), None) == {"h1": "inconclusiva"}


# --- cobertura -------------------------------------------------------------------------------------------------------


def run_coverage(counts):
    memory = ObjectiveMemory()
    state = None
    for i, n in enumerate(counts, 1):
        state = evaluate(FakeReader(), {"tipo": "cobertura"}, memory, CycleView(i, new_hypotheses=n))
        memory = state.memory
    return state


def test_aviso_de_novidade_baixa():
    """Scenario: Aviso de novidade baixa (1, 0, 0, 0, 0 com janela 5 e taxa mínima 0,2)."""
    state = run_coverage([1, 0, 0, 0, 0])
    assert state.saturacao == "so_aviso" and state.detalhes["taxa"] == 0.2 and not state.atingido


def test_novidade_suficiente_nao_avisa():
    assert run_coverage([1, 1, 0, 0, 0]).saturacao == "nao_confirmada"
    assert run_coverage([0, 0]).saturacao == "nao_confirmada"  # janela incompleta


def test_cobertura_so_avanca_com_hipotese_nova():
    assert run_coverage([2]).avanco and not run_coverage([0]).avanco


# --- leitor sobre o grafo --------------------------------------------------------------------------------------------


@pytest.fixture
def world():
    w = HypothesisWorld()
    eg.problema(w, "limiar")
    return w


def reader_of(w):
    return GraphObjectiveReader(w.store, KnowledgeService(w.store), w.pid, w.problem.id)


def test_leitor_so_conta_validado_nao_referencia_e_hipotese_ativa(world):
    """Scenario: Resultado não validado ou de referência."""
    h = eg.hipotese(world)
    eg.resultado(world, eg.experimento(world, testa=h), 0.99, validado=False)
    eg.resultado(world, eg.experimento(world, testa=h, papel="referencia"), 0.99)
    assert reader_of(world).eligible_results() == []
    state = evaluate(reader_of(world), dict(world.problem.properties["criterio_sucesso"]), ObjectiveMemory(), CYCLE)
    assert not state.atingido
    good = eg.resultado(world, eg.experimento(world, testa=h), 0.99)
    assert [r.resultado_id for r in reader_of(world).eligible_results()] == [good]


def test_leitor_ignora_hipotese_abandonada_pelo_pesquisador(world):
    h = eg.hipotese(world, status="abandonada", abandonada_por="pesquisador")
    eg.resultado(world, eg.experimento(world, testa=h), 0.99)
    assert reader_of(world).eligible_results() == []
    h2 = eg.hipotese(world, status="abandonada", abandonada_por="agente")
    eg.resultado(world, eg.experimento(world, testa=h2), 0.99)
    assert len(reader_of(world).eligible_results()) == 1


def test_leitor_atinge_com_veredito_baixo(world):
    h = eg.hipotese(world)
    eg.resultado(world, eg.experimento(world, testa=h), 1.0)
    criterion = {**LIMIAR, "alvo": 0.95, "delta_min": 0.01}
    assert evaluate(reader_of(world), criterion, ObjectiveMemory(), CYCLE).atingido


def test_leitor_de_discriminacao(world):
    a = eg.hipotese(world, origem="pesquisador", concorrente=True, predicao="A")
    b = eg.hipotese(world, origem="pesquisador", concorrente=True, predicao="B")
    eg.hipotese(world)  # não concorrente
    exp = eg.experimento(world, testa=a, conferencia_predicoes={a: "confirma", b: "contraria"})
    world.store.create_edge(exp, "TESTA", b, {}, actor=eg.ORQ)
    eg.resultado(world, exp, 0.8)
    reader = reader_of(world)
    assert {c.hipotese_id for c in reader.competitors()} == {a, b}
    assert {(c.hipotese_id, c.conferencia, c.validado) for c in reader.prediction_checks()} == {
        (a, "confirma", True), (b, "contraria", True),
    }
    state = evaluate(reader, {"tipo": "discriminacao"}, ObjectiveMemory(), CYCLE)
    assert state.atingido and state.detalhes["hipotese_id"] == a


def test_leitor_conferencia_de_resultado_nao_validado_nao_vale(world):
    a = eg.hipotese(world, origem="pesquisador", concorrente=True, predicao="A")
    exp = eg.experimento(world, testa=a, conferencia_predicoes={a: "confirma"})
    eg.resultado(world, exp, 0.8, validado=False)
    assert [c.validado for c in reader_of(world).prediction_checks()] == [False]
