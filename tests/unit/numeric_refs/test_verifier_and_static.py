"""Verificador de números (X1–X9) e verificação estática de métricas literais (spec numeric-provenance)."""

from __future__ import annotations

import pytest

from src.numeric_refs.literal_metrics import read_literal_metrics, scan_code, write_findings
from src.numeric_refs.numbers import find_numbers
from src.numeric_refs.verifier import UNVERIFIED_MARK, verify_numbers

pytestmark = pytest.mark.unit


def _marked(text: str, **kw) -> list[str]:
    return [u.texto for u in verify_numbers(text, **kw).nao_verificados]


def test_algarismo_literal_e_marcado_sem_apagar():
    """Scenario: Algarismo literal."""
    out = verify_numbers("a acurácia foi 0,95")
    assert out.texto == f"a acurácia foi 0,95 {UNVERIFIED_MARK}" and [u.texto for u in out.nao_verificados] == ["0,95"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("o erro caiu três vezes", ["três vezes"]),
        ("ficou 3x menor", ["3x"]),
        ("ficou 3× menor", ["3×"]),
        ("foi o dobro do esperado", ["dobro"]),
        ("cresceu o triplo", ["triplo"]),
        ("uma ordem de grandeza maior", ["uma ordem de grandeza"]),
        ("duas ordens de grandeza", ["duas ordens de grandeza"]),
        ("cerca de dois terços", ["dois terços"]),
        ("metade dos casos", ["metade"]),
        ("dois vírgula cinco pontos", ["dois vírgula cinco"]),
        ("duzentos e cinquenta e três mil registros", ["duzentos e cinquenta e três mil"]),
        ("a taxa foi de 12% e subiu 3 pontos percentuais", ["12%", "3 pontos percentuais"]),
        ("entre 3 e 5 amostras", ["3", "5"]),
        ("faixa de 10–20 unidades", ["10–20"]),
        ("valor de 1,2 × 10^-3 e 1e-3", ["1,2 × 10^-3", "1e-3"]),
        ("mais de 1.234,5 casos e 5000", ["1.234,5", "5000"]),
    ],
)
def test_numeros_em_pt_br(text, expected):
    """Scenario: Multiplicador por extenso e demais formas."""
    assert _marked(text) == expected
    # o texto do número é preservado
    for item in expected:
        assert item in verify_numbers(text).texto


def test_numero_apos_span_renderizado_nao_e_marcado():
    """Scenario: Número após span renderizado."""
    text = "valor 7,1 % [C1] vezes maior"
    spans = [(6, 6 + len("7,1 % [C1]"))]
    assert _marked(text, protected_spans=spans) == []


def test_ano_e_numeracao_de_secao_nao_sao_marcados():
    """Scenario: Ano e numeração de seção."""
    text = "## 3.2 Resultados\n\n1. primeiro item\n\npublicado em 2021 e (Silva et al., 2020), ver [3]."
    assert _marked(text) == []


def test_ano_fora_de_contexto_e_marcado():
    """Scenario: Ano fora de contexto."""
    assert _marked("o modelo obteve 2000 amostras corretas") == ["2000"]


def test_contagem_do_orquestrador():
    """Scenario: Contagem do orquestrador."""
    text = "foram executadas três subtarefas. Em outro ponto, 5 subtarefas."
    assert _marked(text, counts={"subtarefa": 3}) == ["5"]
    assert _marked("foram 3 execuções", counts={}) == ["3"]  # o orquestrador não tem a contagem: marca
    assert _marked("foram 3 execuções", counts={"execucao": 3}) == []


def test_secao_do_orquestrador_nao_e_marcada():
    """Scenario: Seção do orquestrador."""
    text = "antes\n<!-- operation-metrics:begin -->\ntokens 1234, custo 5,5\n<!-- operation-metrics:end -->\ndepois 7"
    assert _marked(text) == ["7"]


@pytest.mark.parametrize(
    "text",
    [
        "`x = 42` e ```\ny = 3.14\n```",
        "veja https://exemplo.org/artigo/12 e [link](https://x.org/3)",
        "doi 10.1234/abc.567",
        "o modelo F1 e a camada L2 com qwen3:8b",
        "versão v1.2.3 em Python 3.11",
        "arquivo dados_2021.csv",
        "em 2026-10-08T10:00:00Z às 12:30",
        "em 5 de março de 2024",
        "hash 0123456789abcdef",
        "<!-- comentário 42 -->",
        "um relatório e uma análise, o primeiro e o segundo",
    ],
)
def test_exclusoes_estruturais(text):
    assert _marked(text) == []


def test_local_do_numero_nao_verificado_e_o_titulo():
    outcome = verify_numbers("## Limitações\nhouve 0,5 de erro")
    assert outcome.nao_verificados[0].local == "relatorio:Limitações"


def test_nao_marca_duas_vezes_e_percorre_o_texto_todo():
    first = verify_numbers("valor 0,95")
    again = verify_numbers(first.texto)
    assert again.texto == first.texto


def test_reconhecedor_encontra_um_unico_numero_no_trecho():
    assert len(find_numbers("RMSE de 0,42 mm")) == 1
    assert len(find_numbers("RMSE de 0,42 mm e MAE de 0,3 mm")) == 2


# --- verificação estática ------------------------------------------------------------------------------------------

def test_p1_dicionario_literal_nao_bloqueia():
    """Scenario: Dicionário literal."""
    code = 'from scientific_helpers import save_experiment_artifacts\nsave_experiment_artifacts("t", {}, {"acc": 0.95})'
    (finding,) = scan_code(code)
    assert (finding.metrica, finding.linha, finding.padrao) == ("acc", 2, "P1")


def test_p2_variavel_e_atribuicoes_posteriores():
    code = (
        'm = {"acc": 0.9, "loss": compute()}\n'
        'm["f1"] = 0.8\n'
        "k = 0.7\n"
        'm["x"] = k\n'
        'm["y"] = other()\n'
        'save_experiment_artifacts("t", {}, metrics=m)\n'
    )
    assert {(f.metrica, f.padrao) for f in scan_code(code)} == {("acc", "P2"), ("f1", "P2"), ("x", "P2")}


def test_p2_update_e_dict_call():
    code = 'm = dict(acc=0.9)\nm.update({"f1": 0.8}, loss=compute())\nsave_experiment_artifacts("t", {}, m)'
    assert {f.metrica for f in scan_code(code)} == {"acc", "f1"}


def test_p3_json_dump_e_write_text():
    dump = 'import json\nwith open("/outputs/metrics.json", "w") as f:\n    json.dump({"metrics": {"acc": 0.95}}, f)'
    text = 'from pathlib import Path\nPath("/outputs/metrics.json").write_text(json.dumps({"metrics": {"acc": 1}}))'
    assert [(f.metrica, f.padrao) for f in scan_code(dump)] == [("acc", "P3")]
    assert [(f.metrica, f.padrao) for f in scan_code(text)] == [("acc", "P3")]


def test_metrica_calculada_nao_e_sinalizada():
    """Scenario: Métrica calculada."""
    assert scan_code('metrics = {"acc": accuracy_score(y, y_hat)}\nsave_experiment_artifacts("t", {}, metrics)') == []
    assert scan_code("def f(:") == []  # código inválido: o sandbox acusa o erro


def test_arquivo_de_achados_e_leitura(tmp_path):
    findings = scan_code('save_experiment_artifacts("t", {}, {"acc": 0.95})')
    task_dir = tmp_path / "s1" / "treinar"
    task_dir.mkdir(parents=True)
    assert write_findings(task_dir, "exec_x", "h" * 64, []) is None
    assert not (task_dir / "metricas_literais.json").exists()
    write_findings(task_dir, "exec_x", "h" * 64, findings)
    assert read_literal_metrics(tmp_path / "s1") == {("exec_x", "acc")}
