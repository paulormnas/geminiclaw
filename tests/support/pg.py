"""PostgreSQL real de teste: um banco temporário por execução, com o schema do projeto (v18.7-background-sessions, 3.4).

Cria ``gc_test_<hex>`` no servidor de ``DATABASE_URL``, aplica ``scripts/init_db.sql`` e as migrações ``v18_7_*`` e
apaga o banco no fim. O pool de ``src.db`` aponta para ele durante o teste. Pulado sem ``DATABASE_URL`` acessível.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Tabelas que os testes de v18.7 escrevem; as que ainda não existem no schema são ignoradas.
MUTABLE_TABLES = ("agent_sessions", "terminal_presence", "gate_requests", "session_inbox", "session_events")
MIGRATIONS_V187 = sorted((ROOT / "scripts" / "migrations").glob("v18_7_*.sql"))


def postgres_available() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql://"):
        return False
    try:
        import psycopg

        psycopg.connect(url, connect_timeout=3).close()
        return True
    except Exception:  # noqa: BLE001 - sem banco, o teste é pulado
        return False


skip_if_no_postgres = pytest.mark.skipif(not postgres_available(), reason="PostgreSQL não disponível (DATABASE_URL).")


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/" + name, parts.query, parts.fragment))


@pytest.fixture(scope="session")
def temp_database_url() -> Iterator[str]:
    import psycopg

    admin = os.environ["DATABASE_URL"]
    name = f"gc_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = _with_database(admin, name)
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute((ROOT / "scripts" / "init_db.sql").read_text(encoding="utf-8"))
            for migration in MIGRATIONS_V187:
                conn.execute(migration.read_text(encoding="utf-8"))
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def pg_db(temp_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Aponta ``src.db`` (pool e ``DATABASE_URL``) para o banco temporário, limpo a cada teste."""
    import psycopg

    from src import config, db

    with psycopg.connect(temp_database_url, autocommit=True) as conn:
        existing = [
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                "AND table_name = ANY(%s)",
                (list(MUTABLE_TABLES),),
            ).fetchall()
        ]
        if existing:
            conn.execute("TRUNCATE " + ", ".join(existing) + " RESTART IDENTITY")
    db.close_pool()
    monkeypatch.setattr(config, "DATABASE_URL", temp_database_url)
    try:
        yield temp_database_url
    finally:
        db.close_pool()
