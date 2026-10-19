"""Variantes da fórmula do veredito (v18.8-verdict-lab, requisitos de evidence-scoring)."""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from scripts.verdict_lab import variants as V
from scripts.verdict_lab.scenarios import ABSOLUTO, ERRO, _Builder, catalog
from scripts.verdict_lab.simulation import SimPoint, generate_sequence
from src.knowledge.verdict import Criterion, VerdictParams, compute_verdict

pytestmark = pytest.mark.unit

EPS = 1e-12


def variant(**estrutura) -> V.Variant:
    return V.Variant(nome="t", params=VerdictParams(), estrutura=V.Structure(**estrutura))


def test_equivalencia_da_reimplementacao_no_catalogo() -> None:
    atual = V.Variant(nome="atual", params=VerdictParams())
    for s in catalog():
        ref = compute_verdict(list(s.attempts), s.criterion, VerdictParams())
        got = V.lab_verdict(list(s.attempts), s.criterion, atual, reimplementar=True)
        assert abs(got.veredito - ref.veredito) <= EPS, s.nome
        assert abs(got.alpha - ref.alpha) <= EPS and abs(got.beta - ref.beta) <= EPS and abs(got.f - ref.f) <= EPS
        assert [(d.classificacao, round(d.w, 12)) for d in got.detalhes] == [
            (d.classificacao, round(d.w, 12)) for d in ref.detalhes
        ], s.nome


def test_equivalencia_em_amostra_da_simulacao() -> None:
    import random

    atual = V.Variant(nome="atual", params=VerdictParams())
    point = SimPoint(sigma=0.01, tau=0.01, efeito=0.01, p_variacao=0.5, p_falha=0.3, nos=2)
    for i in range(30):
        for tipo in ("verdadeira", "falsa", "sem_efeito"):
            seq = generate_sequence(random.Random(f"{i}:{tipo}"), tipo, point, 12)
            ref = compute_verdict(seq, ABSOLUTO, VerdictParams()).veredito
            assert abs(V.lab_verdict(seq, ABSOLUTO, atual, reimplementar=True).veredito - ref) <= EPS


def test_variavel_de_ambiente_vale_no_laboratorio(monkeypatch: pytest.MonkeyPatch) -> None:
    from src import config

    monkeypatch.setattr(config, "VERDICT_GAMMA", 0.25)
    params, origem = V.base_params()
    assert params.gamma == 0.25 and origem == "config"
    assert V.current_variant().manifest()["parametros"]["gamma"] == 0.25


def test_campo_desconhecido_e_erro_com_o_nome() -> None:
    doc = {"versao": 1, "variantes": [{"nome": "x", "parametros": {"gama": 0.3}}]}
    with pytest.raises(V.VariantError, match="gama"):
        V.parse_variants(doc)
    with pytest.raises(V.VariantError, match="independencia"):
        V.parse_variants({"versao": 1, "variantes": [{"nome": "x", "estrutura": {"independencia": "outra"}}]})
    with pytest.raises(V.VariantError, match="repetido"):
        V.parse_variants({"versao": 1, "variantes": [{"nome": "x"}, {"nome": "x"}]})


def test_variantes_padrao_carregam_e_incluem_atual() -> None:
    names = [v.nome for v in V.load_variants()]
    assert names[0] == "atual" and "completa" in names and len(set(names)) == len(names)


def test_falhas_fora_de_nconfig() -> None:
    attempts = _Builder().failure("ambigua", "f1").failure("ambigua", "f2").result(0.96, "c3").done()
    sem = V.lab_verdict(list(attempts), ABSOLUTO, variant(n_config_conta_falhas=False))
    com = V.lab_verdict(list(attempts), ABSOLUTO, variant())
    assert [d.b for d in sem.detalhes if d.classificacao == "positiva"] == [1.0]
    expected = 1 / (1 + 0.5 * math.log(3))
    assert [d.b for d in com.detalhes if d.classificacao == "positiva"] == [pytest.approx(expected)]


def test_independencia_por_tipo() -> None:
    b = _Builder()
    b.result(0.96, "A", node="n1", session="s1")
    b.result(0.97, "B", node="n1", session="s1")
    b.result(0.96, "A", node="n2", session="s2")
    b.result(0.96, "A", node="n2", session="s2")
    r = V.lab_verdict(
        list(b.done()), ABSOLUTO, variant(independencia="por_tipo", d_variacao=1.0, d_replica_no=0.5, d_semente=0.2)
    )
    ds = [d.d for d in r.detalhes]
    assert ds == [1.0, 1.0, 0.5, 0.2]


def test_variacao_sem_ganho_e_volume() -> None:
    b = _Builder().result(0.97, "A").result(0.96, "B")
    est = dict(independencia="por_tipo", variacao_util="melhora_o_melhor", variacao_util_epsilon=0.0)
    r = V.lab_verdict(list(b.done()), ABSOLUTO, variant(**est))
    assert [d.d for d in r.detalhes] == [1.0, 0.2]
    b2 = _Builder().result(0.96, "A").result(0.9601, "B")
    assert [d.d for d in V.lab_verdict(list(b2.done()), ABSOLUTO, variant(**est)).detalhes] == [1.0, 1.0]


def test_alvo_exigido_com_baseline() -> None:
    attempts = list(_Builder().result(0.80, "A", baseline=0.333).done())
    crit = Criterion(sentido="maior_melhor", delta_min=0.01, alvo=0.95)
    atual = V.lab_verdict(attempts, crit, variant())
    exige = V.lab_verdict(attempts, crit, variant(criterio_com_alvo="exige_alvo"))
    assert atual.detalhes[0].classificacao == "positiva"
    assert exige.detalhes[0].classificacao == "negativa" and exige.veredito < 0


def test_magnitude_pela_folga_sem_baseline() -> None:
    est = variant(m_sem_baseline="folga")
    pos = V.lab_verdict(list(_Builder().result(0.96, "A").done()), ABSOLUTO, est).detalhes[0]
    assert pos.classificacao == "positiva" and pos.m == pytest.approx(0.5)
    assert V.lab_verdict(list(_Builder().result(0.98, "A").done()), ABSOLUTO, est).detalhes[0].m == 1.0
    neg = V.lab_verdict(list(_Builder().result(0.94, "A").done()), ABSOLUTO, est).detalhes[0]
    assert neg.classificacao == "negativa" and neg.m == pytest.approx(1.0)


def test_sentido_menor_melhor() -> None:
    r = V.lab_verdict(list(_Builder().result(0.09, "A").done()), ERRO, variant(independencia="por_tipo"))
    assert r.detalhes[0].classificacao == "positiva"


def test_manifesto_da_variante_traz_parametros_efetivos() -> None:
    m = V.current_variant().manifest()
    assert m["parametros"]["thresholds"] == [0.1, 0.3, 0.5] and "estrutura" in m
    json.dumps(m)
    assert dataclasses.asdict(V.Structure())["independencia"] == "atual"


COMPLETA2 = dict(
    independencia="por_tipo",
    variacao_util="melhora_o_melhor",
    b_por="variacao_sem_ganho_acumulada",
    m_sem_baseline="folga",
    m_folga_piso=0.5,
    criterio_com_alvo="exige_alvo",
    d_replica_contraria=1.0,
    d_variacao_sem_ganho=0.0,
)


def test_penalidade_acumulada_nao_reduz_o_peso_das_anteriores() -> None:
    est = variant(**COMPLETA2)
    base = list(_Builder().variations([0.96, 0.97, 0.98]).done())
    before = V.lab_verdict(base, ABSOLUTO, est)
    extra = list(_Builder().variations([0.96, 0.97, 0.98]).variations([0.955], start=4).done())
    after = V.lab_verdict(extra, ABSOLUTO, est)
    assert [d.w for d in after.detalhes[:3]] == [d.w for d in before.detalhes]
    old = variant(**{**COMPLETA2, "b_por": "variacao_sem_ganho"})
    assert V.lab_verdict(extra, ABSOLUTO, old).detalhes[0].w < V.lab_verdict(base, ABSOLUTO, old).detalhes[0].w


def test_piso_da_folga_mantem_o_peso_de_melhora_pequena() -> None:
    attempts = list(_Builder().result(0.951, "A").done())
    sem_piso = V.lab_verdict(attempts, ABSOLUTO, variant(m_sem_baseline="folga")).detalhes[0].m
    com_piso = V.lab_verdict(attempts, ABSOLUTO, variant(m_sem_baseline="folga", m_folga_piso=0.5)).detalhes[0].m
    assert sem_piso == pytest.approx(0.05) and com_piso == 0.5


def test_replica_contraria_pesa_cheio() -> None:
    b = _Builder().variations([0.96, 0.97, 0.98]).result(0.93, "c3", node="n2", session="s2")
    padrao = V.lab_verdict(list(b.done()), ABSOLUTO, variant(independencia="por_tipo"))
    cheio = V.lab_verdict(list(b.done()), ABSOLUTO, variant(independencia="por_tipo", d_replica_contraria=1.0))
    assert padrao.detalhes[-1].d == 0.5 and cheio.detalhes[-1].d == 1.0 and cheio.veredito < padrao.veredito


def test_completa2_e_monotonica_no_catalogo() -> None:
    from scripts.verdict_lab.properties import measure_properties

    rows = measure_properties([variant(**COMPLETA2)], catalog())
    assert {r["propriedade"]: r["violacoes"] for r in rows}["monotonicidade"] == 0


def test_completa2_conclui_o_que_o_pesquisador_definiu() -> None:
    from scripts.verdict_lab.scenarios import by_name

    est = V.Variant(nome="c2", params=VerdictParams(), estrutura=V.Structure(**COMPLETA2))
    sc = by_name()
    for nome in ("A8-ruido", "A16-ruido", "V20", "Q-E5-R3-neg", "E2", "R5"):
        s = sc[nome]
        assert abs(V.lab_verdict(list(s.attempts), s.criterion, est).veredito) < 0.3, nome
    for nome in ("E5", "C5-acima-do-alvo"):
        s = sc[nome]
        assert V.lab_verdict(list(s.attempts), s.criterion, est).veredito >= 0.3, nome
    assert V.lab_verdict(list(sc["C3-abaixo-do-alvo"].attempts), sc["C3-abaixo-do-alvo"].criterion, est).veredito < -0.3


def test_positiva_sem_ganho_nao_soma_volume() -> None:
    b = _Builder().variations([0.96] + [0.96] * 19)
    r = V.lab_verdict(list(b.done()), ABSOLUTO, variant(**COMPLETA2))
    assert [d.d for d in r.detalhes] == [1.0] + [0.0] * 19
