"""Ponta da cadeia no checkpoint, retomada e derivação de ``Experimento``/``Resultado`` (spec execution-provenance)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.continuity import Checkpoint, CheckpointError, CheckpointRecorder, read_checkpoint
from src.knowledge import vocabulary
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.ingestion import (
    ProvenancePending,
    SessionContext,
    SubtaskInput,
    ingest_session_start,
    ingest_subtask,
)
from src.knowledge.projects import create_project
from src.knowledge.vocabulary import seed_vocabulary
from src.orchestrator import Orchestrator
from src.provenance.hashing import sha256_file
from src.provenance.ledger import get_ledger

from .helpers import inicio, run_one, termino

pytestmark = pytest.mark.unit

FIXTURE_CSV = Path(__file__).resolve().parents[2] / "fixtures" / "cnpq_areas_fixture.csv"
REAL_METRICS = vocabulary.DEFAULT_VOCABULARY_DIR / vocabulary.METRICS_FILENAME
PROJ = "3f2b8c1e-5d4a-4b6f-9a7e-1c2d3e4f5a6b"
TIP = {"project_id": PROJ, "seq": 4, "record_hash": "a" * 64}


# --- checkpoint ---------------------------------------------------------------------------------------------------

def test_checkpoint_serializa_e_le_a_ponta(tmp_path):
    session = tmp_path / "s1"
    session.mkdir()
    recorder = CheckpointRecorder.start(
        session, session_id="s1", project_id=PROJ, continues_session_id=None, prompt="p", modo="auto"
    )
    recorder.provenance_provider = lambda: (TIP, ["exec_x"])
    recorder.set_usage(consumo={"tokens": 1})
    checkpoint, _ = read_checkpoint(session, expected_session_id="s1")
    assert checkpoint.provenance_chain_tip == TIP and checkpoint.provenance_pending == ["exec_x"]
    assert json.loads((session / "checkpoint.json").read_text(encoding="utf-8"))["provenance_chain_tip"] == TIP


def test_checkpoint_sem_ponta_continua_valido(tmp_path):
    session = tmp_path / "s1"
    session.mkdir()
    CheckpointRecorder.start(
        session, session_id="s1", project_id=None, continues_session_id=None, prompt="p", modo="auto"
    )
    checkpoint, _ = read_checkpoint(session, expected_session_id="s1")
    assert checkpoint.provenance_chain_tip is None and checkpoint.provenance_pending == []


@pytest.mark.parametrize(
    "tip",
    [{"project_id": "p", "seq": 0, "record_hash": "a" * 64}, {"project_id": "p", "seq": 1, "record_hash": "xyz"},
     {"project_id": "", "seq": 1, "record_hash": "a" * 64}, "texto"],
)
def test_ponta_invalida_no_checkpoint_e_recusada(tip):
    data = Checkpoint(session_id="s1").to_dict()
    data["provenance_chain_tip"] = tip
    with pytest.raises(CheckpointError):
        Checkpoint.from_dict(data, expected_session_id="s1")


def test_falha_do_provedor_nao_impede_a_gravacao(tmp_path):
    session = tmp_path / "s1"
    session.mkdir()
    recorder = CheckpointRecorder.start(
        session, session_id="s1", project_id=None, continues_session_id=None, prompt="p", modo="auto"
    )

    def broken():
        raise RuntimeError("sem ledger")

    recorder.provenance_provider = broken
    assert recorder.set_usage(consumo={"tokens": 2}) is True


def test_fechamento_grava_a_ponta_conhecida_do_processo(tmp_path):
    """Scenario: Fechamento da sessão — o checkpoint traz a ponta do projeto."""
    ledger = get_ledger()
    run_one(ledger, project_id=PROJ, session_id="s1")
    session = tmp_path / "s1"
    session.mkdir()
    recorder = CheckpointRecorder.start(
        session, session_id="s1", project_id=PROJ, continues_session_id=None, prompt="p", modo="auto"
    )
    orch = Orchestrator(session_manager=MagicMock(), output_manager=MagicMock(base_dir=tmp_path))
    recorder.provenance_provider = orch._provenance_provider("s1", PROJ)  # noqa: SLF001
    recorder.close("fechado", None)
    checkpoint, _ = read_checkpoint(session, expected_session_id="s1")
    assert checkpoint.provenance_chain_tip == ledger.known_tip(PROJ) and checkpoint.provenance_chain_tip["seq"] == 2


# --- retomada -----------------------------------------------------------------------------------------------------

def _orchestrator_with_checkpoint(tmp_path: Path, tip: dict | None) -> Orchestrator:
    source = tmp_path / "origem"
    source.mkdir()
    recorder = CheckpointRecorder.start(
        source, session_id="origem", project_id=PROJ, continues_session_id=None, prompt="p", modo="auto"
    )
    if tip is not None:
        recorder.provenance_provider = lambda: (tip, [])
        recorder.set_usage(consumo={"tokens": 1})
    return Orchestrator(session_manager=MagicMock(), output_manager=MagicMock(base_dir=tmp_path))


def test_retomada_com_ponta_existente_nao_avisa(tmp_path):
    ledger = get_ledger()
    run_one(ledger, project_id=PROJ)
    orch = _orchestrator_with_checkpoint(tmp_path, ledger.chain_tip(PROJ))
    assert orch.resume_provenance_divergence("origem") is None


def test_ponta_divergente_na_retomada_avisa_e_registra_evento(tmp_path, monkeypatch):
    """Scenario: Ponta divergente na retomada."""
    run_one(get_ledger(), project_id=PROJ)
    orch = _orchestrator_with_checkpoint(tmp_path, {"project_id": PROJ, "seq": 2, "record_hash": "f" * 64})
    events = MagicMock()
    monkeypatch.setattr("src.orchestrator.get_telemetry", lambda: events)
    message, seq = orch.resume_provenance_divergence("origem")
    assert seq == 2 and "provenance verify" in message
    orch._note_resume_provenance("nova", "origem")  # noqa: SLF001
    assert orch.provenance_warnings["nova"] == [message]
    assert events.record_agent_event.call_args.kwargs["event_type"] == "proveniencia_divergente"


def test_retomada_sem_ponta_no_checkpoint_ou_sem_registro_nao_bloqueia(tmp_path):
    assert _orchestrator_with_checkpoint(tmp_path, None).resume_provenance_divergence("origem") is None
    get_ledger().store.unavailable = True
    orch = _orchestrator_with_checkpoint(tmp_path / "x", TIP) if (tmp_path / "x").mkdir() is None else None
    assert orch.resume_provenance_divergence("origem") is None


# --- derivação no grafo -------------------------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path_factory) -> InMemoryGraphStore:
    vocab_dir = tmp_path_factory.mktemp("vocab")
    shutil.copy(FIXTURE_CSV, vocab_dir / vocabulary.CNPQ_FILENAME)
    shutil.copy(REAL_METRICS, vocab_dir / vocabulary.METRICS_FILENAME)
    s = InMemoryGraphStore()
    seed_vocabulary(s, vocabulary_dir=vocab_dir)
    return s


@pytest.fixture
def ctx(store) -> SessionContext:
    project_id = create_project(store, "Projeto", "Objetivo", [])
    return SessionContext(
        project_id=project_id, session_id="sessao-teste", modo="auto", inicio="2026-10-06T10:00:00+00:00",
        no_execucao="no-1",
    )


def _write_run(tmp_path: Path, task="treinar", metrics=None) -> Path:
    folder = tmp_path / "sessao-teste" / task
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "params.json").write_text(json.dumps({"task_name": task, "seed": 42, "parameters": {"k": 1}}))
    payload = {"task_name": task, "seed": 42, "parameters": {"k": 1}, "metrics": metrics or {"r2": 0.8}}
    (folder / "metrics.json").write_text(json.dumps(payload))
    return folder / "metrics.json"


def _record_run(tmp_path, metrics_file: Path, *, status="sucesso", seed=42, code_hash="2" * 64, subtask="sub-1"):
    digest = sha256_file(metrics_file)
    return run_one(
        get_ledger(), project_id="proj", session_id="sessao-teste", subtask_id=subtask, task_name="treinar",
        termino_over={
            "status": status, "seed": seed, "hash_codigo": code_hash, "hash_params": "p" * 64,
            "metricas": {"r2": "0.8"}, "hash_metrics": digest, "python_version": "3.11.9",
            "saidas": [{"caminho": "sessao-teste/treinar/metrics.json", "sha256": digest, "tamanho": 9}],
            "pacotes": {"numpy": "1.26.4"},
        },
    )


def _sub() -> SubtaskInput:
    return SubtaskInput(task_name="treinar", subtask_id="sub-1", agent_id="developer", review_status="pass",
                        review_verified=True)


def _nodes(store, label):
    return store.find_nodes(label, {}, limit=100)


def test_experimento_e_resultado_derivados_do_registro(tmp_path, store, ctx):
    """Scenarios: Subtarefa com retentativa e Valor do Resultado vem do registro."""
    session_dir = tmp_path / "sessao-teste"
    metrics_file = _write_run(tmp_path)
    failed, _ = run_one(
        get_ledger(), project_id="proj", session_id="sessao-teste", subtask_id="sub-1", task_name="treinar",
        termino_over={"status": "falha_execucao", "exit_code": 1, "seed": 1, "hash_codigo": "1" * 64},
    )
    ok, _ = _record_run(tmp_path, metrics_file)
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub())
    (exp,) = _nodes(store, "Experimento")
    assert exp.properties["exec_ids"] == [failed.exec_id, ok.exec_id] and exp.properties["exec_id"] == ok.exec_id
    assert exp.properties["hash_codigo"] == "2" * 64 and exp.properties["seed"] == 42
    assert exp.properties["hash_params"] == "p" * 64
    ambiente = exp.properties["ambiente"]
    assert ambiente["python"] == "3.11.9" and ambiente["pacotes"] == ["numpy==1.26.4"]
    (res,) = _nodes(store, "Resultado")
    assert res.properties["valor"] == 0.8 and res.properties["exec_id"] == ok.exec_id
    assert res.properties["hash_metrics"] == sha256_file(metrics_file)


def test_metrics_editado_antes_da_ingestao_nao_cria_resultado(tmp_path, store, ctx, monkeypatch):
    """Scenario: metrics.json editado antes da ingestão."""
    session_dir = tmp_path / "sessao-teste"
    metrics_file = _write_run(tmp_path)
    _record_run(tmp_path, metrics_file)
    metrics_file.write_text(json.dumps({"metrics": {"r2": 0.99}}))
    events = MagicMock()
    monkeypatch.setattr("src.telemetry.get_telemetry", lambda: events)
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub())
    assert _nodes(store, "Resultado") == [] and len(_nodes(store, "Experimento")) == 1
    assert events.record_agent_event.call_args.kwargs["event_type"] == "proveniencia_inconsistente"


def test_termino_pendente_adia_a_ingestao(tmp_path, store, ctx):
    session_dir = tmp_path / "sessao-teste"
    metrics_file = _write_run(tmp_path)
    ledger = get_ledger()
    began = ledger.begin(project_id="proj", session_id="sessao-teste", subtask_id="sub-1", task_name="treinar",
                         body=inicio(), output_dir=tmp_path)
    ledger.store.unavailable = True
    ledger.finish(exec_id=began.exec_id, chain_id=began.chain_id, session_id="sessao-teste", subtask_id="sub-1",
                  task_name="treinar", body=termino(began.record.record_hash, hash_metrics=sha256_file(metrics_file)),
                  output_dir=tmp_path)
    ingest_session_start(store, ctx)
    with pytest.raises(ProvenancePending):
        ingest_subtask(store, ctx, session_dir, _sub())
    assert _nodes(store, "Experimento") == []


def test_sem_registro_a_ingestao_segue_pelos_arquivos(tmp_path, store, ctx):
    session_dir = tmp_path / "sessao-teste"
    _write_run(tmp_path)
    ingest_session_start(store, ctx)
    ingest_subtask(store, ctx, session_dir, _sub())
    (exp,) = _nodes(store, "Experimento")
    assert "exec_id" not in exp.properties and exp.properties["seed"] == 42
