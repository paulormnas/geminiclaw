"""Teste de integração de `src/embeddings/reindex.py` com um Qdrant de teste.

Usa `QdrantClient(location=":memory:")` (real, sem servidor externo) para
verificar o fluxo completo: pontos com vetores/metadados "antigos" (como os
mocks aleatórios que existiam antes do Roadmap V16) são revetorizados e
ganham os metadados de embedding corretos; pontos sem texto de origem são
reportados como ignorados.
"""

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from src.embeddings.reindex import CollectionReindexer
from tests.support.fake_embedding_provider import FakeEmbeddingProvider


def _seed_legacy_collection(client: QdrantClient, dimension: int) -> None:
    """Cria uma coleção com pontos "legados": sem metadados de embedding."""
    client.create_collection(
        collection_name="geminiclaw_knowledge",
        vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
    )
    client.upsert(
        collection_name="geminiclaw_knowledge",
        points=[
            PointStruct(
                id="00000000-0000-0000-0000-000000000001",
                vector=[0.1] * dimension,
                payload={"url": "https://a.test", "content": "conteúdo recuperável"},
            ),
            PointStruct(
                id="00000000-0000-0000-0000-000000000002",
                vector=[0.2] * dimension,
                payload={"url": "https://b.test"},  # sem "content" — não recuperável
            ),
        ],
    )


@pytest.mark.integration
def test_reindex_updates_legacy_points_and_reports_points_without_text():
    provider = FakeEmbeddingProvider(dimension=8, model="fake/test-embedding", version="test-1")
    client = QdrantClient(location=":memory:")
    _seed_legacy_collection(client, dimension=8)

    reindexer = CollectionReindexer("geminiclaw_knowledge", embedding_provider=provider, client=client)

    assert reindexer.count_outdated() == 2

    report = reindexer.run()

    assert report.recreated_collection is False
    assert report.updated == 1
    assert report.skipped_no_text == 1
    assert report.already_current == 0

    points, _ = client.scroll(collection_name="geminiclaw_knowledge", with_payload=True)
    by_id = {str(p.id): p.payload for p in points}

    updated_payload = by_id["00000000-0000-0000-0000-000000000001"]
    assert updated_payload["embedding_model"] == "fake/test-embedding"
    assert updated_payload["embedding_version"] == "test-1"
    assert updated_payload["embedding_dim"] == 8
    assert "text_hash" in updated_payload

    untouched_payload = by_id["00000000-0000-0000-0000-000000000002"]
    assert "embedding_model" not in untouched_payload

    # Uma segunda passagem não deve reescrever o ponto já atualizado.
    assert reindexer.count_outdated() == 1
    second_report = reindexer.run()
    assert second_report.updated == 0
    assert second_report.already_current == 1
    assert second_report.skipped_no_text == 1


@pytest.mark.integration
def test_reindex_recreates_collection_when_dimension_changes():
    provider = FakeEmbeddingProvider(dimension=16, model="fake/test-embedding", version="test-1")
    client = QdrantClient(location=":memory:")
    _seed_legacy_collection(client, dimension=8)

    reindexer = CollectionReindexer("geminiclaw_knowledge", embedding_provider=provider, client=client)
    report = reindexer.run()

    assert report.recreated_collection is True
    info = client.get_collection("geminiclaw_knowledge")
    assert info.config.params.vectors.size == 16
    assert info.points_count == 0
