import pytest
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch
from src.skills.search_deep.crawler import DomainCrawler, CrawledPage

@pytest.fixture
def crawler():
    crawler = DomainCrawler(state_file="/tmp/test_crawl_state.json")
    yield crawler
    if os.path.exists("/tmp/test_crawl_state.json"):
        os.remove("/tmp/test_crawl_state.json")

@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawler_extract_text(crawler):
    from bs4 import BeautifulSoup
    html = "<html><body><h1>Title</h1><p>Paragraph 1</p><script>alert(1)</script><style>body{color:red}</style></body></html>"
    soup = BeautifulSoup(html, "lxml")
    text = crawler._extract_text(soup)
    assert "Title" in text
    assert "Paragraph 1" in text
    assert "alert" not in text
    assert "color:red" not in text

@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawler_incremental_logic(crawler):
    # Mock do httpx client
    crawler.client = AsyncMock()
    
    # Simula página não modificada (304)
    crawler.state["https://example.com"] = {"last_modified": "Mon, 01 Jan 2024 00:00:00 GMT"}
    
    mock_response = MagicMock()
    mock_response.status_code = 304
    crawler.client.get.return_value = mock_response
    
    pages = await crawler._crawl_domain("example.com", max_pages=1)
    
    assert len(pages) == 0
    assert crawler.client.get.call_args[1]["headers"]["If-Modified-Since"] == "Mon, 01 Jan 2024 00:00:00 GMT"
@pytest.mark.unit
def test_crawler_load_state_error(tmp_path):
    state_file = tmp_path / "corrupt.json"
    state_file.write_text("invalid json")
    crawler = DomainCrawler(state_file=str(state_file))
    assert crawler.state == {}

@pytest.mark.unit
def test_crawler_save_state(tmp_path):
    state_file = tmp_path / "state.json"
    crawler = DomainCrawler(state_file=str(state_file))
    crawler.state["test"] = "data"
    crawler._save_state()
    assert state_file.exists()
    assert "test" in state_file.read_text()

@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawler_main_crawl_method(crawler):
    with patch.object(crawler, "_crawl_domain", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = [
            CrawledPage(url="http://a.com", title="A", content="A", crawled_at="now", domain="a.com")
        ]
        pages = await crawler.crawl(["a.com"], max_pages_per_domain=1)
        assert len(pages) == 1
        assert mock_crawl.called

@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawler_handle_non_200(crawler):
    crawler.client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 404
    crawler.client.get.return_value = mock_response
    
    pages = await crawler._crawl_domain("example.com", max_pages=1)
    assert len(pages) == 0

@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawler_link_extraction(crawler):
    crawler.client = AsyncMock()
    
    # Simula primeira página com link
    res1 = MagicMock()
    res1.status_code = 200
    res1.text = "<html><body><a href='/page2'>Link</a></body></html>"
    res1.headers = {}
    
    # Simula segunda página
    res2 = MagicMock()
    res2.status_code = 200
    res2.text = "<html><body>Page 2</body></html>"
    res2.headers = {}
    
    crawler.client.get.side_effect = [res1, res2]
    
    # Mock sleep para acelerar teste
    with patch("asyncio.sleep", return_value=None):
        pages = await crawler._crawl_domain("example.com", max_pages=2)
        
    assert len(pages) == 2
    assert "page2" in pages[1].url

@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawler_close(crawler):
    crawler.client = AsyncMock()
    await crawler.close()
    assert crawler.client.aclose.called
