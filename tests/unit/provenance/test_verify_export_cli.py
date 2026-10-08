"""Verificação, exportação, seção do relatório e CLI (spec execution-provenance)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli_provenance import handle_provenance_command
from src.provenance.errors import ProvenanceUnavailable
from src.provenance.export import export_session
from src.provenance.hashing import sha256_file
from src.provenance.ledger import PENDING_FILE, corpo_sha256
from src.provenance.report import provenance_section
from src.provenance.verify import (
    EXIT_INCONSISTENT,
    EXIT_OK,
    verify_export,
    verify_project,
    verify_session,
)

from .helpers import make_ledger, run_one

pytestmark = pytest.mark.unit


def _with_output(tmp_path: Path, ledger, name="metrics.json", content='{"metrics": {"r2": 0.8}}'):
    """Execução que registra um arquivo de saída real em disco."""
    out_dir = tmp_path / "outputs" / "s1" / "tarefa"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(content, encoding="utf-8")
    saida = {"caminho": f"s1/tarefa/{name}", "sha256": sha256_file(path), "tamanho": path.stat().st_size}
    began, done = run_one(ledger, termino_over={"saidas": [saida], "hash_metrics": saida["sha256"]})
    return began, done, path


def test_cadeia_integra(tmp_path):
    ledger = make_ledger(tmp_path)
    _with_output(tmp_path, ledger)
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.integra and report.exit_code == EXIT_OK and report.registros == 2
    assert [a["estado"] for a in report.arquivos] == ["ok"]


def test_registro_adulterado_e_apontado_pelo_seq(tmp_path):
    """Scenario: Registro adulterado."""
    ledger = make_ledger(tmp_path)
    run_one(ledger)
    ledger.store.tamper("proj", 2, corpo={"status": "sucesso", "inventado": True})
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.exit_code == EXIT_INCONSISTENT
    assert any(p["seq"] == 2 and "alterado" in p["problema"] for p in report.problemas_cadeia)


def test_lacuna_na_cadeia(tmp_path):
    ledger = make_ledger(tmp_path)
    run_one(ledger)
    run_one(ledger)
    chain = ledger.store._rows["proj"]  # noqa: SLF001 - simula a remoção de um registro
    del chain[1]
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.exit_code == EXIT_INCONSISTENT and any("lacuna" in p["problema"] for p in report.problemas_cadeia)


def test_arquivo_de_saida_alterado(tmp_path):
    """Scenario: Arquivo de saída alterado."""
    ledger = make_ledger(tmp_path)
    _, _, path = _with_output(tmp_path, ledger)
    path.write_text('{"metrics": {"r2": 0.99}}', encoding="utf-8")
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.exit_code == EXIT_INCONSISTENT
    assert [a["estado"] for a in report.arquivos_alterados] == ["alterado"]


def test_arquivo_ausente_nao_quebra_a_verificacao(tmp_path):
    ledger = make_ledger(tmp_path)
    _, _, path = _with_output(tmp_path, ledger)
    path.unlink()
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.exit_code == EXIT_OK and report.arquivos[0]["estado"] == "ausente"


def test_arquivo_reescrito_por_execucao_posterior_nao_e_alteracao(tmp_path):
    """O último escritor do caminho é quem vale: a retentativa que reescreve metrics.json não acusa a anterior."""
    ledger = make_ledger(tmp_path)
    _with_output(tmp_path, ledger, content='{"metrics": {"r2": 0.1}}')
    _, _, path = _with_output(tmp_path, ledger, content='{"metrics": {"r2": 0.9}}')
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    states = sorted(a["estado"] for a in report.arquivos)
    assert report.exit_code == EXIT_OK and states == ["ok", "substituido"] and path.exists()


def test_orfa_sem_termino_apos_queda(tmp_path):
    """Scenario: Execução órfã após queda — aparece em ``orfas`` e o código de saída continua 0."""
    ledger = make_ledger(tmp_path)
    began, _ = run_one(ledger, finish=False)
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.exit_code == EXIT_OK
    assert report.orfas == [{"exec_id": began.exec_id, "classe": "sem_termino", "task_name": "tarefa", "seq": 1}]


def test_orfa_com_termino_pendente_local(tmp_path):
    ledger = make_ledger(tmp_path)
    began, _ = run_one(ledger, finish=False)
    ledger.store.unavailable = True
    from .helpers import termino

    ledger.finish(
        exec_id=began.exec_id, chain_id=began.chain_id, session_id="s1", subtask_id=None, task_name="tarefa",
        body=termino(began.record.record_hash),
    )
    ledger.store.unavailable = False
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.orfas[0]["classe"] == "pendente_local" and report.pendencias == [began.exec_id]
    assert report.exit_code == EXIT_OK


def test_pendencia_em_conflito_gera_codigo_1(tmp_path):
    ledger = make_ledger(tmp_path)
    began, done = run_one(ledger)
    other = {**done.record.corpo, "seed": 5}
    entry = {"exec_id": began.exec_id, "corpo": other, "corpo_sha256": corpo_sha256(other)}
    path = tmp_path / "outputs" / "s1" / PENDING_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.conflitos_pendencia == [began.exec_id] and report.exit_code == EXIT_INCONSISTENT


def test_checkpoint_com_ponta_divergente(tmp_path):
    ledger = make_ledger(tmp_path)
    run_one(ledger)
    tip = ledger.chain_tip("proj")
    session = tmp_path / "outputs" / "s1"
    session.mkdir(parents=True, exist_ok=True)
    (session / "checkpoint.json").write_text(json.dumps({"provenance_chain_tip": tip}), encoding="utf-8")
    assert verify_project(ledger.store, "proj", tmp_path / "outputs").exit_code == EXIT_OK
    bad = {**tip, "record_hash": "f" * 64}
    (session / "checkpoint.json").write_text(json.dumps({"provenance_chain_tip": bad}), encoding="utf-8")
    report = verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert report.exit_code == EXIT_INCONSISTENT and report.checkpoints_divergentes[0]["session_id"] == "s1"


def test_banco_indisponivel_levanta_para_o_chamador_traduzir_em_2(tmp_path):
    """Scenario: Banco indisponível."""
    ledger = make_ledger(tmp_path)
    ledger.store.unavailable = True
    with pytest.raises(ProvenanceUnavailable):
        verify_project(ledger.store, "proj", tmp_path / "outputs")
    assert handle_provenance_command(["verify", "proj"], ledger) == 2


def test_verificacao_da_sessao_ignora_registros_de_outras_sessoes(tmp_path):
    ledger = make_ledger(tmp_path)
    run_one(ledger, session_id="s1")
    other, _ = run_one(ledger, session_id="s2", finish=False)
    (report,) = verify_session(ledger.store, "s1", tmp_path / "outputs")
    assert report.orfas == [] and other.exec_id not in str(report.orfas)


# --- exportação ---------------------------------------------------------------------------------------------------

def test_exportacao_e_verificacao_sem_banco(tmp_path):
    """Scenario: Verificação de exportação — elos conferidos e o primeiro prev_hash exibido como âncora."""
    ledger = make_ledger(tmp_path)
    run_one(ledger, session_id="s0")  # sessão anterior do mesmo projeto
    run_one(ledger, session_id="s1")
    run_one(ledger, session_id="s1")
    target = export_session(ledger.store, "s1", tmp_path / "outputs")
    assert (target / "execution_records.jsonl").is_file() and (target / "chain_tip.json").is_file()
    tip = json.loads((target / "chain_tip.json").read_text(encoding="utf-8"))
    assert tip["seq"] == 6 and tip["primeiro_seq"] == 3
    (report,) = verify_export(target)
    assert report.integra and report.registros == 4 and report.ancora_prev_hash == tip["primeiro_prev_hash"]
    assert handle_provenance_command(["verify", "--from-export", str(target)], make_ledger(tmp_path)) == 0


def test_exportacao_adulterada_e_detectada(tmp_path):
    ledger = make_ledger(tmp_path)
    run_one(ledger, session_id="s1")
    target = export_session(ledger.store, "s1", tmp_path / "outputs")
    lines = (target / "execution_records.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["corpo"]["status"] = "falha_execucao"
    lines[1] = json.dumps(record, ensure_ascii=False)
    (target / "execution_records.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (report,) = verify_export(target)
    assert not report.integra and report.exit_code == EXIT_INCONSISTENT


def test_sessao_sem_execucoes_nao_exporta(tmp_path):
    assert export_session(make_ledger(tmp_path).store, "vazia", tmp_path / "outputs") is None


# --- seção do relatório e CLI -------------------------------------------------------------------------------------

def test_secao_do_relatorio_traz_ponta_status_e_verificacao(tmp_path):
    """Scenario: Fechamento da sessão."""
    ledger = make_ledger(tmp_path)
    run_one(ledger)
    run_one(ledger, termino_over={"status": "timeout", "exit_code": -1})
    run_one(ledger, termino_over={"rede_na_execucao": True, "ativos": [{"url": "u", "hash_declarado": False}]})
    text = provenance_section(ledger, "s1", tmp_path / "outputs")
    tip = ledger.chain_tip("proj")
    assert f"seq={tip['seq']}" in text and tip["record_hash"] in text
    assert "Execuções da sessão**: 3" in text and "sucesso: 2" in text and "timeout: 1" in text
    assert "Verificação da sessão**: íntegra" in text
    assert "Ativos sem hash declarado**: 1" in text and "rede na fase execute**: 1" in text
    assert (tmp_path / "outputs" / "s1" / "provenance" / "chain_tip.json").is_file()


def test_secao_sem_execucoes_e_sem_banco(tmp_path):
    ledger = make_ledger(tmp_path)
    assert "Nenhuma execução" in provenance_section(ledger, "s1", tmp_path / "outputs")
    ledger.store.unavailable = True
    assert "Não foi possível consultar" in provenance_section(ledger, "s1", tmp_path / "outputs")


def test_secao_menciona_ponta_divergente_na_retomada(tmp_path):
    ledger = make_ledger(tmp_path)
    run_one(ledger)
    text = provenance_section(ledger, "s1", tmp_path / "outputs", divergences=["ponta seq 9 ausente"])
    assert "Ponta divergente na retomada" in text and "ponta seq 9 ausente" in text


def test_cli_verify_codigos_de_saida_e_json(tmp_path, monkeypatch, capsys):
    from src import config

    monkeypatch.setattr(config, "OUTPUT_BASE_DIR", str(tmp_path / "outputs"))
    monkeypatch.setattr(config, "PROVENANCE_HASH_CACHE_PATH", str(tmp_path / "cache.db"))
    ledger = make_ledger(tmp_path)
    run_one(ledger)
    assert handle_provenance_command(["verify", "proj"], ledger) == 0
    assert "ÍNTEGRA" in capsys.readouterr().out
    assert handle_provenance_command(["verify", "proj", "--json", "--full"], ledger) == 0
    assert json.loads(capsys.readouterr().out)[0]["integra"] is True
    ledger.store.tamper("proj", 1, task_name="outro")
    assert handle_provenance_command(["verify", "proj"], ledger) == 1
    assert handle_provenance_command(["verify"], ledger) == 2
    assert handle_provenance_command(["export", "--session", "s1"], ledger) == 0
    assert (tmp_path / "outputs" / "s1" / "provenance" / "execution_records.jsonl").is_file()


def test_limpeza_de_dev_nao_trunca_a_tabela_de_execucoes():
    """Tarefa 3.7: ``execution_records`` fica fora da lista de tabelas limpas."""
    import importlib.util

    path = Path(__file__).resolve().parents[3] / ".agents" / "skills" / "clean_dev.py"
    spec = importlib.util.spec_from_file_location("clean_dev_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "execution_records" not in module.POSTGRES_TABLES
    sql = (Path(__file__).resolve().parents[3] / "scripts" / "migrations" / "v18_5_001_execution_records.sql").read_text()
    assert "BEFORE TRUNCATE" in sql and "BEFORE UPDATE OR DELETE" in sql
    init = (Path(__file__).resolve().parents[3] / "scripts" / "init_db.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS execution_records" in init
