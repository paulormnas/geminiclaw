import pytest
import asyncio
from typing import List, Dict, Any
from src.skills.search_deep.indexer import VectorIndexer
from src.skills.search_deep.crawler import CrawledPage

@pytest.fixture
def indexer():
    # Usar memória pura para testes rápidos e isolados
    return VectorIndexer(url=":memory:")

@pytest.mark.asyncio
async def test_indexer_flow(indexer):
    pages = [
        CrawledPage(
            url="https://docs.python.org/page1",
            title="Python Functions",
            content="def my_func():\n    pass",
            crawled_at="2026-03-22T00:00:00Z",
            domain="docs.python.org",
            content_type="code"
        ),
        CrawledPage(
            url="https://docs.python.org/page2",
            title="Python Introduction",
            content="Python is a programming language.",
            crawled_at="2026-03-22T00:00:00Z",
            domain="docs.python.org",
            content_type="text"
        ),
        CrawledPage(
            url="https://rust-lang.org/intro",
            title="Rust Intro",
            content="Rust is safe.",
            crawled_at="2026-03-22T00:00:00Z",
            domain="rust-lang.org",
            content_type="text"
        )
    ]
    
    # 1. Indexing
    await indexer.index_pages(pages)
    
    stats = indexer.get_stats()
    assert stats["points_count"] == 3
    
    # 2. Search without filters
    results = await indexer.search("programming")
    assert len(results) == 3 # Returns all points normally, sorted by score. The mock embedding is random.
    
    # 3. Search with domain filter
    filtered_results = await indexer.search("programming", domain="docs.python.org")
    assert len(filtered_results) == 2
    for r in filtered_results:
        assert r["metadata"]["domain"] == "docs.python.org"
        
    # 4. Reindex (delete domain specific)
    await indexer.reindex("docs.python.org")
    
    stats_after = indexer.get_stats()
    assert stats_after["points_count"] == 1 # Only rust remains
    
    remaining = await indexer.search("anything")
    assert remaining[0]["metadata"]["domain"] == "rust-lang.org"

def test_indexer_chunking(indexer):
    text = "A" * 2000
    chunks = indexer._chunk_text(text, chunk_size=1500, overlap=150)
    assert len(chunks) == 2
    assert len(chunks[0]) == 1500
    assert chunks[1] == "A" * (2000 - 1500 + 150)
