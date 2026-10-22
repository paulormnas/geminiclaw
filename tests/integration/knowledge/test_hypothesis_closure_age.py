"""``v18.6-hypothesis-closure`` tarefa 8.2: sessão simulada com Apache AGE real.

Uma hipótese refutada (resultado negativo ingerido) e outra validada fecham pela **regra de réplicas**. Pulado quando
não há AGE de teste acessível (ver ``conftest.py`` deste diretório). Usa ``projeto_id`` único e remove do grafo e da
auditoria só o que criou (o ``GraphStore`` não apaga; a limpeza usa SQL/Cypher direto, como o módulo vizinho).
"""

from __future__ import annotations

import json
import uuid

import pytest

from src import config
from src.knowledge.graph_store import AgeGraphStore
from tests.support.hypothesis_closure_scenario import run_closure_scenario

pytestmark = pytest.mark.integration


def _cleanup(project_id: str) -> None:
    import psycopg

    graph = config.KNOWLEDGE_GRAPH_NAME
    params = json.dumps({"pid": project_id})
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("LOAD 'age'")
        conn.execute('SET search_path = ag_catalog, "$user", public')
        ids = [
            row[0].strip('"')
            for row in conn.execute(
                f"SELECT * FROM cypher('{graph}', $$ MATCH (n) WHERE n.projeto_id = $pid RETURN n.id $$, %s::agtype) "
                "AS (r agtype)",
                (params,),
            ).fetchall()
        ]
        if ids:
            conn.execute("DELETE FROM knowledge_audit WHERE node_id = ANY(%s)", (ids,))
        conn.execute(
            f"SELECT * FROM cypher('{graph}', $$ MATCH (n) WHERE n.projeto_id = $pid DETACH DELETE n $$, %s::agtype) "
            "AS (r agtype)",
            (params,),
        )


def test_sessao_simulada_fecha_hipoteses_pela_regra_de_replicas(age_store: AgeGraphStore, tmp_path):
    suffix = uuid.uuid4().hex[:8]
    try:
        out = run_closure_scenario(age_store, tmp_path, suffix)
        assert age_store.get_node(out["experiment"]).properties["status"] == "sucesso"
        assert out["changed"][out["refuted"]] == "refutada"
        assert out["changed"][out["validated"]] == "validada"
        assert out["facts"][out["refuted"]].n_atingiu_alvo == 0 < out["facts"][out["validated"]].n_atingiu_alvo
        refuta = age_store.neighbors(out["refuted"], ["REFUTA"], direction="in", depth=1).edges
        assert refuta, "a hipótese refutada deve ter Resultado-REFUTA->Hipotese"
    finally:
        _cleanup(f"proj-{suffix}")
