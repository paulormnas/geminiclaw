"""Falha de abordagem reproduzida no laboratório (v18.8-verdict-controlled-sessions, seção 4)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from scripts.verdict_lab import __main__ as cli
from scripts.verdict_lab import reports
from scripts.verdict_lab.scenarios import ABSOLUTO, FUNCIONA, INDECISO, NAO_FUNCIONA, catalog
from scripts.verdict_lab.simulation import (
    ASSINATURA_ABORDAGEM,
    TIPO_ABORDAGEM,
    SimPoint,
    generate_sequence,
    grid_points,
    run_abordagem,
)
from scripts.verdict_lab.variants import lab_verdict, load_variants, select_variants

pytestmark = pytest.mark.unit

NOMES = ["completa2", "completa2+q_abordagem_0_5", "completa2+q_abordagem_0_7", "completa2+q_abordagem_1_0"]
PONTO = dict(sigma=0.01, tau=0.01, efeito=0.02, p_variacao=0.5, p_falha=0.0, nos=1)


def cenario(nome: str):
    return next(s for s in catalog() if s.nome == nome)


def veredito(nome_cenario: str, variante: str) -> float:
    v = select_variants(load_variants(), [variante])[0]
    return lab_verdict(list(cenario(nome_cenario).attempts), ABSOLUTO, v).veredito


def test_variantes_de_q_no_arquivo() -> None:
    qs = {v.nome: v.params.approach_failure_q for v in select_variants(load_variants(), NOMES)}
    assert qs == {"completa2": 0.3, "completa2+q_abordagem_0_5": 0.5, "completa2+q_abordagem_0_7": 0.7,
                  "completa2+q_abordagem_1_0": 1.0}


@pytest.mark.parametrize(("variante", "esperado"), zip(NOMES, (-0.141, -0.250, -0.340, -0.444), strict=True))
def test_valores_de_n_abordagem_4_por_q(variante: str, esperado: float) -> None:
    assert veredito("N-abordagem-4", variante) == pytest.approx(esperado, abs=1e-3)


@pytest.mark.parametrize(("variante", "esperado"), zip(NOMES, (-0.096, -0.184, -0.262, -0.360), strict=True))
def test_valores_de_n_abordagem_3_por_q(variante: str, esperado: float) -> None:
    assert veredito("N-abordagem-3", variante) == pytest.approx(esperado, abs=1e-3)


def test_reproducao_minima_continua_indecisa_com_q_0_7() -> None:
    assert veredito("N-abordagem-2", "completa2+q_abordagem_0_7") == pytest.approx(-0.170, abs=1e-3)


def test_n_abordagem_ruido_funciona_com_q_atual_e_perde_forca_ao_subir_q() -> None:
    valores = [veredito("N-abordagem-ruido", n) for n in NOMES]
    assert valores[0] >= 0.3 and valores == sorted(valores, reverse=True) and all(v > 0 for v in valores)


def test_catalogo_declara_o_que_e_acerto() -> None:
    n3, ruido = cenario("N-abordagem-3"), cenario("N-abordagem-ruido")
    assert (n3.esperado, n3.aceitaveis) == (INDECISO, (NAO_FUNCIONA,))
    assert (ruido.esperado, ruido.aceitaveis) == (FUNCIONA, (INDECISO,))


def test_tipo_abordagem_falha_so_tem_falhas_com_a_mesma_assinatura() -> None:
    seq = generate_sequence(random.Random(1), TIPO_ABORDAGEM, SimPoint(**PONTO), 8)
    assert len(seq) == 8 and {a.outcome_kind for a in seq} == {"falha"}
    assert {a.failure_signature for a in seq} == {ASSINATURA_ABORDAGEM} and {a.failure_cause for a in seq} == {"abordagem"}
    assert len({a.seed for a in seq}) == 8


def test_developer_incapaz_gera_falhas_de_abordagem_nas_demais_hipoteses() -> None:
    sem = generate_sequence(random.Random(2), "verdadeira", SimPoint(**PONTO), 20)
    todas = generate_sequence(random.Random(2), "verdadeira", SimPoint(**PONTO, p_falha_abordagem=1.0), 20)
    assert all(a.outcome_kind == "resultado" for a in sem)
    assert all(a.failure_cause == "abordagem" for a in todas)


def test_ponto_sem_falha_de_abordagem_nao_muda_a_sequencia() -> None:
    a = generate_sequence(random.Random(3), "falsa", SimPoint(**PONTO), 12)
    b = generate_sequence(random.Random(3), "falsa", SimPoint(**PONTO, p_falha_abordagem=0.0), 12)
    assert a == b


def linhas(p_falha: float, repeticoes: int = 60) -> dict[tuple[str, str], dict]:
    pontos = grid_points({**{k: [v] for k, v in PONTO.items()}, "p_falha_abordagem": [p_falha]})
    variantes = select_variants(load_variants(), NOMES)
    rows = run_abordagem(pontos, variantes, semente=7, repeticoes=repeticoes, max_tentativas=10, limiar=0.3)
    return {(r["variante"], r["tipo"]): r for r in rows}


def test_q_maior_refuta_a_abordagem_plantada_com_menos_tentativas() -> None:
    r = linhas(0.0)
    medianas = [r[(n, TIPO_ABORDAGEM)]["tentativas_ate_refutar_mediana"] for n in NOMES]
    assert medianas == sorted(medianas, reverse=True) and medianas[0] > medianas[-1]
    assert all(r[(n, TIPO_ABORDAGEM)]["refutadas"] == 1.0 for n in NOMES)


def test_falsa_refutacao_cresce_com_q_e_falsa_validacao_nao_muda() -> None:
    r = linhas(0.5)
    falsa_refutacao = [r[(n, "verdadeira")]["refutadas"] for n in NOMES]
    assert falsa_refutacao == sorted(falsa_refutacao) and falsa_refutacao[-1] > falsa_refutacao[0]
    for tipo in ("falsa", "sem_efeito"):
        assert len({r[(n, tipo)]["validadas"] for n in NOMES}) == 1


def test_simulacao_da_abordagem_e_deterministica() -> None:
    assert linhas(0.2, 30) == linhas(0.2, 30)


def test_comando_abordagem_grava_saidas(tmp_path: Path) -> None:
    saida = tmp_path / "abordagem"
    args = ["abordagem", "--saida", str(saida), "--repeticoes", "20", "--p-falha-abordagem", "0", "0.5"]
    assert cli.main(args) == 0
    relatorio = (saida / "relatorio.md").read_text(encoding="utf-8")
    for trecho in ("N-abordagem-ruido", "Falsa refutação", "Tentativas até refutar", "Developer incapaz em 50%"):
        assert trecho in relatorio
    csv = (saida / "resultados.csv").read_text(encoding="utf-8")
    assert "catalogo" in csv and "simulacao" in csv and (saida / "manifesto.json").is_file()
    assert cli.main(args) == 2  # já tem manifesto.json
    assert cli.main([*args, "--sobrescrever"]) == 0


def test_relatorio_lista_so_os_cenarios_de_abordagem() -> None:
    rows = reports.abordagem_catalog_rows(catalog(), select_variants(load_variants(), NOMES), 0.3)
    assert {r["cenario"] for r in rows} == set(reports.CENARIOS_ABORDAGEM) and len(rows) == 16
