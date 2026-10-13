"""Reset dos bancos de benchmark contra PostgreSQL (com AGE) e Qdrant reais (v18.6-benchmark-harness, tarefa 1.7).

Cenários "Reset completo", "Dump gravado" e "Dump falha" da spec ``benchmark``, mais a conferência de que o banco recriado
tem as mesmas tabelas de um banco criado pelo ``docker-entrypoint-initdb.d`` (``init_db.sql``).

Segurança: o teste NUNCA toca nos bancos compartilhados. Cria e apaga um banco descartável
(``geminiclaw_bench_it_<hex>``, no mesmo servidor) e usa coleções do Qdrant com nome descartável
(``bench_it_<hex>``), inclusive para a carga do vocabulário (``KNOWLEDGE_COLLECTION`` do subprocesso). Requer:

- ``DATABASE_URL`` apontando para um PostgreSQL com AGE e permissão de ``CREATE DATABASE`` (o do projeto);
- ``BENCHMARK_IT_QDRANT_URL`` (ex.: ``http://localhost:6333``), pois ``QDRANT_URL`` é ``:memory:`` na suíte;
- ``KNOWLEDGE_READER_DATABASE_URL`` e ``KNOWLEDGE_READER_PASSWORD`` (a migração v17 recria o papel somente-leitura).

Sem eles, o módulo é pulado.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from scripts.benchmark import reset_stores
from scripts.benchmark.reset_stores import BenchmarkTarget, ResetError

DIRTY_POINT = 987654321
DEV_URL = os.environ.get("DATABASE_URL", "")
QDRANT_URL = os.environ.get("BENCHMARK_IT_QDRANT_URL", "")


def _available() -> bool:
    if not DEV_URL.startswith("postgresql://") or "test_geminiclaw" in DEV_URL or not QDRANT_URL:
        return False
    if not os.environ.get("KNOWLEDGE_READER_DATABASE_URL") or not os.environ.get("KNOWLEDGE_READER_PASSWORD"):
        return False
    try:
        import psycopg

        psycopg.connect(DEV_URL, connect_timeout=3).close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _available(), reason="PostgreSQL com AGE, Qdrant e variáveis do leitor não disponíveis."),
]


@pytest.fixture
def sandbox_target():
    """Alvo descartável: banco ``geminiclaw_bench_it_<hex>`` e coleção ``bench_it_<hex>`` (apagados ao final)."""
    import psycopg
    from qdrant_client import QdrantClient

    suffix = uuid.uuid4().hex[:8]
    database = f"geminiclaw_bench_it_{suffix}"
    collection = f"bench_it_{suffix}"
    parts = urlsplit(DEV_URL)
    url = urlunsplit(parts._replace(path=f"/{database}"))
    target = BenchmarkTarget(
        database_url=url, qdrant_url=QDRANT_URL, dev_database_url=DEV_URL,
        knowledge_collection=collection, collections=(collection,),
    )
    env = {**os.environ, "KNOWLEDGE_COLLECTION": collection}
    yield target, env
    with psycopg.connect(urlunsplit(parts._replace(path="/postgres")), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    client = QdrantClient(url=QDRANT_URL)
    if collection in {c.name for c in client.get_collections().collections}:
        client.delete_collection(collection)


def _count(url: str, table: str) -> int:
    import psycopg

    with psycopg.connect(url) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _public_tables(url: str) -> set[str]:
    import psycopg

    with psycopg.connect(url) as conn:
        rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
    return {r[0] for r in rows}


def _dirty(target: BenchmarkTarget) -> None:
    """Suja o banco e a coleção: evento, registro de execução, nó extra no grafo e um ponto no Qdrant."""
    import psycopg
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    with psycopg.connect(target.database_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO agent_events (id, execution_id, session_id, agent_id, event_type, timestamp) "
            "VALUES ('e1', 'x', 'x', 'a', 'complete', now())"
        )
        conn.execute("LOAD 'age'")
        conn.execute('SET search_path = ag_catalog, "$user", public')
        conn.execute(
            f"SELECT * FROM cypher('{target.graph_name}', $$ CREATE (:Hipotese {{id: 'sujo'}}) $$) AS (v agtype)"
        )
    client = QdrantClient(url=target.qdrant_url)
    size = 4
    if target.knowledge_collection in {c.name for c in client.get_collections().collections}:
        # A carga do vocabulário já indexa termos na coleção: o ponto sujo usa a mesma dimensão.
        size = client.get_collection(target.knowledge_collection).config.params.vectors.size
    else:
        client.create_collection(target.knowledge_collection, vectors_config=VectorParams(size=4, distance=Distance.COSINE))
    client.upsert(target.knowledge_collection, [PointStruct(id=DIRTY_POINT, vector=[0.1] * size, payload={"k": 1})])


def _graph_nodes(target: BenchmarkTarget) -> int:
    import psycopg

    with psycopg.connect(target.database_url, autocommit=True) as conn:
        conn.execute("LOAD 'age'")
        conn.execute('SET search_path = ag_catalog, "$user", public')
        row = conn.execute(
            f"SELECT * FROM cypher('{target.graph_name}', $$ MATCH (n) RETURN count(n) $$) AS (c agtype)"
        ).fetchone()
    return int(str(row[0]))


def test_reset_completo_dump_gravado_e_tabelas_iguais_ao_initdb(sandbox_target, tmp_path) -> None:
    """Cenários "Reset completo" e "Dump gravado"; tabelas iguais às do banco criado pelo ``init_db.sql``."""
    from qdrant_client import QdrantClient

    target, env = sandbox_target
    first = reset_stores.reset_stores(target, archive_dir=tmp_path / "r0", dump=False, base_env=env)
    vocabulary_nodes = _graph_nodes(target)
    assert first.vocabulary and vocabulary_nodes > 0 and "init_db.sql" in first.migrations_applied
    _dirty(target)
    assert _graph_nodes(target) == vocabulary_nodes + 1 and _count(target.database_url, "agent_events") == 1

    report = reset_stores.reset_stores(target, archive_dir=tmp_path / "r1", base_env=env)

    assert _graph_nodes(target) == vocabulary_nodes  # só o vocabulário
    assert _count(target.database_url, "execution_records") == 0 and _count(target.database_url, "agent_events") == 0
    client = QdrantClient(url=target.qdrant_url)
    assert report.dropped_collections == [target.knowledge_collection]
    if target.knowledge_collection in {c.name for c in client.get_collections().collections}:
        assert client.retrieve(target.knowledge_collection, [DIRTY_POINT]) == []  # o ponto sujo não sobreviveu
    assert report.dump_path and Path(report.dump_path).is_file() and Path(report.dump_path).stat().st_size > 0
    assert Path(report.dump_path).parent == tmp_path / "r1" / "pre_reset"
    assert report.qdrant_snapshots and all(Path(p).is_file() for p in report.qdrant_snapshots)
    assert reset_stores._verify(target) == []

    # Banco criado só pelo init_db.sql (como o docker-entrypoint-initdb.d): mesmas tabelas públicas.
    import psycopg

    reference = f"{urlsplit(target.database_url).path.lstrip('/')}_ref"
    admin = urlunsplit(urlsplit(DEV_URL)._replace(path="/postgres"))
    ref_url = urlunsplit(urlsplit(DEV_URL)._replace(path=f"/{reference}"))
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{reference}"')
    try:
        with psycopg.connect(ref_url, autocommit=True) as conn:
            conn.execute(reset_stores.INIT_SQL.read_text(encoding="utf-8"))
        assert _public_tables(ref_url) <= _public_tables(target.database_url)
        extra = _public_tables(target.database_url) - _public_tables(ref_url)
        assert extra <= {"knowledge_audit"}, f"tabelas além do init_db.sql: {extra}"
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{reference}" WITH (FORCE)')


def test_dump_falha_nao_apaga_o_banco(sandbox_target, tmp_path, monkeypatch) -> None:
    """Cenário "Dump falha": sem ``pg_dump`` (host e container) o reset termina com erro e o banco continua."""
    target, env = sandbox_target
    reset_stores.reset_stores(target, archive_dir=tmp_path / "r0", dump=False, base_env=env)
    _dirty(target)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ResetError, match="pg_dump"):
        reset_stores.reset_stores(target, archive_dir=tmp_path / "r1", base_env=env)
    assert _count(target.database_url, "agent_events") == 1 and _graph_nodes(target) > 0
