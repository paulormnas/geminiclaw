"""Livro de execuções: registros, cadeia, concorrência, pendências e consultas (spec execution-provenance)."""

from __future__ import annotations

import json
import threading

import pytest

from src.provenance.canonical import ZERO_HASH
from src.provenance.errors import MetricNotRecorded, ProvenanceError
from src.provenance.ledger import PENDING_FILE, chain_id_for
from src.provenance.store import TIPO_INICIO, TIPO_TERMINO

from .helpers import inicio, make_ledger, run_one, termino

pytestmark = pytest.mark.unit


def test_par_inicio_termino_com_o_mesmo_exec_id(tmp_path):
    """Scenario: Execução bem-sucedida."""
    ledger = make_ledger(tmp_path)
    began, done = run_one(ledger, termino_over={"seed": 42, "hash_params": "p" * 64, "pacotes": {"numpy": "1.26.4"}})
    start = ledger.store.get(began.exec_id, TIPO_INICIO)
    end = ledger.store.get(began.exec_id, TIPO_TERMINO)
    assert began.exec_id.startswith("exec_") and len(began.exec_id) == len("exec_") + 36
    assert (start.seq, end.seq) == (1, 2) and end.prev_hash == start.record_hash
    assert end.corpo["inicio_hash"] == start.record_hash and end.corpo["status"] == "sucesso"
    assert done.pending is False and done.record == end


def test_primeiro_registro_tem_prev_hash_de_zeros(tmp_path):
    ledger = make_ledger(tmp_path)
    began, _ = run_one(ledger, finish=False)
    assert began.record.seq == 1 and began.record.prev_hash == ZERO_HASH


def test_encadeamento_entre_sessoes(tmp_path):
    """Scenario: Encadeamento entre sessões — a sessão retomada continua a mesma cadeia do projeto."""
    ledger = make_ledger(tmp_path)
    for _ in range(5):
        run_one(ledger, session_id="s1")
    tip = ledger.chain_tip("proj")
    assert tip["seq"] == 10
    began, _ = run_one(ledger, session_id="s2", finish=False)
    assert began.record.seq == 11 and began.record.prev_hash == tip["record_hash"]


def test_ida_e_volta_preserva_o_hash(tmp_path):
    """Scenario: Ida e volta pelo banco (aqui, pela serialização JSON do armazenamento)."""
    ledger = make_ledger(tmp_path)
    saida = {"caminho": "s/t/metrics.json", "sha256": "a" * 64, "tamanho": 3}
    _, done = run_one(ledger, termino_over={"saidas": [saida]})
    stored = ledger.store.get(done.record.exec_id, TIPO_TERMINO)
    rebuilt = json.loads(json.dumps(stored.hashed_form(), ensure_ascii=False))
    from src.provenance.canonical import record_hash

    assert record_hash(rebuilt) == stored.record_hash == stored.recompute_hash()


def test_cadeia_por_projeto_e_independente(tmp_path):
    ledger = make_ledger(tmp_path)
    run_one(ledger, project_id="a")
    began, _ = run_one(ledger, project_id="b", finish=False)
    assert began.record.seq == 1 and began.record.prev_hash == ZERO_HASH


def test_sem_projeto_a_cadeia_e_da_sessao(tmp_path):
    assert chain_id_for(None, "s9") == "sem_projeto:s9" and chain_id_for("p", "s9") == "p"
    ledger = make_ledger(tmp_path)
    began, _ = run_one(ledger, project_id=None, session_id="s9", finish=False)
    assert began.chain_id == "sem_projeto:s9"


def test_subtarefas_paralelas_geram_cadeia_sem_bifurcacao(tmp_path):
    """Scenario: Subtarefas paralelas — 8 execuções em duas sessões, seq 1..16, término depois do início."""
    ledger = make_ledger(tmp_path)

    def worker(index: int) -> None:
        run_one(ledger, session_id=f"s{index % 2}", subtask_id=f"sub-{index}", task_name=f"t{index}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    records = ledger.store.records("proj")
    assert [r.seq for r in records] == list(range(1, 17))
    for earlier, later in zip(records, records[1:]):
        assert later.prev_hash == earlier.record_hash
    starts = {r.exec_id: r.seq for r in records if r.tipo == TIPO_INICIO}
    assert all(r.seq > starts[r.exec_id] for r in records if r.tipo == TIPO_TERMINO)


# --- pendências ---------------------------------------------------------------------------------------------------

def test_banco_indisponivel_no_inicio_nao_registra(tmp_path):
    """Scenario: Banco indisponível no início — o chamador não executa nada."""
    from src.provenance.errors import ProvenanceUnavailable

    ledger = make_ledger(tmp_path)
    ledger.store.unavailable = True
    with pytest.raises(ProvenanceUnavailable):
        ledger.begin(project_id="p", session_id="s1", subtask_id=None, task_name="t", body=inicio())


def test_termino_vai_para_o_arquivo_de_pendencias_e_entra_depois(tmp_path):
    """Scenario: Banco cai durante a execução."""
    ledger = make_ledger(tmp_path)
    began, _ = run_one(ledger, finish=False)
    ledger.store.unavailable = True
    done = ledger.finish(
        exec_id=began.exec_id, chain_id=began.chain_id, session_id="s1", subtask_id="sub-1", task_name="tarefa",
        body=termino(began.record.record_hash, seed=7),
    )
    assert done.pending is True and done.record is None
    pending_file = tmp_path / "outputs" / "s1" / PENDING_FILE
    assert ledger.pending_exec_ids("s1") == [began.exec_id] and pending_file.is_file()

    ledger.store.unavailable = False
    again = ledger.begin(project_id="proj", session_id="s1", subtask_id="sub-2", task_name="t2", body=inicio())
    # o término pendente entrou ANTES do novo início e saiu do arquivo
    end = ledger.store.get(began.exec_id, TIPO_TERMINO)
    assert end is not None and end.seq < again.record.seq
    assert end.corpo["registrado_localmente_em"] and end.corpo["seed"] == 7
    assert not pending_file.exists() and ledger.pending_exec_ids("s1") == []


def test_pendencia_ja_acrescentada_nao_duplica(tmp_path):
    """Scenario: Pendência já acrescentada."""
    ledger = make_ledger(tmp_path)
    began, done = run_one(ledger)
    entry = {
        "exec_id": began.exec_id, "project_id": "proj", "tipo": "termino", "session_id": "s1", "subtask_id": "sub-1",
        "task_name": "tarefa", "registrado_em": "2026-10-08T00:00:00+00:00", "corpo": done.record.corpo,
    }
    from src.provenance.ledger import corpo_sha256

    entry["corpo_sha256"] = corpo_sha256(entry["corpo"])
    path = tmp_path / "outputs" / "s1" / PENDING_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    before = len(ledger.store.records("proj"))
    report = ledger.flush_pending("s1")
    assert report.already == [began.exec_id] and not report.appended
    assert len(ledger.store.records("proj")) == before and not path.exists()


def test_pendencia_com_corpo_diferente_e_conflito(tmp_path):
    ledger = make_ledger(tmp_path)
    began, done = run_one(ledger)
    from src.provenance.ledger import corpo_sha256

    other = {**done.record.corpo, "seed": 999}
    entry = {
        "exec_id": began.exec_id, "project_id": "proj", "tipo": "termino", "session_id": "s1", "subtask_id": "sub-1",
        "task_name": "tarefa", "registrado_em": "x", "corpo": other, "corpo_sha256": corpo_sha256(other),
    }
    (tmp_path / "outputs" / "s1").mkdir(parents=True, exist_ok=True)
    (tmp_path / "outputs" / "s1" / PENDING_FILE).write_text(json.dumps(entry) + "\n", encoding="utf-8")
    report = ledger.flush_pending("s1")
    assert report.conflicts == [began.exec_id] and ledger.pending_exec_ids("s1") == [began.exec_id]


def test_pendencia_adulterada_no_arquivo_nao_entra(tmp_path):
    ledger = make_ledger(tmp_path)
    began, _ = run_one(ledger, finish=False)
    ledger.store.unavailable = True
    ledger.finish(
        exec_id=began.exec_id, chain_id=began.chain_id, session_id="s1", subtask_id=None, task_name="t",
        body=termino(began.record.record_hash),
    )
    ledger.store.unavailable = False
    path = tmp_path / "outputs" / "s1" / PENDING_FILE
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["corpo"]["status"] = "falha_execucao"
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    report = ledger.flush_pending("s1")
    assert report.conflicts == [began.exec_id] and ledger.store.get(began.exec_id, TIPO_TERMINO) is None


def test_sem_banco_e_sem_disco_a_skill_recebe_erro_explicito(tmp_path):
    """Scenario: Sem banco e sem disco."""
    ledger = make_ledger(tmp_path)
    began, _ = run_one(ledger, finish=False)
    ledger.store.unavailable = True
    # um arquivo no lugar do diretório da sessão impede gravar as pendências
    ledger.output_dir = tmp_path / "bloqueado"
    ledger.output_dir.write_text("arquivo")
    with pytest.raises(ProvenanceError, match="término não registrado nem guardado localmente"):
        ledger.finish(
            exec_id=began.exec_id, chain_id=began.chain_id, session_id="s1", subtask_id=None, task_name="t",
            body=termino(began.record.record_hash),
        )


def test_flush_com_banco_fora_do_ar_mantem_o_arquivo(tmp_path):
    ledger = make_ledger(tmp_path)
    began, _ = run_one(ledger, finish=False)
    ledger.store.unavailable = True
    ledger.finish(
        exec_id=began.exec_id, chain_id=began.chain_id, session_id="s1", subtask_id=None, task_name="t",
        body=termino(began.record.record_hash),
    )
    report = ledger.flush_pending("s1")
    assert report.remaining == [began.exec_id] and ledger.pending_exec_ids("s1") == [began.exec_id]


# --- consultas ----------------------------------------------------------------------------------------------------

def test_get_metric_devolve_valor_seq_e_hash(tmp_path):
    ledger = make_ledger(tmp_path)
    began, done = run_one(ledger, termino_over={"metricas": {"r2": "0.8"}})
    metric = ledger.get_metric(began.exec_id, "r2")
    assert (metric.valor_texto, metric.seq, metric.record_hash) == ("0.8", done.record.seq, done.record.record_hash)


def test_get_metric_inexistente_levanta_erro(tmp_path):
    """Scenario: Métrica inexistente — sem valor padrão."""
    ledger = make_ledger(tmp_path)
    began, _ = run_one(ledger, termino_over={"metricas": {"r2": "0.8"}})
    with pytest.raises(MetricNotRecorded, match="f1"):
        ledger.get_metric(began.exec_id, "f1")
    with pytest.raises(MetricNotRecorded):
        ledger.get_metric("exec_inexistente", "r2")


def test_derivacao_do_experimento_com_retentativa(tmp_path):
    """Scenario: Subtarefa com retentativa — exec_id, hash_codigo e seed vêm da execução com sucesso."""
    ledger = make_ledger(tmp_path)
    failed, _ = run_one(
        ledger, termino_over={"status": "falha_execucao", "exit_code": 1, "hash_codigo": "1" * 64, "seed": 1}
    )
    ok, _ = run_one(
        ledger,
        termino_over={
            "hash_codigo": "2" * 64, "seed": 42, "hash_params": "p" * 64, "metricas": {"r2": "0.8"},
            "hash_metrics": "m" * 64,
            "saidas": [{"caminho": "s1/tarefa/metrics.json", "sha256": "m" * 64, "tamanho": 9}],
            "pacotes": {"numpy": "1.26.4"}, "python_version": "3.11.9",
        },
    )
    derived = ledger.derive_experiment_fields("sub-1")
    assert derived.exec_ids == [failed.exec_id, ok.exec_id] and derived.exec_id == ok.exec_id
    assert (derived.hash_codigo, derived.seed, derived.hash_params) == ("2" * 64, 42, "p" * 64)
    assert derived.ambiente["python"] == "3.11.9" and derived.ambiente["pacotes"] == {"numpy": "1.26.4"}
    assert derived.metricas == {"r2": "0.8"} and derived.hash_metrics == "m" * 64


def test_derivacao_sem_sucesso_usa_o_ultimo_termino(tmp_path):
    ledger = make_ledger(tmp_path)
    run_one(ledger, termino_over={"status": "falha_execucao", "exit_code": 1})
    last, _ = run_one(ledger, termino_over={"status": "timeout", "exit_code": -1})
    derived = ledger.derive_experiment_fields("sub-1")
    assert derived.exec_id == last.exec_id and derived.status == "timeout"
    assert ledger.derive_experiment_fields("nenhuma") is None
