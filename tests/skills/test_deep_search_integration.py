import pytest
import respx
import asyncio
from src.skills.search_deep.skill import DeepSearchSkill
from src.skills.search_deep.indexer import VectorIndexer
from src.skills.search_deep.cache import DeepSearchCache
from src.skills.search_deep.crawler import DomainCrawler

@pytest.fixture
def memory_indexer():
    return VectorIndexer(url=":memory:")

@pytest.fixture
def memory_cache(tmp_path):
    db_path = tmp_path / "cache.db"
    return DeepSearchCache(db_path=str(db_path))

@pytest.mark.asyncio
async def test_deep_search_integration(tmp_path, memory_indexer, memory_cache):
    state_file = tmp_path / "state.json"
    crawler = DomainCrawler(state_file=str(state_file))
    
    html = """
    <html><head><title>Integration Test</title></head>
    <body><p>This is the content that should be crawled, indexed, and found.</p></body></html>
    """
    
    with respx.mock(assert_all_called=True) as mock_respx:
        mock_respx.get("https://int-test.local").respond(200, html=html)
        
        # 1. Crawl
        pages = await crawler.crawl(["int-test.local"], max_pages_per_domain=1)
        assert len(pages) == 1
        
        # 2. Index
        await memory_indexer.index_pages(pages)
        
        # 3. Simulate Agent Search via Skill
        skill = DeepSearchSkill(indexer=memory_indexer, cache=memory_cache)
        
        query = "crawled indexed content"
        
        # Primeira busca: miss no cache, hit no índice
        result1 = await skill.run(query=query, domain="int-test.local")
        assert result1.success is True
        assert len(result1.output) > 0
        assert result1.metadata["source"] == "index"
        assert result1.output[0]["title"] == "Integration Test"
        
        # Segunda busca: hit no cache
        result2 = await skill.run(query=query, domain="int-test.local")
        assert result2.success is True
        assert result2.metadata["source"] == "cache"
        assert result2.output == result1.output
    
    await crawler.close()
