"""Cadeia de proveniência sem falso ``divergente`` (v18.7-benchmark-fixes, achado 5 da bateria V18.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.numeric_refs.literal_metrics import LITERALS_FILE
from src.provenance.hashing import sha256_file
from src.provenance.verify import EXIT_INCONSISTENT, EXIT_OK, PLATFORM_WRITTEN_FILES, verify_project
from src.report.operation_metrics import ProvenanceChainReader

from .helpers import make_ledger, run_one

pytestmark = pytest.mark.unit

TASK = "s1/tarefa"


def _item(path: Path, relative: str) -> dict:
    return {"caminho": relative, "sha256": sha256_file(path), "tamanho": path.stat().st_size}


def _retry_pair(tmp_path: Path):
    """Duas execuções da mesma subtarefa: a segunda encontra ``metrics.json`` e o reescreve."""
    ledger = make_ledger(tmp_path)
    folder = tmp_path / "outputs" / "s1" / "tarefa"
    folder.mkdir(parents=True)
    metrics = folder / "metrics.json"
    metrics.write_text('{"metrics": {"r2": 0.1}}', encoding="utf-8")
    first = _item(metrics, f"{TASK}/metrics.json")
    run_one(ledger, termino_over={"saidas": [first]})
    metrics.write_text('{"metrics": {"r2": 0.9}}', encoding="utf-8")
    second = _item(metrics, f"{TASK}/metrics.json")
    run_one(ledger, termino_over={"entradas": [first], "saidas": [second]})
    return ledger, metrics


def test_retentativa_que_reescreve_metrics_json(tmp_path):
    """Scenario: Retentativa que reescreve metrics.json."""
    ledger, _ = _retry_pair(tmp_path)
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.integra and report.exit_code == EXIT_OK
    by_seq = {(a["seq"], a["papel"]): a for a in report.arquivos}
    assert by_seq[(2, "saida")]["estado"] == "substituido"  # a referência antiga (último escritor é a seguinte)
    assert by_seq[(4, "entrada")]["estado"] == "substituido"
    assert by_seq[(4, "entrada")]["detalhe"] == "consumida e reescrita pela mesma execução"
    assert by_seq[(4, "saida")]["estado"] == "ok"


def test_edicao_posterior_continua_detectada(tmp_path):
    """Scenario: Edição posterior continua detectada."""
    ledger, metrics = _retry_pair(tmp_path)
    metrics.write_text('{"metrics": {"r2": 0.5}}', encoding="utf-8")
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.exit_code == EXIT_INCONSISTENT
    assert [(a["papel"], a["estado"]) for a in report.arquivos_alterados] == [("saida", "alterado")]


def test_entrada_lida_sem_reescrita_continua_conferida(tmp_path):
    """Scenario: Entrada lida sem reescrita."""
    ledger = make_ledger(tmp_path)
    folder = tmp_path / "outputs" / "s1" / "tarefa"
    folder.mkdir(parents=True)
    data = folder / "dados.csv"
    data.write_text("a,b\n1,2\n", encoding="utf-8")
    run_one(ledger, termino_over={"entradas": [_item(data, f"{TASK}/dados.csv")]})
    data.write_text("a,b\n9,9\n", encoding="utf-8")
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.exit_code == EXIT_INCONSISTENT
    assert [a["caminho"] for a in report.arquivos_alterados] == [f"{TASK}/dados.csv"]


def test_arquivo_da_plataforma_reescrito_depois_do_termino_nao_e_adulteracao(tmp_path):
    """Achado da bateria V18.6: ``metricas_literais.json`` é gravado pela plataforma depois de cada execução."""
    assert LITERALS_FILE in PLATFORM_WRITTEN_FILES
    ledger = make_ledger(tmp_path)
    folder = tmp_path / "outputs" / "s1" / "tarefa"
    folder.mkdir(parents=True)
    literals = folder / LITERALS_FILE
    literals.write_text('{"achados": []}', encoding="utf-8")
    run_one(ledger, termino_over={"entradas": [_item(literals, f"{TASK}/{LITERALS_FILE}")]})
    literals.write_text('{"achados": [1]}', encoding="utf-8")  # a plataforma reescreve depois do último término
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.integra
    assert report.arquivos[0]["estado"] == "substituido" and "plataforma" in report.arquivos[0]["detalhe"]


def test_causa_da_divergencia_no_leitor(tmp_path, monkeypatch):
    """Scenario: Cadeia divergente por arquivo alterado (``cadeia.motivos`` e exemplos)."""
    ledger, metrics = _retry_pair(tmp_path)
    metrics.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.provenance.ledger.get_ledger", lambda: ledger)
    chain = ProvenanceChainReader().read("s1")["cadeia"]
    assert chain["resultado"] == "divergente"
    assert chain["motivos"] == {
        "cadeia": 0, "pares": 0, "arquivos_alterados": 1, "checkpoints_divergentes": 0, "conflitos_pendencia": 0,
    }
    assert chain["arquivos_alterados_exemplos"] == [f"{TASK}/metrics.json"]


def test_cadeia_integra_traz_motivos_zerados(tmp_path, monkeypatch):
    ledger, _ = _retry_pair(tmp_path)
    monkeypatch.setattr("src.provenance.ledger.get_ledger", lambda: ledger)
    chain = ProvenanceChainReader().read("s1")["cadeia"]
    assert chain["resultado"] == "integra" and not any(chain["motivos"].values())
    assert chain["arquivos_alterados_exemplos"] == []
