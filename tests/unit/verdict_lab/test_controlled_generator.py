"""Dados sintéticos de resposta conhecida (v18.8-verdict-controlled-sessions, requisitos de benchmark)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.verdict_lab.controlled import generator, regimes
from src.research_data.manifest import load_manifest

pytestmark = pytest.mark.unit

TOL = 0.005


def test_determinismo_byte_a_byte(tmp_path: Path) -> None:
    a = generator.escrever_csv(tmp_path / "a.csv", "P", 300, 7)
    b = generator.escrever_csv(tmp_path / "b.csv", "P", 300, 7)
    c = generator.escrever_csv(tmp_path / "c.csv", "P", 300, 8)
    assert a == b and a != c
    assert (tmp_path / "a.csv").read_bytes() == (tmp_path / "b.csv").read_bytes()


def test_formato_do_csv(tmp_path: Path) -> None:
    generator.escrever_csv(tmp_path / "d.csv", "N", 50, 1)
    with (tmp_path / "d.csv").open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "y"]
    assert len(rows) == 51 and all(r[-1] in ("0", "1") for r in rows[1:])


def test_familia_desconhecida() -> None:
    with pytest.raises(ValueError, match="desconhecida"):
        list(generator.linhas("Z", 1, 1))


@pytest.mark.parametrize("nome", ["P", "T"])
def test_teto_e_patamares_no_oraculo(nome: str) -> None:
    r = regimes.regime(nome)
    ora = generator.oraculo(r.familia)
    assert ora["teto"] == pytest.approx(r.teto, abs=TOL)
    assert len(ora["patamares"]) == len(r.patamares)
    for medido, esperado in zip(ora["patamares"], r.patamares, strict=True):
        assert medido == pytest.approx(esperado, abs=TOL)


def test_regime_f_usa_o_rotulo_de_p_com_12000_linhas() -> None:
    f, p = regimes.regime("F"), regimes.regime("P")
    assert f.familia == "P" and f.n_linhas == 12000 and f.abordagem_plantada
    assert (f.teto, f.alvo, f.patamares) == (p.teto, p.alvo, p.patamares)


def test_ruido_puro_sem_associacao_com_os_atributos() -> None:
    rows = list(generator.linhas("N", 2000, 3))
    ys = [y for _, y in rows]
    assert abs(sum(ys) / len(ys) - 0.5) < 0.045
    for j in range(generator.N_ATRIBUTOS):
        col = sorted(x[j] for x, _ in rows)
        mediana = col[len(col) // 2]
        acerto = sum(1 for x, y in rows if (x[j] > mediana) == bool(y)) / len(rows)
        assert max(acerto, 1 - acerto) < 0.55, f"x{j + 1}"


def test_alvos_e_tetos_aprovados() -> None:
    assert {n: (r.teto, r.alvo) for n, r in regimes.REGIMES.items()} == {
        "P": (0.96, 0.93), "T": (0.90, 0.93), "N": (0.50, 0.55), "F": (0.96, 0.93),
    }
    assert regimes.regime("T").teto < regimes.regime("T").alvo < regimes.regime("P").teto


def test_dados_yaml_aceito_pelo_carregador(tmp_path: Path) -> None:
    regimes.preparar_entrada("N", 5, tmp_path / "in", tmp_path / "verdade")
    marking = load_manifest(tmp_path / "in").marking_for(tmp_path / "in" / "dados.csv")
    assert marking.compartilhavel and marking.motivo == generator.MOTIVO_COMPARTILHAVEL
    assert marking.classe.name == "DADO_DE_PESQUISA"


def test_verdade_fora_da_entrada(tmp_path: Path) -> None:
    conteudo = regimes.preparar_entrada("T", 9, tmp_path / "in", tmp_path / "out" / "verdade")
    saved = json.loads((tmp_path / "out" / "verdade" / "verdade.json").read_text(encoding="utf-8"))
    assert saved == conteudo
    assert saved["regime"] == "T" and saved["resposta_correta"] == "nunca_funciona" and saved["semente"] == 9
    assert saved["sha256_dados"] == generator.sha256_arquivo(tmp_path / "in" / "dados.csv")
    assert not list((tmp_path / "in").rglob("verdade.json"))


def test_verdade_dentro_da_entrada_e_recusada(tmp_path: Path) -> None:
    with pytest.raises(regimes.RegimeError, match="enxergariam"):
        regimes.preparar_entrada("P", 1, tmp_path / "in", tmp_path / "in" / "sub")
    assert not (tmp_path / "in" / "dados.csv").exists()


def test_entrada_dentro_da_verdade_e_recusada(tmp_path: Path) -> None:
    with pytest.raises(regimes.RegimeError, match="enxergariam"):
        regimes.preparar_entrada("P", 1, tmp_path / "v" / "in", tmp_path / "v")


def test_regime_desconhecido() -> None:
    with pytest.raises(regimes.RegimeError, match="desconhecido"):
        regimes.regime("Z")


@pytest.mark.parametrize("nome", ["P", "T", "N", "F"])
def test_problema_do_regime(nome: str) -> None:
    r = regimes.regime(nome)
    draft = regimes.problem_draft(nome)
    criterio = draft.criterio_sucesso()
    assert criterio["tipo"] == "limiar" and criterio["metrica"] == "acurácia"
    assert criterio["alvo"] == r.alvo and criterio["delta_min"] == 0.01
    assert criterio["ao_atingir_objetivo"] == "continuar"
    assert draft.objective_gaps() == []


@pytest.mark.parametrize("nome", ["P", "T", "N", "F"])
def test_texto_neutro(nome: str) -> None:
    texto = (regimes.tarefa(nome) + " " + regimes.problem_draft(nome).resumo).lower()
    for proibido in ("interac", "interaç", "quadr", "alvo", "0,9", "0.9", "0,55", "0.55", "teto", "ruído", "ruido"):
        assert proibido not in texto, proibido


def test_verdade_do_regime_f_traz_a_assinatura() -> None:
    assert regimes.verdade("F", 1, "x")["abordagem_plantada"]["assinatura_falha"] == "MemoryError"
    assert regimes.verdade("P", 1, "x")["abordagem_plantada"] is None


def test_sementes_das_repeticoes_sao_deterministicas() -> None:
    a = generator.sementes_das_repeticoes(42, 5)
    assert a == generator.sementes_das_repeticoes(42, 5) and len(set(a)) == 5
    assert a != generator.sementes_das_repeticoes(43, 5)
    assert generator.sementes_das_repeticoes(42, 0) == []
