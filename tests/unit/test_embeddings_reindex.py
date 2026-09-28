"""Testes unitários de `src/embeddings/reindex.py` (Roadmap V16 / ADR 011 §3).

Cobre a lógica de `CollectionReindexer` com um `QdrantClient` mockado:
contagem de pontos desatualizados, recriação da coleção quando a dimensão
muda, pontos sem texto de origem, e coleção/nome inválidos.
"""

from unittest.mock import MagicMock

import pytest

from src.embeddings.reindex import (
    REINDEXABLE_COLLECTIONS,
    CollectionNotFoundError,
    CollectionReindexer,
)
from tests.support.fake_embedding_provider import FakeEmbeddingProvider


def _point(point_id: str, payload: dict) -> MagicMock:
    p = MagicMock()
    p.id = point_id
    p.payload = payload
    return p


def _client_with_points(points: list, collection_exists: bool = True) -> MagicMock:
    client = MagicMock()
    existing = MagicMock()
    existing.name = "geminiclaw_knowledge"
    client.get_collections.return_value.collections = [existing] if collection_exists else []
    client.scroll.return_value = (points, None)
    collection_info = MagicMock()
    collection_info.config.params.vectors.size = 384
    client.get_collection.return_value = collection_info
    return client


@pytest.mark.unit
def test_rejects_non_reindexable_collection_name():
    provider = FakeEmbeddingProvider(dimension=384)
    with pytest.raises(ValueError):
        CollectionReindexer("not_a_real_collection", embedding_provider=provider, client=MagicMock())


@pytest.mark.unit
def test_reindexable_collections_constant_has_expected_names():
    assert set(REINDEXABLE_COLLECTIONS) == {"geminiclaw_knowledge", "geminiclaw_documents"}


@pytest.mark.unit
def test_count_outdated_raises_when_collection_missing():
    client = _client_with_points([], collection_exists=False)
    provider = FakeEmbeddingProvider(dimension=384)
    reindexer = CollectionReindexer("geminiclaw_knowledge", embedding_provider=provider, client=client)

    with pytest.raises(CollectionNotFoundError):
        reindexer.count_outdated()


@pytest.mark.unit
def test_run_raises_when_collection_missing():
    client = _client_with_points([], collection_exists=False)
    provider = FakeEmbeddingProvider(dimension=384)
    reindexer = CollectionReindexer("geminiclaw_knowledge", embedding_provider=provider, client=client)

    with pytest.raises(CollectionNotFoundError):
        reindexer.run()


@pytest.mark.unit
def test_count_outdated_counts_points_missing_or_mismatched_metadata():
    points = [
        _point("1", {"content": "a", "embedding_model": "fake/test-embedding", "embedding_version": "test-1"}),
        _point("2", {"content": "b"}),  # sem metadados (vetor aleatório legado)
        _point("3", {"content": "c", "embedding_model": "outro/modelo", "embedding_version": "v0"}),
    ]
    client = _client_with_points(points)
    provider = FakeEmbeddingProvider(dimension=384, model="fake/test-embedding", version="test-1")
    reindexer = CollectionReindexer("geminiclaw_knowledge", embedding_provider=provider, client=client)

    assert reindexer.count_outdated() == 2


@pytest.mark.unit
def test_run_recreates_collection_when_dimension_changed():
    client = _client_with_points([])
    client.get_collection.return_value.config.params.vectors.size = 999  # != provider.dimension
    provider = FakeEmbeddingProvider(dimension=384)
    reindexer = CollectionReindexer("geminiclaw_knowledge", embedding_provider=provider, client=client)

    report = reindexer.run()

    assert report.recreated_collection is True
    assert report.updated == 0
    client.delete_collection.assert_called_once_with("geminiclaw_knowledge")
    client.create_collection.assert_called_once()


@pytest.mark.unit
def test_run_rewrites_only_outdated_points_and_reports_skipped_without_text():
    points = [
        _point("1", {"content": "novo conteúdo sem metadata"}),
        _point(
            "2",
            {"content": "já vetorizado", "embedding_model": "fake/test-embedding", "embedding_version": "test-1"},
        ),
        _point("3", {}),  # sem "content" — não pode ser revetorizado
    ]
    client = _client_with_points(points)
    provider = FakeEmbeddingProvider(dimension=384, model="fake/test-embedding", version="test-1")
    reindexer = CollectionReindexer("geminiclaw_knowledge", embedding_provider=provider, client=client)

    report = reindexer.run()

    assert report.recreated_collection is False
    assert report.updated == 1
    assert report.already_current == 1
    assert report.skipped_no_text == 1
    client.upsert.assert_called_once()
    upserted_points = client.upsert.call_args.kwargs["points"]
    assert len(upserted_points) == 1
    assert upserted_points[0].id == "1"
    assert upserted_points[0].payload["embedding_model"] == "fake/test-embedding"


@pytest.mark.unit
def test_reindex_report_summary_mentions_recreated_when_dimension_changed():
    from src.embeddings.reindex import ReindexReport

    report = ReindexReport(collection="geminiclaw_knowledge", recreated_collection=True, elapsed_seconds=1.0)
    assert "recriada" in report.summary()


@pytest.mark.unit
def test_reindex_report_summary_counts_when_not_recreated():
    from src.embeddings.reindex import ReindexReport

    report = ReindexReport(
        collection="geminiclaw_knowledge",
        updated=3,
        already_current=2,
        skipped_no_text=1,
        elapsed_seconds=0.5,
    )
    summary = report.summary()
    assert "3" in summary and "2" in summary and "1" in summary
