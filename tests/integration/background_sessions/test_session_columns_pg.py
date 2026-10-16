"""Colunas do processo, reafirmação e purga da sessão contra o PostgreSQL real (v18.7-background-sessions, 1.1-1.4)."""

from __future__ import annotations

import datetime

import psycopg
import pytest

from src.session.manager import SessionManager
from tests.support.pg import MIGRATIONS_V187, pg_db, skip_if_no_postgres, temp_database_url  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.timeout(15), skip_if_no_postgres]

NOW = datetime.datetime.now(datetime.timezone.utc)


def _age(manager: SessionManager, session_id: str, days: float) -> None:
    from src.db import get_connection

    with get_connection() as conn:
        conn.execute(
            "UPDATE agent_sessions SET updated_at = %s WHERE id = %s",
            ((NOW - datetime.timedelta(days=days)).isoformat(), session_id),
        )


def test_migracao_aplicada_duas_vezes(temp_database_url):  # noqa: F811
    """Scenario: a migração é idempotente e aditiva (init_db.sql já a aplicou uma vez)."""
    with psycopg.connect(temp_database_url, autocommit=True) as conn:
        for migration in MIGRATIONS_V187:
            conn.execute(migration.read_text(encoding="utf-8"))
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'agent_sessions'"
        ).fetchall()}
    assert {"pid", "host", "process_started_at", "loop_beat_at", "terminal_id", "alias", "resumo"} <= cols


def test_registro_do_processo_e_batimento_com_sinal_do_laco(pg_db):  # noqa: F811
    manager = SessionManager()
    session = manager.create("orchestrator", "sess-proc")
    assert manager.register_process(
        session.id, pid=4242, host="maquina", process_started_at=NOW.isoformat(), alias="proj-01",
        resumo="Comparar classificadores", terminal_id="t1",
    )
    got = manager.get(session.id)
    assert (got.pid, got.host, got.alias, got.resumo, got.terminal_id) == (
        4242, "maquina", "proj-01", "Comparar classificadores", "t1"
    )
    assert got.loop_beat_at is not None
    beat = (NOW + datetime.timedelta(seconds=5)).isoformat()
    assert manager.heartbeat(session.id, loop_beat_at=beat) is True
    assert manager.get(session.id).loop_beat_at.startswith(beat[:19])
    assert manager.find_by_alias("proj-01").id == session.id
    assert manager.aliases_in_use("proj") == ["proj-01"]


def test_reassert_active_recusa_sessao_continuada(pg_db):  # noqa: F811
    """Scenario: sessão continuada não volta a ``active`` (caso 11 do ADR 023)."""
    manager = SessionManager()
    a = manager.create("orchestrator", "sess-a")
    manager.update(a.id, status="interrompida", payload={"motivo_parada": "interrompida"})
    assert manager.reassert_active(a.id) is True
    manager.update(a.id, status="interrompida", payload={"continued_by": "sess-b"})
    assert manager.reassert_active(a.id) is False
    assert manager.get(a.id).status == "interrompida"


def test_purga_so_remove_terminadas_antigas_fora_de_cadeia_viva(pg_db):  # noqa: F811
    """Scenario: a retenção remove sessões terminadas e antigas; nunca as por terminar nem a cadeia delas."""
    manager = SessionManager()
    for sid in ("velha", "recente", "ativa", "interrompida", "raiz", "meio", "folha"):
        manager.create("orchestrator", sid)
    manager.update("velha", status="closed")
    manager.update("recente", status="closed")
    manager.update("ativa", status="active")
    manager.update("interrompida", status="interrompida")
    manager.update("raiz", status="closed", payload={"continued_by": "meio"})
    manager.update("meio", status="closed", payload={"continues_session_id": "raiz", "continued_by": "folha"})
    manager.update("folha", status="interrompida", payload={"continues_session_id": "meio"})
    for sid in ("velha", "ativa", "interrompida", "raiz", "meio", "folha"):
        _age(manager, sid, 90)
    assert manager.purge_finished(30) == 1
    assert manager.get("velha") is None
    for sid in ("recente", "ativa", "interrompida", "raiz", "meio", "folha"):
        assert manager.get(sid) is not None, sid


def test_purga_desligada_com_zero_dias(pg_db):  # noqa: F811
    manager = SessionManager()
    manager.create("orchestrator", "antiga")
    manager.update("antiga", status="closed")
    _age(manager, "antiga", 400)
    assert manager.purge_finished(0) == 0 and manager.get("antiga") is not None
