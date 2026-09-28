"""Testes do comportamento introduzido pela mudança v16-local-embeddings em VectorIndexer.

Cobre: indexação e busca via provedor de embeddings local (falso e
determinístico nos testes), proteção contra mistura de dimensões, e
exclusão/aviso de pontos com embedding desatualizado na busca.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.skills.search_deep.crawler import CrawledPage
from src.skills.search_deep.indexer import VectorIndexer
from tests.support.fake_embedding_provider import FakeEmbeddingProvider


def _mocked_qdrant_client(existing_collections=None):
    """Cria um QdrantClient mockado com `get_collections` pré-configurado."""
    patcher = patch("src.skills.search_deep.indexer.QdrantClient")
    mock_cls = patcher.start()
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.get_collections.return_value.collections = existing_collections or []
    return patcher, mock_client


@pytest.mark.unit
@pytest.mark.asyncio
async def test_index_and_search_returns_nearest_chunk_with_fake_provider():
    """Indexa dois trechos bem distintos e verifica que a busca retorna o mais próximo."""
    provider = FakeEmbeddingProvider(dimension=16)
    indexer = VectorIndexer(url=":memory:", embedding_provider=provider)

    pages = [
        CrawledPage(
            url="https://a.test/crystal",
            title="Cristalografia",
            content="difração de raios X em cristais",
            crawled_at="2026-01-01T00:00:00Z",
            domain="a.test",
        ),
        CrawledPage(
            url="https://b.test/bread",
            title="Receita",
            content="receita tradicional de pão caseiro",
            crawled_at="2026-01-01T00:00:00Z",
            domain="b.test",
        ),
    ]
    await indexer.index_pages(pages)

    # Consulta com o texto EXATO do primeiro chunk: o provedor falso é
    # determinístico (hash do texto), então o vetor da query é idêntico ao
    # vetor gravado para esse chunk — deve ser o resultado mais próximo.
    results = await indexer.search("difração de raios X em cristais")

    assert results[0]["url"] == "https://a.test/crystal"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_indexed_points_carry_embedding_metadata():
    provider = FakeEmbeddingProvider(dimension=8, model="fake/test-embedding", version="test-1")
    indexer = VectorIndexer(url=":memory:", embedding_provider=provider)

    pages = [
        CrawledPage(
            url="https://a.test/1",
            title="A",
            content="conteudo de teste",
            crawled_at="2026-01-01T00:00:00Z",
            domain="a.test",
        )
    ]
    await indexer.index_pages(pages)

    results = await indexer.search("conteudo de teste")
    metadata = results[0]["metadata"]

    assert metadata["embedding_model"] == "fake/test-embedding"
    assert metadata["embedding_version"] == "test-1"
    assert metadata["embedding_dim"] == 8
    assert "text_hash" in metadata


@pytest.mark.unit
def test_ensure_collection_disables_search_on_dimension_mismatch():
    """Coleção já existente com dimensão diferente do provedor atual: não recria, desabilita a busca."""
    patcher, mock_client = _mocked_qdrant_client()
    try:
        existing = MagicMock()
        existing.name = VectorIndexer.COLLECTION_NAME
        mock_client.get_collections.return_value.collections = [existing]

        collection_info = MagicMock()
        collection_info.config.params.vectors.size = 768
        mock_client.get_collection.return_value = collection_info

        provider = FakeEmbeddingProvider(dimension=384)
        indexer = VectorIndexer(url=":memory:", embedding_provider=provider)

        assert indexer._search_disabled is True
        mock_client.create_collection.assert_not_called()
    finally:
        patcher.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_returns_empty_with_warning_when_disabled(caplog):
    patcher, mock_client = _mocked_qdrant_client()
    try:
        existing = MagicMock()
        existing.name = VectorIndexer.COLLECTION_NAME
        mock_client.get_collections.return_value.collections = [existing]
        collection_info = MagicMock()
        collection_info.config.params.vectors.size = 999
        mock_client.get_collection.return_value = collection_info

        provider = FakeEmbeddingProvider(dimension=384)
        indexer = VectorIndexer(url=":memory:", embedding_provider=provider)
        assert indexer._search_disabled is True

        with caplog.at_level(logging.WARNING):
            results = await indexer.search("qualquer coisa")

        assert results == []
        assert not mock_client.query_points.called
        assert any("desabilitada" in r.message for r in caplog.records)
    finally:
        patcher.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_index_pages_noop_when_disabled():
    patcher, mock_client = _mocked_qdrant_client()
    try:
        existing = MagicMock()
        existing.name = VectorIndexer.COLLECTION_NAME
        mock_client.get_collections.return_value.collections = [existing]
        collection_info = MagicMock()
        collection_info.config.params.vectors.size = 999
        mock_client.get_collection.return_value = collection_info

        provider = FakeEmbeddingProvider(dimension=384)
        indexer = VectorIndexer(url=":memory:", embedding_provider=provider)
        assert indexer._search_disabled is True

        pages = [
            CrawledPage(
                url="https://a.test",
                title="A",
                content="x",
                crawled_at="2026-01-01T00:00:00Z",
                domain="a.test",
            )
        ]
        await indexer.index_pages(pages)

        assert not mock_client.upsert.called
    finally:
        patcher.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_filters_outdated_points_and_warns(caplog):
    patcher, mock_client = _mocked_qdrant_client()
    try:
        provider = FakeEmbeddingProvider(dimension=4)
        indexer = VectorIndexer(url=":memory:", embedding_provider=provider)

        hit = MagicMock()
        hit.payload = {"content": "conteudo", "url": "https://a.test", "title": "A"}
        hit.score = 0.5
        result_obj = MagicMock()
        result_obj.points = [hit]
        mock_client.query_points.return_value = result_obj
        mock_client.count.side_effect = [MagicMock(count=10), MagicMock(count=7)]

        with caplog.at_level(logging.WARNING):
            results = await indexer.search("query")

        assert len(results) == 1
        assert any("desatualizado" in r.message for r in caplog.records)
        assert any(getattr(r, "outdated_count", None) == 3 for r in caplog.records)
    finally:
        patcher.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_count_failure_does_not_break_search():
    """Se a contagem de pontos desatualizados falhar, a busca ainda deve funcionar (aviso é best-effort)."""
    patcher, mock_client = _mocked_qdrant_client()
    try:
        provider = FakeEmbeddingProvider(dimension=4)
        indexer = VectorIndexer(url=":memory:", embedding_provider=provider)

        hit = MagicMock()
        hit.payload = {"content": "conteudo", "url": "https://a.test", "title": "A"}
        hit.score = 0.5
        result_obj = MagicMock()
        result_obj.points = [hit]
        mock_client.query_points.return_value = result_obj
        mock_client.count.side_effect = Exception("boom")

        results = await indexer.search("query")

        assert len(results) == 1
    finally:
        patcher.stop()
