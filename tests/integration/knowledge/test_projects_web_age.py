"""``v18.10-web-skeleton`` tarefa 1.5: criar, editar, arquivar e listar projetos com Apache AGE real.

Usa um grafo temporário (nome único), criado e descartado pelo teste, sem tocar o grafo do projeto.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from src import config
from src.knowledge import projects
from src.knowledge.graph_store import AgeGraphStore

pytestmark = pytest.mark.integration


@pytest.fixture
def temp_store():
    from scripts import migrate_v17_knowledge as migration

    name = f"knowledge_t_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        migration.apply_static_sql(conn, name)
        migration.create_node_labels(conn, name)
        migration.create_relation_labels(conn, name)
        yield AgeGraphStore(name, reader_conninfo="", read_timeout_ms=config.KNOWLEDGE_READ_TIMEOUT_MS)
        conn.execute("LOAD 'age'")
        conn.execute('SET search_path = ag_catalog, "$user", public')
        conn.execute("SELECT drop_graph(%s, true)", (name,))


def test_ciclo_de_vida_do_projeto_com_age_real(temp_store) -> None:
    pid = projects.create_project(temp_store, "Íris", "Classificar espécies")
    detail = projects.update_project(temp_store, pid, titulo="Íris 2", status="concluido")
    assert (detail.titulo, detail.status) == ("Íris 2", "concluido")
    assert [p.status for p in projects.list_projects(temp_store, "concluido")] == ["concluido"]

    archived = projects.update_project(temp_store, pid, status="arquivado")
    assert archived.status == "arquivado"
    assert projects.list_projects(temp_store, "ativo") == []
    assert [p.projeto_id for p in projects.list_projects(temp_store, "arquivado")] == [pid]

    node = temp_store.find_nodes("Projeto", {"projeto_id": pid}, limit=1)[0]
    history = temp_store.audit_history(node.id)
    assert history and all(entry["actor"] for entry in history)
    assert any("arquivado" in str(entry["changes"]) for entry in history)
