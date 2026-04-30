import pytest
import respx
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from src.skills.search_deep.skill import DeepSearchSkill
from src.skills.search_deep.indexer import VectorIndexer
from src.skills.search_deep.cache import DeepSearchCache
from src.skills.search_deep.crawler import DomainCrawler

@pytest.fixture
def memory_indexer():
    return VectorIndexer(url=":memory:")

@pytest.fixture
def memory_cache():
    return DeepSearchCache()


@pytest.mark.asyncio
async def test_deep_search_integration(tmp_path, memory_indexer, memory_cache):
    state_file = tmp_path / "state.json"
    crawler = DomainCrawler(state_file=str(state_file))

    html = """
    <html><head><title>Integration Test</title></head>
    <body><p>This is the content that should be crawled, indexed, and found.</p></body></html>
    """

    # Prepara o mock do cache: primeiro get() dá miss, set() grava, segundo get() dá hit
    results_store = {}

    def _make_conn_ctx(fetchone_val=None):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = fetchone_val
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_conn)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    # Primeira busca: cache miss (fetchone=None) + set (INSERT)
    # Segunda busca: cache hit (fetchone com resultado)
    fake_results_json = None

    def cache_get_side_effect():
        if fake_results_json is None:
            return _make_conn_ctx(fetchone_val=None)
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        return _make_conn_ctx(fetchone_val={"results": fake_results_json, "expires_at": future})

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
        with patch("src.skills.search_deep.cache.get_connection", side_effect=lambda: _make_conn_ctx(None)):
            result1 = await skill.run(query=query, domain="int-test.local")

        assert result1.success is True
        assert len(result1.output) > 0
        assert result1.metadata["source"] == "index"
        assert result1.output[0]["title"] == "Integration Test"

        # Salva resultado para simular hit no cache
        fake_results_json = json.dumps(result1.output)
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        hit_row = {"results": fake_results_json, "expires_at": future}
        ctx_update = _make_conn_ctx()  # para o UPDATE de expires_at após hit

        # Segunda busca: hit no cache
        with patch("src.skills.search_deep.cache.get_connection", side_effect=[_make_conn_ctx(hit_row), ctx_update]):
            result2 = await skill.run(query=query, domain="int-test.local")

        assert result2.success is True
        assert result2.metadata["source"] == "cache"
        assert result2.output == result1.output

    await crawler.close()
