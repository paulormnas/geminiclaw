"""Testes unitários para AgeGraphStore (src/knowledge/graph_store.py) sem banco real.

Usa mocks para validar: (1) que a validação de schema roda ANTES de qualquer
chamada ao banco (rótulo/relação inválidos nunca chegam a montar SQL); (2)
que valores de propriedade nunca são interpolados no texto Cypher — viajam
sempre pelo parâmetro `agtype` (tarefa 4.2 de tasks.md, Scenario "Valor
malicioso"); (3) a decodificação de valores `agtype`.

Testes que exigem um Apache AGE real (criar nó, aresta, neighbors,
project_subgraph fim-a-fim) estão em `tests/integration/knowledge/`.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.knowledge.errors import (
    DisallowedRelationError,
    InvalidEnumValueError,
    NodeNotFoundError,
    UnknownLabelError,
    UnknownPropertyError,
)
from src.knowledge.graph_store import AgeGraphStore, Node
from src.knowledge.provenance import Actor

ORQUESTRADOR = Actor(kind="orquestrador")


def _make_store() -> AgeGraphStore:
    return AgeGraphStore("knowledge", reader_conninfo="postgresql://reader@localhost/db", read_timeout_ms=5000)


@pytest.mark.unit
class TestDecodeAgtype:
    def test_decodifica_vertice_com_sufixo(self):
        store = _make_store()
        raw = '{"id": 1, "label": "Projeto", "properties": {"id": "abc", "titulo": "X"}}::vertex'
        decoded = store._decode_agtype(raw)  # noqa: SLF001
        assert decoded["label"] == "Projeto"
        assert decoded["properties"]["titulo"] == "X"

    def test_decodifica_valor_none(self):
        store = _make_store()
        assert store._decode_agtype(None) is None  # noqa: SLF001

    def test_decodifica_texto_simples_sem_sufixo_json(self):
        store = _make_store()
        assert store._decode_agtype("42") == 42  # noqa: SLF001


@pytest.mark.unit
class TestCreateNodeValidatesBeforeDb:
    def test_rotulo_desconhecido_nao_chama_banco(self):
        store = _make_store()
        with patch.object(store, "_run_cypher") as mock_run:
            with pytest.raises(UnknownLabelError):
                store.create_node(
                    "Pessoa",
                    {"projeto_id": "p1", "sessao_id": "s1"},
                    actor=ORQUESTRADOR,
                )
        mock_run.assert_not_called()

    def test_valor_malicioso_vai_apenas_no_parametro(self):
        """O valor malicioso nunca aparece no texto do corpo Cypher, só no dict de params."""
        store = _make_store()
        payload = "x'}) MATCH (n) DETACH DELETE n //"
        with patch.object(store, "_run_cypher", return_value=[]) as mock_run:
            store.create_node(
                "Projeto",
                {"titulo": payload, "objetivo": "y", "status": "ativo", "projeto_id": "p1", "sessao_id": "s1"},
                actor=ORQUESTRADOR,
            )
        cypher_body, params = mock_run.call_args[0]
        assert payload not in cypher_body
        assert params["props"]["titulo"] == payload


@pytest.mark.unit
class TestFindNodesValidatesBeforeDb:
    """PR #64 review, achado 'Importante': find_nodes interpola as CHAVES de
    ``filters`` como identificadores Cypher (``n.{key} = $filters.{key}``).
    ``validate_node_filter_keys`` deve rodar antes de montar/enviar qualquer
    Cypher, recusando chaves fora do schema do rótulo.
    """

    def test_chave_de_filtro_desconhecida_nao_chama_banco(self):
        store = _make_store()
        with patch.object(store, "_run_cypher") as mock_run:
            with pytest.raises(UnknownPropertyError):
                store.find_nodes("Projeto", {"campo_invalido": 1})
        mock_run.assert_not_called()

    def test_chave_forjada_para_injecao_nao_chama_banco(self):
        """Uma chave de filtro com sintaxe Cypher embutida também é recusada antes do banco."""
        store = _make_store()
        payload = "titulo = 'x' OR 1=1 // "
        with patch.object(store, "_run_cypher") as mock_run:
            with pytest.raises(UnknownPropertyError):
                store.find_nodes("Projeto", {payload: "y"})
        mock_run.assert_not_called()

    def test_filtro_com_chaves_conhecidas_so_interpola_nomes_validos(self):
        """Chaves conhecidas do schema podem compor o corpo Cypher; valores vão só por parâmetro."""
        store = _make_store()
        with patch.object(store, "_run_cypher", return_value=[]) as mock_run:
            store.find_nodes("Projeto", {"status": "ativo"})
        cypher_body, params = mock_run.call_args[0]
        assert "n.status = $filters.status" in cypher_body
        assert params["filters"]["status"] == "ativo"


@pytest.mark.unit
class TestCreateEdgeValidatesBeforeDb:
    def test_relacao_nao_permitida_nao_chama_banco(self):
        store = _make_store()
        resultado = Node(id="r1", label="Resultado", properties={"id": "r1"})
        problema = Node(id="p1", label="Problema", properties={"id": "p1"})
        with patch.object(store, "get_node", side_effect=[resultado, problema]):
            with patch.object(store, "_run_cypher") as mock_run:
                with pytest.raises(DisallowedRelationError):
                    store.create_edge("r1", "FUNCIONOU_PARA", "p1", {}, actor=ORQUESTRADOR)
        mock_run.assert_not_called()

    def test_no_origem_inexistente(self):
        store = _make_store()
        with patch.object(store, "get_node", return_value=None):
            with pytest.raises(NodeNotFoundError):
                store.create_edge("nao-existe", "SOBRE", "p1", {}, actor=ORQUESTRADOR)


@pytest.mark.unit
class TestSetEdgeStatusValidatesBeforeDb:
    def test_status_invalido_nao_chama_banco(self):
        store = _make_store()
        with patch.object(store, "_run_cypher") as mock_run:
            with pytest.raises(InvalidEnumValueError):
                store.set_edge_status("a", "SOBRE", "b", "invalido", actor=ORQUESTRADOR)
        mock_run.assert_not_called()

    def test_relacao_desconhecida_nao_chama_banco(self):
        store = _make_store()
        with patch.object(store, "_run_cypher") as mock_run:
            with pytest.raises(DisallowedRelationError):
                store.set_edge_status("a", "RELACAO_INEXISTENTE", "b", "confirmada", actor=ORQUESTRADOR)
        mock_run.assert_not_called()


@pytest.mark.unit
class TestRunCypherRowsSql:
    def test_sql_declara_colunas_pedidas(self):
        store = _make_store()
        mock_pool_conn = MagicMock()
        mock_pool_conn.execute.return_value.fetchall.return_value = []

        class _CtxMgr:
            def __enter__(self_inner):
                return mock_pool_conn

            def __exit__(self_inner, *exc):
                return False

        with patch.object(store, "_connection", return_value=_CtxMgr()):
            store._run_cypher_rows("MATCH (n) RETURN n", {}, columns=("a", "b"))  # noqa: SLF001

        sql_arg = mock_pool_conn.execute.call_args[0][0]
        assert "a agtype, b agtype" in sql_arg
        assert "knowledge" in sql_arg


@pytest.mark.unit
class TestPropertyMap:
    """O AGE não aceita ``CREATE (n:L $props)``; o mapa vira ``{k: $props.k}``."""

    def test_gera_acessos_ao_parametro_por_chave(self):
        assert AgeGraphStore._property_map("props", ["id", "titulo"]) == "{id: $props.id, titulo: $props.titulo}"  # noqa: SLF001

    @pytest.mark.parametrize("chave", ["a}) DETACH DELETE (n) //", "x y", "a-b", "1a", "", "a.b", "$$"])
    def test_chave_que_nao_e_identificador_e_rejeitada(self, chave):
        with pytest.raises(ValueError):
            AgeGraphStore._property_map("props", ["id", chave])  # noqa: SLF001

    def test_create_node_usa_mapa_de_chaves_e_nao_o_parametro_inteiro(self):
        store = _make_store()
        with patch.object(store, "_run_cypher", return_value=[]) as run:
            store.create_node(
                "Projeto",
                {"titulo": "X", "objetivo": "y", "status": "ativo", "projeto_id": "p1", "sessao_id": "s1"},
                actor=ORQUESTRADOR,
            )
        body = run.call_args.args[0]
        assert "$props.id" in body and "$props.titulo" in body
        assert "$props)" not in body


@pytest.mark.unit
class TestNeighborsSemConsultaDeComprimentoVariavel:
    """O ``*1..N`` do AGE custa ~0,25 s por consulta no Pi 5 (benchmark de 2026-10-12): só saltos simples."""

    @staticmethod
    def _vertex(node_id: str, label: str = "Dominio") -> dict:
        return {"label": label, "properties": {"id": node_id}}

    def _store_with_graph(self, edges: list[tuple[str, str, str]]):
        """Grafo simulado: cada consulta devolve as arestas adjacentes ao ``$id`` pedido."""
        store = _make_store()
        calls: list[str] = []

        def fake_rows(cypher, params, columns):
            calls.append(cypher)
            current = params["id"]
            rows = []
            for src, rel, dst in edges:
                touches = (
                    ("-[rel" in cypher and "]->" in cypher and src == current)
                    or ("<-[rel" in cypher and dst == current)
                    or ("-[rel" in cypher and "]-(x)" in cypher and "<-" not in cypher and current in (src, dst))
                )
                if touches:
                    rows.append({"a": self._vertex(src), "rel": {"label": rel, "properties": {}}, "b": self._vertex(dst)})
            return rows

        store._run_cypher_rows = fake_rows  # type: ignore[method-assign]  # noqa: SLF001
        store._node_from_agtype = lambda v: Node(id=v["properties"]["id"], label=v["label"], properties=v["properties"])  # type: ignore[method-assign]  # noqa: SLF001, E501
        return store, calls

    def test_nenhuma_consulta_usa_comprimento_variavel(self):
        store, calls = self._store_with_graph([("a", "SUBAREA_DE", "b"), ("b", "SUBAREA_DE", "c")])
        store.neighbors("a", ["SUBAREA_DE"], direction="out", depth=3)
        assert calls and not any("*" in c for c in calls)

    def test_profundidade_1_devolve_so_o_primeiro_salto(self):
        store, calls = self._store_with_graph([("a", "SUBAREA_DE", "b"), ("b", "SUBAREA_DE", "c")])
        sub = store.neighbors("a", ["SUBAREA_DE"], direction="out", depth=1)
        assert {(e.src_id, e.dst_id) for e in sub.edges} == {("a", "b")}
        assert {n.id for n in sub.nodes} == {"a", "b"} and len(calls) == 1

    def test_profundidade_3_percorre_em_niveis_e_para_quando_nao_ha_mais_nos(self):
        store, calls = self._store_with_graph([("a", "SUBAREA_DE", "b"), ("b", "SUBAREA_DE", "c")])
        sub = store.neighbors("a", ["SUBAREA_DE"], direction="out", depth=3)
        assert {(e.src_id, e.dst_id) for e in sub.edges} == {("a", "b"), ("b", "c")}
        assert {n.id for n in sub.nodes} == {"a", "b", "c"}
        assert len(calls) == 3  # a, b e c (c sem saída encerra)

    def test_ciclo_nao_repete_consultas(self):
        store, calls = self._store_with_graph([("a", "RELACIONADA_A", "b"), ("b", "RELACIONADA_A", "a")])
        sub = store.neighbors("a", ["RELACIONADA_A"], direction="out", depth=5)
        assert len(sub.edges) == 2 and len(calls) == 2

    def test_sem_vizinhos_devolve_subgrafo_vazio(self):
        store, _ = self._store_with_graph([])
        sub = store.neighbors("a", None, direction="both", depth=2)
        assert sub.nodes == [] and sub.edges == []

    def test_direcao_invalida_e_relacao_fora_do_schema_continuam_recusadas(self):
        store, _ = self._store_with_graph([])
        with pytest.raises(ValueError):
            store.neighbors("a", None, direction="lado")
        with pytest.raises(DisallowedRelationError):
            store.neighbors("a", ["NAO_EXISTE"])
