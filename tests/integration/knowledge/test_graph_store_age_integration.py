"""Testes de integração de ``AgeGraphStore`` contra uma instância real de Apache AGE.

Cobrem a tarefa 4.3 de ``openspec/changes/v17-graph-store/tasks.md``: criar
nó, criar aresta, ``neighbors`` e ``project_subgraph`` fim-a-fim contra o
motor Cypher real — complementam (não duplicam) os testes unitários com
mocks de ``tests/unit/knowledge/test_graph_store_age.py``, que cobrem a
validação/segurança sem depender de banco.

Pulados automaticamente (ver ``conftest.py`` deste diretório) quando não há
uma instância de Apache AGE acessível e migrada.
"""

from __future__ import annotations

import uuid

import pytest

from src.knowledge.graph_store import AgeGraphStore
from src.knowledge.provenance import Actor

ORQUESTRADOR = Actor(kind="orquestrador")
PESQUISADOR = Actor(kind="pesquisador")
CURATOR = Actor(kind="agente", role="curator", model="qwen3:8b")


def _unique(prefix: str) -> str:
    """Gera um identificador único por teste, para isolar dados no grafo compartilhado.

    Como o ``GraphStore`` nunca apaga nada (ADR 015), cada teste usa seu
    próprio ``projeto_id``/``sessao_id`` em vez de limpar o grafo entre
    execuções.
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
class TestCreateAndReadNode:
    def test_cria_no_e_le_de_volta(self, age_store: AgeGraphStore):
        projeto_id = _unique("proj")
        node_id = age_store.create_node(
            "Projeto",
            {
                "titulo": "Integração AGE",
                "objetivo": "Validar store real",
                "status": "ativo",
                "projeto_id": projeto_id,
                "sessao_id": _unique("sess"),
            },
            actor=ORQUESTRADOR,
        )

        node = age_store.get_node(node_id)

        assert node is not None
        assert node.label == "Projeto"
        assert node.id == node_id
        assert node.properties["titulo"] == "Integração AGE"
        assert node.properties["criado_por"] == "orquestrador"

    def test_no_inexistente_retorna_none(self, age_store: AgeGraphStore):
        assert age_store.get_node(str(uuid.uuid4())) is None

    def test_valor_malicioso_gravado_literalmente(self, age_store: AgeGraphStore):
        """Scenario 'Valor malicioso' (spec.md) contra o motor Cypher real, não um mock."""
        projeto_id = _unique("proj")
        payload = "x'}) MATCH (n) DETACH DELETE n //"
        node_id = age_store.create_node(
            "Projeto",
            {
                "titulo": payload,
                "objetivo": "y",
                "status": "ativo",
                "projeto_id": projeto_id,
                "sessao_id": _unique("sess"),
            },
            actor=ORQUESTRADOR,
        )

        node = age_store.get_node(node_id)

        assert node.properties["titulo"] == payload


@pytest.mark.integration
class TestCreateEdgeAndNeighbors:
    def _build_problema_hipotese(self, age_store: AgeGraphStore) -> tuple[str, str, str]:
        projeto_id = _unique("proj")
        sessao_id = _unique("sess")
        problema_id = age_store.create_node(
            "Problema",
            {"titulo": "P", "resumo": "R", "status": "rascunho", "projeto_id": projeto_id, "sessao_id": sessao_id},
            actor=ORQUESTRADOR,
        )
        hipotese_id = age_store.create_node(
            "Hipotese",
            {
                "enunciado": "E",
                "justificativa": "J",
                "status": "proposta",
                "origem": "pesquisador",
                "projeto_id": projeto_id,
                "sessao_id": sessao_id,
            },
            actor=PESQUISADOR,
        )
        age_store.create_edge(hipotese_id, "SOBRE", problema_id, {}, actor=PESQUISADOR)
        return projeto_id, problema_id, hipotese_id

    def test_cria_aresta_e_aparece_em_neighbors_out(self, age_store: AgeGraphStore):
        _, problema_id, hipotese_id = self._build_problema_hipotese(age_store)

        sub = age_store.neighbors(hipotese_id, rels=["SOBRE"], direction="out", depth=1)

        assert problema_id in {n.id for n in sub.nodes}
        assert any(
            e.src_id == hipotese_id and e.dst_id == problema_id and e.rel_type == "SOBRE" for e in sub.edges
        )

    def test_neighbors_direcao_in(self, age_store: AgeGraphStore):
        _, problema_id, hipotese_id = self._build_problema_hipotese(age_store)

        sub = age_store.neighbors(problema_id, rels=["SOBRE"], direction="in", depth=1)

        assert hipotese_id in {n.id for n in sub.nodes}

    def test_project_subgraph_retorna_nos_e_arestas_do_projeto(self, age_store: AgeGraphStore):
        projeto_id, problema_id, hipotese_id = self._build_problema_hipotese(age_store)

        sub = age_store.project_subgraph(projeto_id)
        node_ids = {n.id for n in sub.nodes}

        assert problema_id in node_ids
        assert hipotese_id in node_ids
        assert len(sub.edges) == 1
        assert sub.edges[0].rel_type == "SOBRE"

    def test_project_subgraph_filtra_por_rotulo(self, age_store: AgeGraphStore):
        projeto_id, problema_id, hipotese_id = self._build_problema_hipotese(age_store)

        sub = age_store.project_subgraph(projeto_id, labels=["Problema"])

        assert {n.id for n in sub.nodes} == {problema_id}


@pytest.mark.integration
class TestUpdateNodeAudit:
    def test_update_node_altera_status_e_grava_auditoria(self, age_store: AgeGraphStore):
        projeto_id = _unique("proj")
        sessao_id = _unique("sess")
        descoberta_id = age_store.create_node(
            "Descoberta",
            {
                "tipo": "funciona",
                "enunciado": "x",
                "n_evidencias": 1,
                "status": "ativa",
                "projeto_id": projeto_id,
                "sessao_id": sessao_id,
                "justificativa_criacao": "motivo de teste de integração",
                "nos_consultados": [],
            },
            actor=CURATOR,
        )

        age_store.update_node(descoberta_id, {"status": "contestada"}, actor=PESQUISADOR)

        node = age_store.get_node(descoberta_id)
        assert node.properties["status"] == "contestada"
        # Campos de proveniência preservados (update_node não os altera).
        assert node.properties["criado_por"] == "curator/qwen3:8b"

        from src.db import get_connection

        with get_connection() as conn:
            row = conn.execute(
                'SELECT actor, changes FROM knowledge_audit WHERE node_id = %s ORDER BY id DESC LIMIT 1',
                (descoberta_id,),
            ).fetchone()

        assert row is not None
        assert row["actor"] == "pesquisador"


@pytest.mark.integration
class TestReadQueryReal:
    def test_read_query_le_dados_gravados(self, age_store: AgeGraphStore):
        projeto_id = _unique("proj")
        age_store.create_node(
            "Projeto",
            {
                "titulo": "ReadQuery",
                "objetivo": "O",
                "status": "ativo",
                "projeto_id": projeto_id,
                "sessao_id": _unique("sess"),
            },
            actor=ORQUESTRADOR,
        )

        results = age_store.read_query(
            "MATCH (n:Projeto) WHERE n.projeto_id = $projeto_id RETURN n.titulo",
            {"projeto_id": projeto_id},
        )

        assert len(results) == 1
        assert results[0]["result"] == "ReadQuery"

    def test_read_query_create_e_recusado_pelo_filtro_e_pelo_banco(self, age_store: AgeGraphStore):
        """Scenario 'Tentativa de escrita em consulta livre': recusado ANTES de chegar ao banco.

        O filtro textual de ``read_guard`` já recusa qualquer ``CREATE`` — a
        garantia real (papel ``knowledge_reader`` sem privilégio de escrita,
        mais ``SET TRANSACTION READ ONLY``) é redundante em relação a este
        filtro no caminho feliz, mas seria a defesa que atuaria se o filtro
        textual fosse contornado.
        """
        from src.knowledge.errors import ReadOnlyQueryViolation

        with pytest.raises(ReadOnlyQueryViolation):
            age_store.read_query("CREATE (n:Projeto {titulo: 'nao deveria gravar'})", {})
