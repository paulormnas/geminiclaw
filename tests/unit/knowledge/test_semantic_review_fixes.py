"""Correções da revisão do PR #100 (I1–I5, S1–S3): histórico da fila, paginação, coleção própria,
filtros de status/visibilidade, ligação à factory e calibração com amostra mínima."""

from unittest.mock import patch

import pytest
from qdrant_client.models import PointStruct

from src import config
from src.knowledge import factory
from src.knowledge.calibration import suggest_adjustments
from src.knowledge.graph_store import AgeGraphStore, InMemoryGraphStore
from src.knowledge.indexed_store import IndexedGraphStore
from src.knowledge.semantic_index import ForeignCollectionError, IndexDimensionError, SemanticIndex
from src.knowledge.semantic_runtime import SemanticRuntime, run_knowledge_command
from src.knowledge.similarity_queue import (
    BandRate,
    Candidate,
    InMemorySimilarityQueue,
    PostgresSimilarityQueue,
)
from tests.support.controlled_embedding_provider import ControlledEmbeddingProvider, pair_vectors
from tests.unit.knowledge.conftest import DIM, ORQ
from tests.unit.knowledge.test_similarity_queue_storage import _cand, _FakeConn


def _vec(env, marker, axis=0, cosine=1.0, second=False):
    a, b = pair_vectors(DIM, axis, cosine)
    env.provider.vectors[marker] = b if second else a


@pytest.mark.unit
class TestI1HistoricoDaFila:
    def test_pendente_antigo_vira_historico_quando_o_texto_muda(self):
        """Scenario: Par já avaliado (pendente antigo vira histórico)"""
        queue = InMemorySimilarityQueue()
        queue.enqueue(_cand(text_hash_a="v1"))
        assert queue.enqueue(_cand(text_hash_a="v2")) is True
        pend = queue.next_batch(10)
        assert [i.candidate.text_hash_a for i in pend] == ["v2"]
        assert queue.pending_count() == 1
        historico = [i for i in queue._items.values() if i.status == "descartado"]  # noqa: SLF001
        assert historico[0].revisado_por == "sistema" and historico[0].motivo == "texto alterado"

    def test_historico_automatico_nao_entra_na_calibracao(self):
        queue = InMemorySimilarityQueue()
        queue.enqueue(_cand(score=0.65, text_hash_a="v1"))
        queue.enqueue(_cand(score=0.65, text_hash_a="v2"))
        assert queue.confirmation_rate(30) == []

    def test_postgres_arquiva_pendentes_antigos_ao_inserir_novo(self):
        from contextlib import contextmanager

        conn = _FakeConn([[{"inserido": True}], []])

        @contextmanager
        def factory_():
            yield conn

        PostgresSimilarityQueue(factory_).enqueue(_cand())
        sql, params = conn.calls[1]
        assert "SET status = 'descartado'" in sql and "status = 'pendente'" in sql
        assert params[0] == "sistema" and params[1] == "texto alterado"

    def test_atualizacao_do_texto_no_fluxo_completo(self, env):
        _vec(env, "nome: par0a", 0, 0.93)
        _vec(env, "nome: par0b", 0, 0.93, second=True)
        _vec(env, "nome: par0c", 0, 0.93, second=True)
        env.make("Abordagem", nome="par0a")
        b = env.make("Abordagem", nome="par0b")
        env.store.update_node(b, {"nome": "par0c"}, actor=ORQ)
        assert env.queue.pending_count() == 1


@pytest.mark.unit
class TestI2ReconcilePaginado:
    def test_reconcile_le_o_grafo_em_paginas_limitadas(self, env, monkeypatch):
        monkeypatch.setattr(config, "SIM_RECONCILE_BATCH_SIZE", 3)
        for i in range(10):
            env.provider.vectors[f"titulo: Q{i}x"] = pair_vectors(DIM, i % 8, 1.0)[0]
        ids = [env.make("Problema", titulo=f"Q{i}x") for i in range(10)]
        for node_id in ids:  # força tudo a divergir
            env.client.set_payload(env.index.collection, payload={"text_hash": "velho"}, points=[node_id])
        pages = []
        original = env.raw.list_nodes

        def spy(label, *, after_id=None, limit=200):
            page = original(label, after_id=after_id, limit=limit)
            pages.append(len(page))
            return page

        monkeypatch.setattr(env.raw, "list_nodes", spy)
        report = env.index.reconcile()
        assert report.reindexed == 10
        assert max(pages) <= 3 and sum(1 for p in pages if p) >= 4

    def test_list_nodes_inmemory_pagina_por_id(self):
        store = InMemoryGraphStore()
        ids = [
            store.create_node(
                "Problema",
                {"titulo": f"t{i}", "resumo": "r", "status": "rascunho", "projeto_id": "p", "sessao_id": "s"},
                actor=ORQ,
            )
            for i in range(5)
        ]
        p1 = store.list_nodes("Problema", limit=2)
        p2 = store.list_nodes("Problema", after_id=p1[-1].id, limit=10)
        assert [n.id for n in p1 + p2] == sorted(ids)

    def test_list_nodes_age_usa_cursor_ordem_e_limite_parametrizados(self):
        store = AgeGraphStore("knowledge", reader_conninfo="postgresql://r@h/d", read_timeout_ms=5000)
        with patch.object(store, "_run_cypher", return_value=[]) as run:
            store.list_nodes("Problema", after_id="abc", limit=50)
        body, params = run.call_args.args
        assert "n.id > $after_id" in body and "ORDER BY n.id LIMIT $limit" in body
        assert params == {"after_id": "abc", "limit": 50}


@pytest.mark.unit
class TestI3ColecaoPropria:
    def _mismatch(self, env):
        _vec(env, "titulo: P1")
        env.make("Problema", titulo="P1")
        env.index._provider_arg = ControlledEmbeddingProvider(  # noqa: SLF001
            {"titulo: P1": [1.0] * 4}, dimension=4, model="outro"
        )
        env.index._ready = False  # noqa: SLF001

    def test_recusa_colecao_com_nome_diferente_do_configurado(self, env, monkeypatch):
        self._mismatch(env)
        monkeypatch.setattr(config, "KNOWLEDGE_COLLECTION", "outra_colecao")
        with pytest.raises(ForeignCollectionError):
            env.index.reconcile(allow_recreate=True)
        assert env.client.collection_exists(env.index.collection)

    def test_recusa_colecao_com_pontos_estrangeiros(self, env):
        """Scenario: Coleção estrangeira"""
        self._mismatch(env)
        env.client.upsert(
            env.index.collection,
            [PointStruct(id=999, vector=[0.1] * DIM, payload={"content": "chunk de documento"})],
        )
        with pytest.raises(ForeignCollectionError):
            env.index.reconcile(allow_recreate=True)
        assert env.client.count(env.index.collection).count == 2

    def _runtime(self, env):
        self._mismatch(env)
        return SemanticRuntime(store=env.store, raw_store=env.raw, index=env.index, queue=env.queue)

    def test_reindex_cancelado_nao_recria(self, env, monkeypatch, capsys):
        runtime = self._runtime(env)
        monkeypatch.setattr("builtins.input", lambda _: "n")
        assert run_knowledge_command(["reindex"], runtime) == 1
        assert "cancelada" in capsys.readouterr().out
        assert env.client.get_collection(env.index.collection).config.params.vectors.size == DIM

    def test_reindex_confirmado_com_o_nome_da_colecao_recria(self, env, monkeypatch):
        runtime = self._runtime(env)
        monkeypatch.setattr("builtins.input", lambda _: env.index.collection)
        assert run_knowledge_command(["reindex"], runtime) == 0
        assert env.client.get_collection(env.index.collection).config.params.vectors.size == 4

    def test_reindex_sem_terminal_pede_yes(self, env, monkeypatch, capsys):
        runtime = self._runtime(env)

        def eof(_):
            raise EOFError

        monkeypatch.setattr("builtins.input", eof)
        assert run_knowledge_command(["reindex"], runtime) == 1
        assert "--yes" in capsys.readouterr().out

    def test_reindex_yes_pula_a_confirmacao(self, env):
        runtime = self._runtime(env)
        assert run_knowledge_command(["reindex", "--yes"], runtime) == 0

    def test_dimensao_diferente_sem_permissao_levanta(self, env):
        self._mismatch(env)
        with pytest.raises(IndexDimensionError):
            env.index.reconcile()


@pytest.mark.unit
class TestI4StatusEVisibilidade:
    def test_similar_nao_devolve_rejeitado(self, env):
        """Scenario: Nó rejeitado"""
        _vec(env, "enunciado: oa", 0, 0.9)
        _vec(env, "enunciado: ob", 0, 0.9, second=True)
        _vec(env, "enunciado: oc", 0, 0.9, second=True)
        env.make("Oportunidade", enunciado="oa")
        rejeitada = env.make("Oportunidade", enunciado="ob", status="rejeitada")
        ok = env.make("Oportunidade", enunciado="oc")
        hits = env.index.similar(text="enunciado: oa", labels=["Oportunidade"])
        ids = {h.node_id for h in hits}
        assert ok in ids and rejeitada not in ids

    def test_similar_nao_devolve_dominio_rejeitado_nem_substituida(self, env):
        env.provider.vectors["termo: dom"] = pair_vectors(DIM, 0, 1.0)[0]
        env.make("Dominio", termo="dom", status="rejeitado")
        assert env.index.similar(text="termo: dom", labels=["Dominio"]) == []

    def test_projeto_id_restringe_a_privados_do_proprio_projeto(self, env):
        """Scenario: Privado de outro projeto"""
        _vec(env, "titulo: Q", 0, 0.8)
        _vec(env, "titulo: meu", 0, 0.8, second=True)
        _vec(env, "titulo: alheio", 0, 0.8, second=True)
        _vec(env, "titulo: aberto", 0, 0.8, second=True)
        meu = env.make("Problema", projeto_id="A", titulo="meu")
        env.make("Problema", projeto_id="B", titulo="alheio")
        aberto = env.make("Problema", projeto_id="B", titulo="aberto", visibilidade="compartilhavel")
        hits = env.index.similar(text="titulo: Q", labels=["Problema"], projeto_id="A")
        assert {h.node_id for h in hits} == {meu, aberto}
        todos = env.index.similar(text="titulo: Q", labels=["Problema"])
        assert len(todos) == 3

    def test_filtro_com_chave_desconhecida_falha_cedo(self, env):
        with pytest.raises(ValueError, match="desconhecida"):
            env.index.similar(text="x", labels=["Problema"], filters={"projeto": "A"})

    def test_related_experience_restrito_nao_traz_privado_de_outro_projeto(self, env):
        from tests.unit.knowledge.test_related_experience import _abordagem, _funcionou, _setup

        ids = _setup(env)
        a = _abordagem(env, "A", "projB")
        _funcionou(env, a, ids["P2"])
        # visão local (padrão): enxerga
        assert [i.node.id for i in env.index.related_experience(ids["P1"])] == [a]
        # visão restrita: P2 é privado de outro projeto -> nada
        assert env.index.related_experience(ids["P1"], restrict_to_visible=True) == []

    def test_related_experience_ignora_item_substituido(self, env):
        from tests.unit.knowledge.test_related_experience import _descoberta, _setup

        ids = _setup(env)
        d = _descoberta(env, "velha", "projB", 0.9, status="substituida")
        env.store.create_edge(d, "SOBRE", ids["P2"], {}, actor=ORQ)
        assert env.index.related_experience(ids["P1"]) == []


@pytest.mark.unit
class TestI5LigacaoNaFactory:
    def test_open_graph_store_devolve_store_indexado(self, monkeypatch):
        raw = InMemoryGraphStore()
        monkeypatch.setattr(factory, "open_raw_graph_store", lambda: raw)
        monkeypatch.setattr(config, "KNOWLEDGE_SEMANTIC_INDEX_ENABLED", True)
        from qdrant_client import QdrantClient

        monkeypatch.setattr("src.embeddings.reindex._make_client", lambda url: QdrantClient(location=":memory:"))
        store = factory.open_graph_store()
        assert isinstance(store, IndexedGraphStore)

    def test_escrita_do_vocabulario_passa_pelo_gancho(self, monkeypatch):
        raw = InMemoryGraphStore()
        monkeypatch.setattr(factory, "open_raw_graph_store", lambda: raw)
        from qdrant_client import QdrantClient

        client = QdrantClient(location=":memory:")
        monkeypatch.setattr("src.embeddings.reindex._make_client", lambda url: client)
        store = factory.open_graph_store()
        node_id = store.create_node(
            "Dominio",
            {"termo": "Química", "nivel": "area", "status": "candidato", "projeto_id": "vocab", "sessao_id": "s"},
            actor=ORQ,
        )
        assert raw.get_node(node_id).properties["estado_vetorizacao"] == "ok"
        assert client.retrieve(config.KNOWLEDGE_COLLECTION, ids=[node_id])

    def test_desligado_devolve_store_cru(self, monkeypatch):
        raw = InMemoryGraphStore()
        monkeypatch.setattr(factory, "open_raw_graph_store", lambda: raw)
        monkeypatch.setattr(config, "KNOWLEDGE_SEMANTIC_INDEX_ENABLED", False)
        assert factory.open_graph_store() is raw

    def test_indice_nao_carrega_modelo_ao_ser_montado(self, monkeypatch):
        from qdrant_client import QdrantClient

        def boom():
            raise AssertionError("modelo carregado cedo demais")

        monkeypatch.setattr("src.knowledge.semantic_index.get_embedding_provider", boom)
        SemanticIndex(InMemoryGraphStore(), QdrantClient(location=":memory:"))

    def test_status_de_dominio_aprovado_chega_ao_payload(self, env):
        env.provider.vectors["Domínio: Fis"] = pair_vectors(DIM, 0, 1.0)[0]
        dom = env.make("Dominio", termo="Fis", status="candidato")
        env.store.update_node(dom, {"status": "aprovado"}, actor=ORQ)
        assert env.point(dom).payload["status"] == "aprovado"

    def test_reconcile_corrige_payload_defasado_sem_revetorizar(self, env):
        env.provider.vectors["Domínio: Fis"] = pair_vectors(DIM, 0, 1.0)[0]
        dom = env.make("Dominio", termo="Fis", status="candidato")
        env.raw.update_node(dom, {"status": "aprovado"}, actor=ORQ)  # escrita sem o gancho
        assert env.point(dom).payload["status"] == "candidato"
        calls = len(env.provider.embedded_texts)
        report = env.index.reconcile()
        assert report.payload_refreshed == 1 and report.reindexed == 0
        assert env.point(dom).payload["status"] == "aprovado"
        assert len(env.provider.embedded_texts) == calls


@pytest.mark.unit
class TestS1AmostraMinima:
    def test_amostra_pequena_nao_sugere(self):
        assert suggest_adjustments([BandRate("relacionado", "baixa", 0, 3)]) == []

    def test_amostra_suficiente_sugere(self):
        assert suggest_adjustments([BandRate("relacionado", "baixa", 0, 10)])


@pytest.mark.unit
def test_candidato_dataclass_inalterado():
    assert Candidate.__dataclass_fields__["text_hash_a"]
