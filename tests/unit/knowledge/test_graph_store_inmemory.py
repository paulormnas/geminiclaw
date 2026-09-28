"""Testes unitários para InMemoryGraphStore (src/knowledge/graph_store.py).

Exercita a interface GraphStore ponta a ponta sem depender de banco de
dados, incluindo os cenários de segurança e auditoria de
`openspec/changes/v17-graph-store/specs/knowledge-graph/spec.md`
(tarefas 4.1 e 4.2 de tasks.md).
"""

import pytest

from src.knowledge.errors import (
    DisallowedRelationError,
    GraphStoreError,
    ImmutableFieldError,
    InvalidEnumValueError,
    NodeNotFoundError,
    ReadOnlyQueryViolation,
)
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.provenance import Actor

ORQUESTRADOR = Actor(kind="orquestrador")
PESQUISADOR = Actor(kind="pesquisador")
CURATOR = Actor(kind="agente", role="curator", model="qwen3:8b")


def _new_projeto(store: InMemoryGraphStore) -> str:
    return store.create_node(
        "Projeto",
        {"titulo": "Projeto X", "objetivo": "Testar", "status": "ativo", "projeto_id": "self", "sessao_id": "s1"},
        actor=ORQUESTRADOR,
    )


@pytest.mark.unit
class TestCreateNode:
    def test_cria_no_e_retorna_id(self):
        store = InMemoryGraphStore()
        node_id = _new_projeto(store)
        assert node_id
        node = store.get_node(node_id)
        assert node is not None
        assert node.label == "Projeto"
        assert node.properties["titulo"] == "Projeto X"

    def test_valor_malicioso_gravado_literalmente(self):
        """Scenario 'Valor malicioso': o texto é gravado como está, sem efeito colateral."""
        store = InMemoryGraphStore()
        payload = "x'}) MATCH (n) DETACH DELETE n //"
        node_id = store.create_node(
            "Projeto",
            {"titulo": payload, "objetivo": "y", "status": "ativo", "projeto_id": "p1", "sessao_id": "s1"},
            actor=ORQUESTRADOR,
        )
        node = store.get_node(node_id)
        assert node.properties["titulo"] == payload
        # Nenhum outro nó foi afetado.
        assert len(store._nodes) == 1  # noqa: SLF001 - acesso interno legítimo em teste unitário


@pytest.mark.unit
class TestUpdateNode:
    def test_atualiza_campo_mutavel(self):
        store = InMemoryGraphStore()
        node_id = store.create_node(
            "Descoberta",
            {
                "tipo": "funciona",
                "enunciado": "x",
                "n_evidencias": 1,
                "status": "ativa",
                "projeto_id": "p1",
                "sessao_id": "s1",
                "justificativa_criacao": "motivo",
                "nos_consultados": [],
            },
            actor=CURATOR,
        )
        store.update_node(node_id, {"status": "contestada"}, actor=PESQUISADOR)
        assert store.get_node(node_id).properties["status"] == "contestada"

    def test_campo_imutavel_recusado(self):
        store = InMemoryGraphStore()
        node_id = _new_projeto(store)
        with pytest.raises(ImmutableFieldError):
            store.update_node(node_id, {"id": "outro"}, actor=ORQUESTRADOR)

    def test_no_inexistente_levanta_erro(self):
        store = InMemoryGraphStore()
        with pytest.raises(NodeNotFoundError):
            store.update_node("nao-existe", {"status": "ativo"}, actor=ORQUESTRADOR)

    def test_auditoria_registra_mudanca(self):
        """Scenario 'Auditoria de alterações': update_node grava em knowledge_audit."""
        store = InMemoryGraphStore()
        node_id = store.create_node(
            "Descoberta",
            {
                "tipo": "funciona",
                "enunciado": "x",
                "n_evidencias": 1,
                "status": "ativa",
                "projeto_id": "p1",
                "sessao_id": "s1",
                "justificativa_criacao": "motivo",
                "nos_consultados": [],
            },
            actor=CURATOR,
        )
        store.update_node(node_id, {"status": "contestada"}, actor=PESQUISADOR)

        assert len(store.audit_log) == 1
        entry = store.audit_log[0]
        assert entry["node_id"] == node_id
        assert entry["actor"] == "pesquisador"
        assert entry["changes"] == {"status": "contestada"}
        assert "timestamp" in entry


@pytest.mark.unit
class TestCreateEdge:
    def test_cria_aresta_valida(self):
        store = InMemoryGraphStore()
        problema_id = store.create_node(
            "Problema",
            {"titulo": "P", "resumo": "R", "status": "rascunho", "projeto_id": "p1", "sessao_id": "s1"},
            actor=ORQUESTRADOR,
        )
        hipotese_id = store.create_node(
            "Hipotese",
            {
                "enunciado": "E", "justificativa": "J", "status": "proposta", "origem": "pesquisador",
                "projeto_id": "p1", "sessao_id": "s1",
            },
            actor=PESQUISADOR,
        )
        store.create_edge(hipotese_id, "SOBRE", problema_id, {}, actor=PESQUISADOR)
        assert len(store._edges) == 1  # noqa: SLF001

    def test_relacao_nao_permitida_e_recusada(self):
        store = InMemoryGraphStore()
        resultado_id = store.create_node(
            "Resultado",
            {
                "nome_original": "acc", "valor": 0.9, "status_validacao": "validado",
                "caminho_metrics": "/tmp/m.json", "projeto_id": "p1", "sessao_id": "s1",
            },
            actor=ORQUESTRADOR,
        )
        problema_id = store.create_node(
            "Problema",
            {"titulo": "P", "resumo": "R", "status": "rascunho", "projeto_id": "p1", "sessao_id": "s1"},
            actor=ORQUESTRADOR,
        )
        with pytest.raises(DisallowedRelationError):
            store.create_edge(resultado_id, "FUNCIONOU_PARA", problema_id, {}, actor=ORQUESTRADOR)

    def test_no_origem_inexistente(self):
        store = InMemoryGraphStore()
        problema_id = store.create_node(
            "Problema",
            {"titulo": "P", "resumo": "R", "status": "rascunho", "projeto_id": "p1", "sessao_id": "s1"},
            actor=ORQUESTRADOR,
        )
        with pytest.raises(NodeNotFoundError):
            store.create_edge("nao-existe", "SOBRE", problema_id, {}, actor=ORQUESTRADOR)


@pytest.mark.unit
class TestSetEdgeStatus:
    def test_altera_status(self):
        store = InMemoryGraphStore()
        problema_id = store.create_node(
            "Problema",
            {"titulo": "P", "resumo": "R", "status": "rascunho", "projeto_id": "p1", "sessao_id": "s1"},
            actor=ORQUESTRADOR,
        )
        hipotese_id = store.create_node(
            "Hipotese",
            {
                "enunciado": "E", "justificativa": "J", "status": "proposta", "origem": "pesquisador",
                "projeto_id": "p1", "sessao_id": "s1",
            },
            actor=PESQUISADOR,
        )
        store.create_edge(hipotese_id, "SOBRE", problema_id, {}, actor=PESQUISADOR)
        store.set_edge_status(hipotese_id, "SOBRE", problema_id, "contestada", actor=PESQUISADOR)

        edge = store._edges[0]  # noqa: SLF001
        assert edge.properties["status"] == "contestada"

    def test_status_invalido_recusado(self):
        store = InMemoryGraphStore()
        with pytest.raises(InvalidEnumValueError):
            store.set_edge_status("a", "SOBRE", "b", "invalido", actor=ORQUESTRADOR)

    def test_aresta_inexistente_levanta_erro(self):
        store = InMemoryGraphStore()
        with pytest.raises(GraphStoreError):
            store.set_edge_status("a", "SOBRE", "b", "contestada", actor=ORQUESTRADOR)


@pytest.mark.unit
class TestFindNeighborsProject:
    def _build_graph(self, store: InMemoryGraphStore) -> tuple[str, str, str]:
        projeto_id = store.create_node(
            "Projeto",
            {"titulo": "P", "objetivo": "O", "status": "ativo", "projeto_id": "self", "sessao_id": "s1"},
            actor=ORQUESTRADOR,
        )
        problema_id = store.create_node(
            "Problema",
            {"titulo": "Pr", "resumo": "R", "status": "rascunho", "projeto_id": projeto_id, "sessao_id": "s1"},
            actor=ORQUESTRADOR,
        )
        hipotese_id = store.create_node(
            "Hipotese",
            {
                "enunciado": "E", "justificativa": "J", "status": "proposta", "origem": "pesquisador",
                "projeto_id": projeto_id, "sessao_id": "s1",
            },
            actor=PESQUISADOR,
        )
        store.create_edge(hipotese_id, "SOBRE", problema_id, {}, actor=PESQUISADOR)
        return projeto_id, problema_id, hipotese_id

    def test_find_nodes_por_rotulo_e_filtro(self):
        store = InMemoryGraphStore()
        self._build_graph(store)
        results = store.find_nodes("Problema", {"status": "rascunho"})
        assert len(results) == 1
        assert results[0].label == "Problema"

    def test_neighbors_direcao_out(self):
        store = InMemoryGraphStore()
        _, problema_id, hipotese_id = self._build_graph(store)
        sub = store.neighbors(hipotese_id, rels=["SOBRE"], direction="out", depth=1)
        assert {n.id for n in sub.nodes} == {problema_id}
        assert len(sub.edges) == 1

    def test_neighbors_direcao_in(self):
        store = InMemoryGraphStore()
        _, problema_id, hipotese_id = self._build_graph(store)
        sub = store.neighbors(problema_id, rels=["SOBRE"], direction="in", depth=1)
        assert {n.id for n in sub.nodes} == {hipotese_id}

    def test_neighbors_no_inexistente_retorna_vazio(self):
        store = InMemoryGraphStore()
        sub = store.neighbors("nao-existe", rels=None)
        assert sub.nodes == []
        assert sub.edges == []

    def test_project_subgraph_filtra_por_projeto(self):
        store = InMemoryGraphStore()
        projeto_id, problema_id, hipotese_id = self._build_graph(store)
        sub = store.project_subgraph(projeto_id)
        node_ids = {n.id for n in sub.nodes}
        assert problema_id in node_ids
        assert hipotese_id in node_ids
        assert len(sub.edges) == 1

    def test_project_subgraph_filtra_por_rotulo(self):
        store = InMemoryGraphStore()
        projeto_id, problema_id, hipotese_id = self._build_graph(store)
        sub = store.project_subgraph(projeto_id, labels=["Problema"])
        assert {n.id for n in sub.nodes} == {problema_id}


@pytest.mark.unit
class TestReadQuery:
    def test_recusa_create(self):
        store = InMemoryGraphStore()
        with pytest.raises(ReadOnlyQueryViolation):
            store.read_query("CREATE (n:Projeto {titulo: 'x'})", {})

    def test_aceita_match_retorna_vazio(self):
        """InMemoryGraphStore não tem motor Cypher real; apenas garante que o filtro passa."""
        store = InMemoryGraphStore()
        result = store.read_query("MATCH (n:Projeto) RETURN n", {})
        assert result == []
