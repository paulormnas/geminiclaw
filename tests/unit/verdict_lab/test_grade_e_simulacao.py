"""Grade sintética, simulação, propriedades, sensibilidade e saída (v18.8-verdict-lab)."""

from __future__ import annotations

import csv
import json
import socket
from pathlib import Path

import pytest

from scripts.verdict_lab import __main__ as cli
from scripts.verdict_lab import output
from scripts.verdict_lab.properties import measure_properties
from scripts.verdict_lab.scenarios import ESPERADOS, by_name, catalog
from scripts.verdict_lab.sensitivity import run_sensitivity
from scripts.verdict_lab.simulation import SimPoint, estimate_calls, grid_points, run_simulation
from scripts.verdict_lab.variants import current_variant, lab_verdict, load_variants

pytestmark = pytest.mark.unit


def test_catalogo_segue_as_regras_do_pesquisador() -> None:
    s = by_name()
    assert s["E3"].esperado == "funciona" and s["E2"].esperado == "indeciso" and s["V8"].esperado == "indeciso"
    assert {x.familia for x in catalog()} >= set("EVRSNFMBCDPQGA")
    assert all(x.esperado in ESPERADOS and x.justificativa for x in catalog())
    assert len({x.nome for x in catalog()}) == len(catalog())


def test_caso_da_etapa_1_no_catalogo() -> None:
    sc = by_name()["F7-1"]
    assert lab_verdict(list(sc.attempts), sc.criterion, current_variant()).veredito == pytest.approx(0.0138, abs=5e-4)


def test_acerto_contra_o_esperado_e_varios_limiares(tmp_path: Path) -> None:
    out = tmp_path / "g"
    assert (
        cli.main(
            ["grade", "--saida", str(out), "--limiar", "0.2", "0.3", "--variante", "atual", "--variante", "completa"]
        )
        == 0
    )
    rows = list(csv.DictReader((out / "resultados.csv").open(encoding="utf-8")))
    assert {r["limiar"] for r in rows} == {"0.2", "0.3"}
    e3 = [r for r in rows if r["cenario"] == "E3" and r["variante"] == "atual" and r["limiar"] == "0.3"][0]
    assert e3["conclui"] == "indeciso" and e3["acerto"] == "False"
    assert len([r for r in rows if r["cenario"] == "E3" and r["variante"] == "atual"]) == 2


def test_propriedades_relatadas_sem_reprovar(tmp_path: Path) -> None:
    props = measure_properties([current_variant()], catalog())
    by = {p["propriedade"]: p for p in props}
    assert by["limites"]["violacoes"] == 0 and by["determinismo"]["violacoes"] == 0
    assert by["ordem_de_entrada"]["violacoes"] == 0
    assert by["simetria"]["violacoes"] > 0 and by["simetria"]["exemplo"]
    assert "V20" in by["volume_sem_ganho"]["exemplo"]
    assert cli.main(["grade", "--propriedades", "--saida", str(tmp_path / "g")]) == 0


def test_sensibilidade_parametro_sem_efeito_fica_no_fim() -> None:
    scenarios = [s for s in catalog() if s.nome in ("E1", "N1")]
    rows = [r for r in run_sensitivity(current_variant(), scenarios) if r["tabela"] == "isolado"]
    by = {r["parametro"]: r for r in rows}
    assert by["d_new_seed"]["efeito_max"] == 0 and by["d_new_seed"]["posicao"] > by["prior"]["posicao"]


POINT = dict(sigma=0.0, tau=0.0, efeito=0.01, p_variacao=1.0, p_falha=0.0, nos=1)


def test_simulacao_reprodutivel_pela_semente(tmp_path: Path) -> None:
    args = [
        "simulacao",
        "--repeticoes",
        "4",
        "--max-tentativas",
        "6",
        "--sigma",
        "0.01",
        "--tau",
        "0.01",
        "--efeito",
        "0.01",
        "--p-variacao",
        "1",
        "--p-falha",
        "0",
        "--nos",
        "1",
        "--semente",
        "7",
        "--variante",
        "atual",
        "--variante",
        "completa",
    ]
    assert cli.main(args + ["--saida", str(tmp_path / "a")]) == 0
    assert cli.main(args + ["--saida", str(tmp_path / "b")]) == 0
    assert (tmp_path / "a/resultados.csv").read_bytes() == (tmp_path / "b/resultados.csv").read_bytes()


def test_falsa_validacao_zero_sem_ruido() -> None:
    variants = [(v, None) for v in load_variants()]
    rows = run_simulation(
        grid_points({k: [v] for k, v in POINT.items()}),
        variants,
        semente=1,
        repeticoes=3,
        max_tentativas=10,
        limiares=[0.3],
        orcamentos=[5],
    )
    sem = [r for r in rows if r["tabela"] == "curva" and r["tipo"] == "sem_efeito" and r["limiar"] == 0.3]
    # sem ruído, a média real fica exatamente no alvo: tudo é positivo, e a taxa depende só de a fórmula concluir
    # com evidências idênticas; para hipóteses falsas (abaixo do alvo) nenhuma variante valida
    falsas = [r for r in rows if r["tabela"] == "curva" and r["tipo"] == "falsa"]
    assert falsas and all(r["validadas"] == 0 for r in falsas) and sem


def test_curva_de_compromisso_e_custo(tmp_path: Path) -> None:
    out = tmp_path / "s"
    assert (
        cli.main(
            [
                "simulacao",
                "--repeticoes",
                "3",
                "--max-tentativas",
                "5",
                "--sigma",
                "0.01",
                "--tau",
                "0.01",
                "--efeito",
                "0.02",
                "--p-variacao",
                "1",
                "--p-falha",
                "0",
                "--nos",
                "1",
                "--variante",
                "atual",
                "--saida",
                str(out),
            ]
        )
        == 0
    )
    rows = list(csv.DictReader((out / "resultados.csv").open(encoding="utf-8")))
    limiares = {float(r["limiar"]) for r in rows if r["tabela"] == "curva"}
    assert limiares >= {0.1, 0.2, 0.3, 0.4, 0.5, 0.6}
    assert "Custo por validação útil" in (out / "relatorio.md").read_text(encoding="utf-8")


def test_recordes_por_acaso_medidos_por_epsilon(tmp_path: Path) -> None:
    out = tmp_path / "e"
    assert (
        cli.main(
            [
                "simulacao",
                "--repeticoes",
                "5",
                "--max-tentativas",
                "8",
                "--sigma",
                "0.02",
                "--tau",
                "0.0",
                "--efeito",
                "0.01",
                "--p-variacao",
                "1",
                "--p-falha",
                "0",
                "--nos",
                "1",
                "--variante",
                "completa",
                "--expandir",
                "completa",
                "--saida",
                str(out),
            ]
        )
        == 0
    )
    names = {r["variante"] for r in csv.DictReader((out / "resultados.csv").open(encoding="utf-8"))}
    assert {"completa@eps=0", "completa@eps=delta", "completa@eps=sigma"} <= names
    assert any("d_replica=0.3" in n for n in names)


def test_estimativa_antes_de_comecar(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(
        [
            "simulacao",
            "--repeticoes",
            "2",
            "--max-tentativas",
            "4",
            "--sigma",
            "0.01",
            "--tau",
            "0",
            "--efeito",
            "0.01",
            "--p-variacao",
            "1",
            "--p-falha",
            "0",
            "--nos",
            "1",
            "--variante",
            "atual",
            "--saida",
            str(tmp_path / "x"),
        ]
    )
    first = capsys.readouterr().out.splitlines()[0]
    assert "cálculos do veredito" in first and "." not in first.split("cerca de ")[0][-1:]
    assert estimate_calls(1, 2, 1, 4) == 24


def test_manifesto_e_resultado_anterior_protegido(tmp_path: Path) -> None:
    out = tmp_path / "m"
    assert cli.main(["grade", "--saida", str(out), "--variante", "atual"]) == 0
    manifest = json.loads((out / "manifesto.json").read_text(encoding="utf-8"))
    assert manifest["comando"] == "grade" and manifest["commit"] and manifest["entradas"][0]["sha256"]
    assert manifest["variantes"][0]["parametros"]["gamma"] == 0.5
    before = (out / "resultados.csv").read_bytes()
    assert cli.main(["grade", "--saida", str(out), "--variante", "atual", "--familia", "E"]) == 2
    assert (out / "resultados.csv").read_bytes() == before
    assert cli.main(["grade", "--saida", str(out), "--variante", "atual", "--sobrescrever"]) == 0


def test_saida_recusa_raiz_home_e_link(tmp_path: Path) -> None:
    with pytest.raises(output.OutputError):
        output.prepare_output_dir(Path("/"), overwrite=False)
    with pytest.raises(output.OutputError):
        output.prepare_output_dir(Path.home(), overwrite=False)
    target = tmp_path / "t"
    target.mkdir()
    (tmp_path / "ln").symlink_to(target)
    with pytest.raises(output.OutputError):
        output.prepare_output_dir(tmp_path / "ln", overwrite=False)


def test_comandos_sem_rede_nem_llm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise AssertionError("rede/LLM não deve ser usada")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    assert cli.main(["grade", "--saida", str(tmp_path / "g"), "--variante", "atual"]) == 0
    assert cli.main(["sensibilidade", "--saida", str(tmp_path / "s"), "--variante", "atual"]) == 0
    assert (
        cli.main(
            [
                "simulacao",
                "--repeticoes",
                "2",
                "--max-tentativas",
                "4",
                "--sigma",
                "0.01",
                "--tau",
                "0",
                "--efeito",
                "0.01",
                "--p-variacao",
                "1",
                "--p-falha",
                "0",
                "--nos",
                "1",
                "--variante",
                "atual",
                "--saida",
                str(tmp_path / "m"),
            ]
        )
        == 0
    )


def test_nenhum_modulo_de_src_importa_o_laboratorio() -> None:
    root = Path(__file__).resolve().parents[3] / "src"
    assert not [p for p in root.rglob("*.py") if "verdict_lab" in p.read_text(encoding="utf-8")]


def test_sim_point_rotulos() -> None:
    assert SimPoint(**POINT).label()["granularidade"] is None


def test_criterio_de_aceite_da_simulacao(tmp_path: Path) -> None:
    out = tmp_path / "ac"
    assert (
        cli.main(
            [
                "simulacao",
                "--repeticoes",
                "6",
                "--max-tentativas",
                "10",
                "--sigma",
                "0.01",
                "--tau",
                "0.01",
                "--efeito",
                "0.02",
                "--p-variacao",
                "1",
                "--p-falha",
                "0",
                "--nos",
                "1",
                "--fv-max",
                "0.02",
                "--variante",
                "atual",
                "--variante",
                "completa2",
                "--expandir",
                "--saida",
                str(out),
            ]
        )
        == 0
    )
    rows = list(csv.DictReader((out / "resultados.csv").open(encoding="utf-8")))
    aceite = [r for r in rows if r["tabela"] == "aceite"]
    assert aceite and {r["fv_teto"] for r in aceite} == {"0.02"}
    assert all((float(r["fv_max_tipos"]) <= 0.02) == (r["aceita"] == "True") for r in aceite)
    report = (out / "relatorio.md").read_text(encoding="utf-8")
    assert "Critério de aceite: falsa validação de no máximo 2%" in report and "Menor limiar aceito" in report


def test_selecao_combina_simulacao_e_catalogo(tmp_path: Path) -> None:
    grade, sim, sel = tmp_path / "g", tmp_path / "s", tmp_path / "sel"
    limiares = ["0.2", "0.3"]
    assert (
        cli.main(
            [
                "grade",
                "--saida",
                str(grade),
                "--limiar",
                *limiares,
                "--variante",
                "atual",
                "--variante",
                "por_tipo",
                "--variante",
                "completa2",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "simulacao",
                "--repeticoes",
                "5",
                "--max-tentativas",
                "8",
                "--sigma",
                "0.01",
                "--tau",
                "0.01",
                "--efeito",
                "0.02",
                "--p-variacao",
                "1",
                "--p-falha",
                "0",
                "--nos",
                "1",
                "--limiar",
                *limiares,
                "--variante",
                "atual",
                "--variante",
                "por_tipo",
                "--variante",
                "completa2",
                "--expandir",
                "--saida",
                str(sim),
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "selecao",
                "--grade",
                str(grade / "resultados.csv"),
                "--simulacao",
                str(sim / "resultados.csv"),
                "--saida",
                str(sel),
            ]
        )
        == 0
    )
    rows = list(csv.DictReader((sel / "resultados.csv").open(encoding="utf-8")))
    by = {(r["variante"], r["limiar"]): r for r in rows}
    # por_tipo valida volume sem evolução (V8, V20) e é rejeitado pelo catálogo mesmo se estiver no teto da simulação
    rejeitado = by[("por_tipo", "0.2")]
    assert "V20" in rejeitado["cenarios_falsamente_validados"] and rejeitado["aceita"] == "False"
    assert by[("completa2", "0.3")]["falsas_validacoes_no_catalogo"] == "0"
    assert "Rejeitados pelo catálogo" in (sel / "relatorio.md").read_text(encoding="utf-8")
    assert (
        cli.main(
            [
                "selecao",
                "--grade",
                str(sim / "resultados.csv"),
                "--simulacao",
                str(sim / "resultados.csv"),
                "--saida",
                str(tmp_path / "x"),
            ]
        )
        == 2
    )
