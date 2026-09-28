"""Testes do comportamento introduzido pela mudança v16-local-embeddings em DocumentIndexer.

Cobre: indexação vetorial e busca via provedor de embeddings local (falso e
determinístico nos testes), proteção contra mistura de dimensões, e
exclusão/aviso de pontos com embedding desatualizado na busca.
"""

import logging
import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.skills.document_processor.chunker import DocumentChunk
from src.skills.document_processor.indexer import DocumentIndexer
from tests.support.fake_embedding_provider import FakeEmbeddingProvider


def _chunk(chunk_id: str, document_id: str, content: str, index: int = 0) -> DocumentChunk:
    # O Qdrant local (":memory:") exige que IDs de string sejam UUIDs válidos.
    real_id = str(uuid.uuid5(uuid.NAMESPACE_OID, chunk_id))
    return DocumentChunk(
        chunk_id=real_id,
        document_id=document_id,
        content=content,
        chunk_index=index,
        total_chunks=1,
        metadata={"format": "txt"},
        token_count=len(content) // 4,
    )


def _mocked_qdrant_client(existing_collections=None):
    patcher = patch("src.skills.document_processor.indexer.QdrantClient")
    mock_cls = patcher.start()
    mock_client = MagicMock()
    mock_cls.return_value = mock_client
    mock_client.get_collections.return_value.collections = existing_collections or []
    return patcher, mock_client


@pytest.mark.unit
@pytest.mark.asyncio
async def test_index_vectors_and_search_returns_nearest_chunk_with_fake_provider():
    provider = FakeEmbeddingProvider(dimension=16)
    indexer = DocumentIndexer(url=":memory:", embedding_provider=provider)

    chunks = [
        _chunk("c1", "doc1", "difração de raios X em cristais"),
        _chunk("c2", "doc2", "receita tradicional de pão caseiro"),
    ]
    await indexer._index_vectors(chunks)

    results = indexer.search("difração de raios X em cristais")

    assert results[0]["document_id"] == "doc1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_indexed_points_carry_embedding_metadata():
    provider = FakeEmbeddingProvider(dimension=8, model="fake/test-embedding", version="test-1")
    indexer = DocumentIndexer(url=":memory:", embedding_provider=provider)

    chunks = [_chunk("c1", "doc1", "conteudo de teste")]
    await indexer._index_vectors(chunks)

    # Busca via client bruto para inspecionar o payload gravado.
    points, _ = indexer.qdrant.scroll(collection_name=DocumentIndexer.COLLECTION_NAME, with_payload=True)
    payload = points[0].payload

    assert payload["embedding_model"] == "fake/test-embedding"
    assert payload["embedding_version"] == "test-1"
    assert payload["embedding_dim"] == 8
    assert "text_hash" in payload


@pytest.mark.unit
def test_ensure_collection_disables_search_on_dimension_mismatch():
    patcher, mock_client = _mocked_qdrant_client()
    try:
        existing = MagicMock()
        existing.name = DocumentIndexer.COLLECTION_NAME
        mock_client.get_collections.return_value.collections = [existing]

        collection_info = MagicMock()
        collection_info.config.params.vectors.size = 768
        mock_client.get_collection.return_value = collection_info

        provider = FakeEmbeddingProvider(dimension=384)
        indexer = DocumentIndexer(url=":memory:", embedding_provider=provider)

        assert indexer._search_disabled is True
        mock_client.create_collection.assert_not_called()
    finally:
        patcher.stop()


@pytest.mark.unit
def test_search_returns_empty_with_warning_when_disabled(caplog):
    patcher, mock_client = _mocked_qdrant_client()
    try:
        existing = MagicMock()
        existing.name = DocumentIndexer.COLLECTION_NAME
        mock_client.get_collections.return_value.collections = [existing]
        collection_info = MagicMock()
        collection_info.config.params.vectors.size = 999
        mock_client.get_collection.return_value = collection_info

        provider = FakeEmbeddingProvider(dimension=384)
        indexer = DocumentIndexer(url=":memory:", embedding_provider=provider)
        assert indexer._search_disabled is True

        with caplog.at_level(logging.WARNING):
            results = indexer.search("qualquer coisa")

        assert results == []
        assert not mock_client.query_points.called
        assert any("desabilitada" in r.message for r in caplog.records)
    finally:
        patcher.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_index_vectors_noop_when_disabled():
    patcher, mock_client = _mocked_qdrant_client()
    try:
        existing = MagicMock()
        existing.name = DocumentIndexer.COLLECTION_NAME
        mock_client.get_collections.return_value.collections = [existing]
        collection_info = MagicMock()
        collection_info.config.params.vectors.size = 999
        mock_client.get_collection.return_value = collection_info

        provider = FakeEmbeddingProvider(dimension=384)
        indexer = DocumentIndexer(url=":memory:", embedding_provider=provider)
        assert indexer._search_disabled is True

        await indexer._index_vectors([_chunk("c1", "doc1", "x")])

        assert not mock_client.upsert.called
    finally:
        patcher.stop()


@pytest.mark.unit
def test_search_filters_outdated_points_and_warns(caplog):
    patcher, mock_client = _mocked_qdrant_client()
    try:
        provider = FakeEmbeddingProvider(dimension=4)
        indexer = DocumentIndexer(url=":memory:", embedding_provider=provider)

        hit = MagicMock()
        hit.payload = {"content": "conteudo", "document_id": "doc1"}
        hit.score = 0.5
        result_obj = MagicMock()
        result_obj.points = [hit]
        mock_client.query_points.return_value = result_obj
        mock_client.count.side_effect = [MagicMock(count=5), MagicMock(count=4)]

        with caplog.at_level(logging.WARNING):
            results = indexer.search("query")

        assert len(results) == 1
        assert any("desatualizado" in r.message for r in caplog.records)
        assert any(getattr(r, "outdated_count", None) == 1 for r in caplog.records)
    finally:
        patcher.stop()
