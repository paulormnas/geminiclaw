"""Integração do registro de execuções contra um PostgreSQL real (v18.5-execution-provenance, tarefas 5.1–5.4).

Escritos e NÃO executados no PR da mudança (sem PostgreSQL neste ambiente). Requerem um PostgreSQL acessível via
``DATABASE_URL``; são pulados automaticamente sem ele. A tabela é somente-acréscimo: cada teste usa um projeto novo
(UUID) e as linhas de teste ficam no banco de teste (a limpeza desativa os gatilhos só dentro da fixture).

Para rodar (com o banco do projeto no ar), selecione o diretório ``tests/integration/provenance`` com o marcador de
integração do pytest.
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

import pytest

MIGRATION = Path(__file__).resolve().parents[3] / "scripts" / "migrations" / "v18_5_001_execution_records.sql"


def _postgres_available() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql://"):
        return False
    try:
        import psycopg

        psycopg.connect(url, connect_timeout=3).close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_available(), reason="PostgreSQL não disponível (suba o banco do projeto)."),
]


@pytest.fixture(scope="module")
def conninfo() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="module", autouse=True)
def migrated(conninfo):
    """Aplica a migração duas vezes: ela é idempotente e aditiva."""
    import psycopg

    sql = MIGRATION.read_text(encoding="utf-8")
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(sql)
        conn.execute(sql)
    yield


@pytest.fixture(autouse=True)
def real_pool():
    import src.db as db_module

    if db_module._pool is not None:
        db_module.close_pool()
    yield
    if db_module._pool is not None:
        db_module.close_pool()


@pytest.fixture
def project(conninfo):
    pid = f"it-{uuid.uuid4()}"
    yield pid
    import psycopg

    with psycopg.connect(conninfo, autocommit=True) as conn:  # remove só as linhas deste teste
        conn.execute("ALTER TABLE execution_records DISABLE TRIGGER USER")
        try:
            conn.execute("DELETE FROM execution_records WHERE project_id = %s", (pid,))
        finally:
            conn.execute("ALTER TABLE execution_records ENABLE TRIGGER USER")


@pytest.fixture
def ledger(tmp_path):
    from src.provenance.ledger import ExecutionLedger
    from src.provenance.store import PostgresStore

    return ExecutionLedger(PostgresStore(), tmp_path / "outputs")


def _run(ledger, project, session="s1", subtask="sub", task="t"):
    from tests.unit.provenance.helpers import inicio, termino

    began = ledger.begin(project_id=project, session_id=session, subtask_id=subtask, task_name=task, body=inicio())
    ledger.finish(
        exec_id=began.exec_id, chain_id=began.chain_id, session_id=session, subtask_id=subtask, task_name=task,
        body=termino(began.record.record_hash, metricas={"r2": "0.8"}),
    )
    return began


def test_gatilhos_recusam_update_delete_e_truncate(conninfo, ledger, project):
    """Tarefa 5.1 / Scenario: Tentativa de alteração."""
    import psycopg

    _run(ledger, project)
    with psycopg.connect(conninfo, autocommit=True) as conn:
        for statement in (
            "UPDATE execution_records SET corpo = '{}'::jsonb WHERE project_id = %s",
            "DELETE FROM execution_records WHERE project_id = %s",
        ):
            with pytest.raises(psycopg.errors.RestrictViolation):
                conn.execute(statement, (project,))
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute("TRUNCATE execution_records")
    assert len(ledger.store.records(project)) == 2


def test_ida_e_volta_pelo_jsonb_preserva_o_hash(ledger, project):
    """Tarefa 5.2 / Scenario: Ida e volta pelo banco."""
    _run(ledger, project)
    for record in ledger.store.records(project):
        assert record.recompute_hash() == record.record_hash


def test_oito_execucoes_em_duas_sessoes_sem_bifurcacao(ledger, project):
    """Tarefa 5.3 / Scenario: Subtarefas paralelas — seq 1..16 e ``verify`` íntegro."""
    from src.provenance.verify import verify_project

    threads = [
        threading.Thread(target=_run, args=(ledger, project, f"s{i % 2}", f"sub{i}", f"t{i}")) for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    records = ledger.store.records(project)
    assert [r.seq for r in records] == list(range(1, 17))
    assert verify_project(ledger.store, project, ledger.output_dir).integra


def test_banco_indisponivel_no_inicio_nao_cria_container(monkeypatch, tmp_path):
    """Tarefa 5.4: com o banco fora do ar, ``begin`` falha e a skill não chama o sandbox."""
    from src.provenance.errors import ProvenanceUnavailable
    from src.provenance.ledger import ExecutionLedger
    from src.provenance.store import PostgresStore

    def _no_database():
        raise OSError("sem banco")

    monkeypatch.setattr("src.db.get_connection", _no_database)
    book = ExecutionLedger(PostgresStore(), tmp_path)
    with pytest.raises(ProvenanceUnavailable):
        book.begin(project_id="p", session_id="s", subtask_id=None, task_name="t", body={})


def test_registros_por_sessao_e_subtarefa(ledger, project):
    began = _run(ledger, project, session="sx", subtask="sub-x")
    assert {r.exec_id for r in ledger.store.by_session("sx")} >= {began.exec_id}
    assert project in ledger.store.projects_of_session("sx")
    assert ledger.derive_experiment_fields("sub-x").exec_id == began.exec_id
    assert ledger.store.at(project, 1).tipo == "inicio"


def test_tabela_ausente_vira_erro_com_instrucao_de_migracao():
    import psycopg

    from src.provenance.errors import ProvenanceUnavailable
    from src.provenance.store import PostgresStore

    error = PostgresStore._unavailable(psycopg.errors.UndefinedTable("x"))  # noqa: SLF001
    assert isinstance(error, ProvenanceUnavailable) and "migrate_v18_5_provenance" in str(error)
