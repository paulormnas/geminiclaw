import pytest

from src.knowledge.structural_candidates import (
    Derivation,
    GraphView,
    ResultFact,
    default_score,
    descendants,
    generate,
)

pytestmark = pytest.mark.unit

T0 = "2026-10-01T00:00:00+00:00"
T1 = "2026-10-02T00:00:00+00:00"
T2 = "2026-10-03T00:00:00+00:00"


def _sim(table):
    return lambda a, b: table.get(frozenset((a, b)), 0.0)


def _view(facts, sim=0.8, **kwargs):
    return GraphView(facts=tuple(facts), similarity=_sim({frozenset(("P", "Q")): sim}), **kwargs)


def test_transferencia_de_problema_semelhante():
    fact = ResultFact("r1", "Q", "svm", T0, delta_base=0.2, atingiu_alvo=True, n_replicas=2)
    found = generate(_view([fact]), "P", t=T1, min_similarity=0.6)
    assert [(c.tipo, c.abordagem_id, c.origem_ids) for c in found] == [("transferencia", "svm", ("r1",))]
    assert found[0].atributos["semelhanca"] == 0.8
    assert found[0].atributos["replicas"] == 2.0


def test_semelhanca_abaixo_do_limiar_nao_gera_transferencia():
    fact = ResultFact("r1", "Q", "svm", T0, delta_base=0.2, atingiu_alvo=True)
    assert generate(_view([fact], sim=0.5), "P", t=T1, min_similarity=0.6) == []


def test_abordagem_ja_registrada_no_problema_nao_e_candidata():
    facts = [
        ResultFact("r1", "Q", "svm", T0, delta_base=0.2, atingiu_alvo=True),
        ResultFact("r2", "P", "svm", T0, delta_base=0.0),
    ]
    assert generate(_view(facts), "P", t=T1, min_similarity=0.6) == []


def test_sem_futuro():
    futuro = ResultFact("r1", "Q", "svm", T2, delta_base=0.2, atingiu_alvo=True)
    assert generate(_view([futuro]), "P", t=T1, min_similarity=0.6) == []
    assert len(generate(_view([futuro]), "P", t=T2, min_similarity=0.6)) == 1


def test_registro_sem_ganho_nao_e_origem():
    fact = ResultFact("r1", "Q", "svm", T0, delta_base=-0.1, atingiu_alvo=False)
    assert generate(_view([fact]), "P", t=T1, min_similarity=0.6) == []


def test_composicao_de_duas_variantes_do_mesmo_pai():
    facts = [
        ResultFact("r1", "P", "a", T0, delta_base=0.1, delta_pai=0.1),
        ResultFact("r2", "P", "b", T0, delta_base=0.2, delta_pai=0.05),
    ]
    derivations = (Derivation("a", "base", T0), Derivation("b", "base", T0))
    view = _view(facts, derivations=derivations)
    assert [c.abordagem_id for c in generate(view, "P", t=T1) if c.tipo == "composicao"] == ["a+b"]
    combinada = _view(facts, derivations=derivations, combinations=frozenset({frozenset(("a", "b"))}))
    assert [c for c in generate(combinada, "P", t=T1) if c.tipo == "composicao"] == []


def test_pouco_explorado_respeita_o_teto_de_descendentes():
    facts = [ResultFact("r1", "P", "a", T0, delta_base=0.3)]
    derivations = tuple(Derivation(f"d{i}", "a", T0) for i in range(3))
    assert generate(_view(facts, derivations=derivations), "P", t=T1, max_descendants=2) == []
    found = generate(_view(facts, derivations=derivations[:2]), "P", t=T1, max_descendants=2)
    assert [c.tipo for c in found] == ["pouco_explorado"]


def test_descendentes_sao_transitivos_e_toleram_ciclo():
    derivations = (Derivation("b", "a", T0), Derivation("c", "b", T0), Derivation("a", "c", T0))
    assert descendants(derivations, "a") == 2


def test_ordenacao_padrao_penaliza_descendentes():
    base = {"semelhanca": 0.8, "margem": 0.2, "replicas": 2.0, "descendentes": 0.0}
    assert default_score(base) > default_score({**base, "descendentes": 5.0})
    assert default_score({**base, "replicas": 9.0}) == default_score({**base, "replicas": 3.0})
