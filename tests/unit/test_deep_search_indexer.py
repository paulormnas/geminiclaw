import pytest
from unittest.mock import patch, MagicMock
from src.skills.search_deep.indexer import VectorIndexer
from src.skills.search_deep.crawler import CrawledPage

@pytest.fixture
def indexer():
    # Usa Qdrant em memória para testes unitários
    with patch("src.skills.search_deep.indexer.QdrantClient") as mock_qdrant:
        mock_client = MagicMock()
        mock_qdrant.return_value = mock_client
        # Simula resposta de get_collections (vazia)
        mock_client.get_collections.return_value.collections = []
        
        idx = VectorIndexer(url=":memory:")
        return idx, mock_client

from unittest.mock import patch, MagicMock

@pytest.mark.unit
@pytest.mark.asyncio
async def test_indexer_chunking():
    indexer = VectorIndexer(url=":memory:")
    # Caso normal
    text = "A" * 2000
    chunks = indexer._chunk_text(text, chunk_size=1000, overlap=100)
    assert len(chunks) > 1
    assert len(chunks[0]) == 1000
    
    # Caso texto curto
    short_text = "Short"
    chunks = indexer._chunk_text(short_text)
    assert len(chunks) == 1
    assert chunks[0] == short_text

    # Caso texto vazio
    empty_text = ""
    chunks = indexer._chunk_text(empty_text)
    assert len(chunks) == 0

@pytest.mark.unit
@pytest.mark.asyncio
async def test_indexer_upsert():
    with patch("src.skills.search_deep.indexer.QdrantClient") as mock_qdrant:
        mock_client = MagicMock()
        mock_qdrant.return_value = mock_client
        mock_client.get_collections.return_value.collections = []
        
        indexer = VectorIndexer(url=":memory:")
        
        pages = [
            CrawledPage(
                url="https://test.com",
                title="Test",
                content="Some content that will be chunked",
                crawled_at="2024-03-22T00:00:00",
                domain="test.com"
            )
        ]
        
        await indexer.index_pages(pages)
        assert mock_client.upsert.called

@pytest.mark.unit
@pytest.mark.asyncio
async def test_indexer_search():
    with patch("src.skills.search_deep.indexer.QdrantClient") as mock_qdrant:
        mock_client = MagicMock()
        mock_qdrant.return_value = mock_client
        mock_client.get_collections.return_value.collections = []
        
        # Simula retorno do search
        mock_hit = MagicMock()
        mock_hit.payload = {
            "content": "Found content",
            "url": "https://test.com",
            "title": "Test Title"
        }
        mock_hit.score = 0.9
        mock_client.search.return_value = [mock_hit]
        
        indexer = VectorIndexer(url=":memory:")
        results = await indexer.search("query", domain="test.com")
        
        assert len(results) == 1
        assert results[0]["content"] == "Found content"
        assert mock_client.search.called
        # Verifica se o filtro foi aplicado
        args, kwargs = mock_client.search.call_args
        assert "query_filter" in kwargs
        assert kwargs["query_filter"] is not None

@pytest.mark.unit
@pytest.mark.asyncio
async def test_indexer_get_stats():
    with patch("src.skills.search_deep.indexer.QdrantClient") as mock_qdrant:
        mock_client = MagicMock()
        mock_qdrant.return_value = mock_client
        mock_client.get_collections.return_value.collections = []
        
        mock_collection_info = MagicMock()
        mock_collection_info.points_count = 100
        mock_collection_info.status = "green"
        mock_client.get_collection.return_value = mock_collection_info
        
        indexer = VectorIndexer(url=":memory:")
        stats = indexer.get_stats()
        
        assert stats["points_count"] == 100
        assert stats["status"] == "green"

@pytest.mark.unit
def test_indexer_ensure_collection_error():
    with patch("src.skills.search_deep.indexer.QdrantClient") as mock_qdrant:
        mock_client = MagicMock()
        mock_qdrant.return_value = mock_client
        mock_client.get_collections.side_effect = Exception("Qdrant connection error")
        
        # Não deve levantar exceção, apenas logar o erro
        indexer = VectorIndexer(url=":memory:")
        assert indexer.client == mock_client
