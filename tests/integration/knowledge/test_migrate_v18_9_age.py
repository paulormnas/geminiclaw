"""Remoção das propriedades do veredito no Apache AGE real (``scripts/migrate_v18_9_result_records.py``).

Pulado quando não há AGE de teste acessível. Usa ``projeto_id`` único e restringe a remoção a ele, sem tocar nos demais
projetos do grafo; limpa só o que criou.
"""

from __future__ import annotations

import json
import uuid

import pytest

from scripts.migrate_v18_9_result_records import remove_legacy_properties
from src import config
from src.knowledge.graph_store import AgeGraphStore
from tests.support.curator_graph import ORQ, CuratorGraph

pytestmark = pytest.mark.integration


def _cypher(sql_body: str, pid: str) -> list:
    import psycopg

    graph = config.KNOWLEDGE_GRAPH_NAME
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("LOAD 'age'")
        conn.execute('SET search_path = ag_catalog, "$user", public')
        return conn.execute(
            f"SELECT * FROM cypher('{graph}', $$ {sql_body} $$, %s::agtype) AS (r agtype)", (json.dumps({"pid": pid}),)
        ).fetchall()


def _cleanup(pid: str) -> None:
    import psycopg

    ids = [r[0].strip('"') for r in _cypher("MATCH (n) WHERE n.projeto_id = $pid RETURN n.id", pid)]
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("LOAD 'age'")
        conn.execute('SET search_path = ag_catalog, "$user", public')
        if ids:
            conn.execute("DELETE FROM knowledge_audit WHERE node_id = ANY(%s)", (ids,))
        conn.execute(
            f"SELECT * FROM cypher('{config.KNOWLEDGE_GRAPH_NAME}', $$ MATCH (n) WHERE n.projeto_id = $pid "
            "DETACH DELETE n $$, %s::agtype) AS (r agtype)",
            (json.dumps({"pid": pid}),),
        )


def test_remove_as_propriedades_do_veredito_so_do_projeto(age_store: AgeGraphStore):
    pid = f"proj-{uuid.uuid4().hex[:8]}"
    try:
        graph = CuratorGraph(age_store, pid).setup_project()
        hip, abordagem = graph.hipotese(), graph.abordagem()
        age_store.create_edge(abordagem, "FUNCIONOU_PARA", graph.problema,
                              {"metrica": "r2", "melhor_valor": 0.9, "n_exp": 2}, actor=ORQ)
        # propriedades legadas, gravadas por fora do schema (como nos grafos anteriores ao ADR 026)
        _cypher("MATCH (n:Hipotese) WHERE n.projeto_id = $pid SET n.veredito = 0.4, n.suporte = 0.7", pid)
        _cypher("MATCH (a:Abordagem)-[r:FUNCIONOU_PARA]->() WHERE a.projeto_id = $pid SET r.descoberta_id = 'x'", pid)

        nos, arestas = remove_legacy_properties(age_store, apply=False, project_id=pid)
        assert (nos, arestas) == (1, 1)
        assert age_store.get_node(hip).properties.get("veredito") == 0.4  # a contagem não grava

        remove_legacy_properties(age_store, apply=True, project_id=pid)

        assert "veredito" not in age_store.get_node(hip).properties
        assert "suporte" not in age_store.get_node(hip).properties
        assert remove_legacy_properties(age_store, apply=False, project_id=pid) == (0, 0)
    finally:
        _cleanup(pid)
