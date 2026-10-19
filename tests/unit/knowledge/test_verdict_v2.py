"""Modelo v2 da equação de confiança (v18.8-verdict-calibration; ADR 025, ADR 015 §9 revisado)."""

from __future__ import annotations

import importlib
import math
import random

import pytest

from scripts.verdict_lab import variants as lab
from scripts.verdict_lab.scenarios import ABSOLUTO, _Builder, catalog
from scripts.verdict_lab.simulation import SimPoint, generate_sequence
from src.knowledge.verdict import Criterion, VerdictParams, compute_verdict

pytestmark = pytest.mark.unit

V2 = VerdictParams()
ADR015 = VerdictParams(modelo="adr015")


def vd(builder: _Builder, criterion: Criterion = ABSOLUTO, params: VerdictParams = V2):
    return compute_verdict(list(builder.done()), criterion, params)


def test_modelo_padrao_e_v2_e_adr015_restaura_a_equacao_anterior() -> None:
    assert VerdictParams().modelo == "v2"
    attempts = list(_Builder().variations([0.96, 0.97]).done())
    antigo = compute_verdict(attempts, ABSOLUTO, ADR015)
    assert antigo.veredito == pytest.approx(0.033, abs=0.001)  # d = 0,2 na segunda variação, como no ADR 015


def test_modelo_invalido_e_erro() -> None:
    with pytest.raises(ValueError, match="modelo"):
        compute_verdict([], ABSOLUTO, VerdictParams(modelo="outro"))


def test_config_valida_o_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.config as config

    monkeypatch.setenv("VERDICT_MODEL", "x")
    with pytest.raises(ValueError, match="VERDICT_MODEL"):
        importlib.reload(config)
    monkeypatch.delenv("VERDICT_MODEL")
    importlib.reload(config)
    assert config.VERDICT_MODEL == "v2" and config.KNOWLEDGE_SHORTCUT_MIN_VERDICT == 0.3


def test_equivalencia_com_o_laboratorio_no_catalogo() -> None:
    completa2 = next(v for v in lab.load_variants() if v.nome == "completa2")
    for s in catalog():
        ref = lab.lab_verdict(list(s.attempts), s.criterion, completa2)
        got = compute_verdict(list(s.attempts), s.criterion, V2)
        assert abs(got.veredito - ref.veredito) <= 1e-12, s.nome
        assert abs(got.alpha - ref.alpha) <= 1e-12 and abs(got.beta - ref.beta) <= 1e-12 and abs(got.f - ref.f) <= 1e-12
        assert [round(d.w, 12) for d in got.detalhes] == [round(d.w, 12) for d in ref.detalhes], s.nome


def test_equivalencia_com_o_laboratorio_na_simulacao() -> None:
    completa2 = next(v for v in lab.load_variants() if v.nome == "completa2")
    point = SimPoint(sigma=0.01, tau=0.01, efeito=0.01, p_variacao=0.5, p_falha=0.3, nos=2)
    for i in range(30):
        for tipo in ("verdadeira", "falsa", "sem_efeito"):
            seq = generate_sequence(random.Random(f"{i}:{tipo}"), tipo, point, 12)
            ref = lab.lab_verdict(seq, ABSOLUTO, completa2).veredito
            assert abs(compute_verdict(seq, ABSOLUTO, V2).veredito - ref) <= 1e-12


def test_variacao_pesa_mais_que_replica_em_outro_no() -> None:
    b = _Builder()
    b.result(0.96, "A", node="n1", session="s1")
    b.result(0.97, "B", node="n1", session="s1")
    b.result(0.96, "A", node="n2", session="s2")
    b.result(0.96, "A", node="n2", session="s2")
    r = vd(b)
    assert [d.d for d in r.detalhes] == [1.0, 1.0, 0.5, 0.2]
    assert [d.tipo for d in r.detalhes] == ["variacao", "variacao", "replica_no", "semente"]


def test_a_mesma_configuracao_em_tres_nos_nao_conclui() -> None:
    b = _Builder()
    for k in range(3):
        b.result(0.96, "A", node=f"n{k + 1}", session=f"s{k + 1}")
    assert vd(b).veredito == pytest.approx(0.111, abs=0.001)


def test_qualquer_melhora_conta() -> None:
    r = vd(_Builder().result(0.96, "A").result(0.9601, "B"))
    assert [d.d for d in r.detalhes] == [1.0, 1.0] and [d.util for d in r.detalhes] == [True, True]


def test_volume_sem_evolucao_nao_soma() -> None:
    r = vd(_Builder().variations([0.951] * 20))
    assert [d.d for d in r.detalhes] == [1.0] + [0.0] * 19
    assert r.veredito == pytest.approx(0.040, abs=0.001)


def test_cinco_melhoras_concluem_e_tres_nao() -> None:
    cinco = vd(_Builder().variations([0.955, 0.959, 0.963, 0.967, 0.971]))
    tres = vd(_Builder().variations([0.955, 0.959, 0.963]))
    assert cinco.veredito == pytest.approx(0.405, abs=0.005) and cinco.veredito >= 0.3
    assert tres.veredito == pytest.approx(0.204, abs=0.005) and tres.veredito < 0.3


def test_penalidade_acumulada_preserva_pesos_anteriores() -> None:
    base = vd(_Builder().variations([0.96, 0.97, 0.98]))
    mais = vd(_Builder().variations([0.96, 0.97, 0.98]).variations([0.955], start=4))
    assert [d.w for d in mais.detalhes[:3]] == [d.w for d in base.detalhes]


def test_falhas_nao_penalizam() -> None:
    r = vd(_Builder().failure("ambigua", "f1").failure("ambigua", "f2").result(0.96, "c3"))
    assert [d.b for d in r.detalhes if d.classificacao == "positiva"] == [1.0]


def test_alvo_exigido_com_baseline_e_retorno_ao_modelo_anterior() -> None:
    crit = Criterion(sentido="maior_melhor", delta_min=0.01, alvo=0.95)
    b = _Builder().result(0.80, "A", baseline=0.333)
    assert vd(b, crit).detalhes[0].classificacao == "negativa"
    assert vd(b, crit, ADR015).detalhes[0].classificacao == "positiva"


def test_piso_da_folga() -> None:
    assert vd(_Builder().result(0.951, "A")).detalhes[0].m == 0.5
    assert vd(_Builder().result(0.98, "A")).detalhes[0].m == 1.0


def test_replica_contraria_pesa_cheio() -> None:
    b = _Builder().variations([0.955, 0.959, 0.963, 0.967, 0.971])
    for k in range(3):
        b.result(0.93, "c5", node=f"n{k + 2}", session=f"s{k + 2}")
    r = vd(b)
    assert r.veredito < 0.3 and [d.d for d in r.detalhes[-3:]] == [1.0, 1.0, 1.0]


def test_limites_e_ordem_de_entrada() -> None:
    for s in catalog():
        r = compute_verdict(list(s.attempts), s.criterion, V2)
        assert -1 <= r.veredito <= 1 and 0 <= r.certeza < 1
        rev = compute_verdict(list(reversed(s.attempts)), s.criterion, V2)
        assert math.isclose(r.veredito, rev.veredito, abs_tol=1e-12)


def test_falsa_validacao_da_simulacao_reduzida_dentro_do_teto() -> None:
    from scripts.verdict_lab.simulation import grid_points, run_simulation

    completa2 = next(v for v in lab.load_variants() if v.nome == "completa2")
    grid = {
        "sigma": [0.005, 0.01, 0.02],
        "tau": [0.0],
        "efeito": [0.01],
        "p_variacao": [1.0],
        "p_falha": [0.0],
        "nos": [1],
    }
    rows = run_simulation(
        grid_points(grid),
        [(completa2, None)],
        semente=11,
        repeticoes=40,
        max_tentativas=20,
        limiares=[0.3],
        orcamentos=[20],
    )
    fv = {
        t: [r["validadas"] for r in rows if r["tabela"] == "curva" and r["tipo"] == t and r["limiar"] == 0.3]
        for t in ("falsa", "sem_efeito")
    }
    assert max(sum(v) / len(v) for v in fv.values()) <= 0.02
