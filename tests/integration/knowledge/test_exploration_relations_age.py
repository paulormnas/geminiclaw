"""``v18.7-graph-exploration-relations`` tarefa 4.2: rótulos novos pela migração idempotente, com Apache AGE real.

Usa um grafo temporário (nome único) criado só para o teste, sem tocar o grafo do projeto, e o descarta no fim. Pulado
quando não há AGE de teste acessível (ver ``conftest.py``) ou quando faltam as variáveis do papel de leitura.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from src import config
from src.knowledge import schema
from src.knowledge.graph_store import AgeGraphStore

pytestmark = pytest.mark.integration

NEW_LABELS = ["PREPARA", "REFERENCIA_DE"]


@pytest.fixture
def temp_graph():
    from scripts import migrate_v17_knowledge as migration

    name = f"knowledge_t_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        migration.apply_static_sql(conn, name)
        migration.create_node_labels(conn, name)
        yield migration, conn, name
        conn.execute("LOAD 'age'")
        conn.execute('SET search_path = ag_catalog, "$user", public')
        conn.execute("SELECT drop_graph(%s, true)", (name,))


def _migrate_twice(migration, conn, name, monkeypatch):
    before = frozenset(schema.RELATION_TYPES) - set(NEW_LABELS)
    monkeypatch.setattr(schema, "RELATION_TYPES", before)
    assert set(migration.create_relation_labels(conn, name)) == before  # grafo criado antes desta mudança
    monkeypatch.undo()
    assert migration.create_relation_labels(conn, name) == NEW_LABELS
    assert migration.create_relation_labels(conn, name) == []


def test_migracao_idempotente_cria_os_rotulos_novos(temp_graph, monkeypatch):
    """Scenario: Grafo anterior à V18.7 (a migração roda duas vezes sem duplicar rótulos)."""
    migration, conn, name = temp_graph
    _migrate_twice(migration, conn, name, monkeypatch)


def test_leitor_le_as_arestas_novas_e_nao_grava(temp_graph, monkeypatch):
    """Scenario: Grafo anterior à V18.7 (``knowledge_reader`` lê e não grava; parecer de segurança, item c)."""
    if not config.KNOWLEDGE_READER_DATABASE_URL or not config.KNOWLEDGE_READER_PASSWORD:
        pytest.skip("KNOWLEDGE_READER_DATABASE_URL/KNOWLEDGE_READER_PASSWORD não configuradas")
    migration, conn, name = temp_graph
    _migrate_twice(migration, conn, name, monkeypatch)
    migration.create_reader_role(conn, name)

    store = AgeGraphStore(
        name, reader_conninfo=config.KNOWLEDGE_READER_DATABASE_URL, read_timeout_ms=config.KNOWLEDGE_READ_TIMEOUT_MS
    )
    for label in NEW_LABELS:
        store.read_query(f"MATCH ()-[r:{label}]->() RETURN count(r)", {})  # sem erro de permissão

    with psycopg.connect(config.KNOWLEDGE_READER_DATABASE_URL, autocommit=True) as reader:
        reader.execute("LOAD 'age'")
        reader.execute('SET search_path = ag_catalog, "$user", public')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute(f"SELECT * FROM cypher('{name}', $$ CREATE ()-[:PREPARA]->() $$) AS (r agtype)")
