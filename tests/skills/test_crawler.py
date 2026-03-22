import pytest
import respx
import httpx
from datetime import datetime
from src.skills.search_deep.crawler import DomainCrawler, CrawledPage

@pytest.fixture
def crawler(tmp_path):
    state_file = tmp_path / "crawl_state.json"
    c = DomainCrawler(state_file=str(state_file))
    yield c
    import asyncio
    asyncio.run(c.close())

@pytest.mark.asyncio
async def test_crawl_extracts_different_types(crawler):
    html = """
    <html>
        <head><title>Test Page</title></head>
        <body>
            <h1>Main Title</h1>
            <p>This is some introductory text.</p>
            <pre><code>print("Hello World")</code></pre>
            <p>More text goes here.</p>
            <table>
                <tr><td>Row 1</td></tr>
                <tr><td>Row 2</td></tr>
            </table>
        </body>
    </html>
    """
    with respx.mock(assert_all_called=True) as mock_respx:
        mock_respx.get("https://test.local").respond(200, html=html)
        
        pages = await crawler._crawl_domain("test.local", max_pages=1)
        
        assert len(pages) == 3
        
        types = [p.content_type for p in pages]
        assert "code" in types
        assert "table" in types
        assert "text" in types
        
        for p in pages:
            assert p.title == "Test Page"
            assert p.url == "https://test.local"
            assert p.domain == "test.local"
        
        code_page = next(p for p in pages if p.content_type == "code")
        assert "print(\"Hello World\")" in code_page.content
        
        table_page = next(p for p in pages if p.content_type == "table")
        assert "Row 1" in table_page.content
        assert "Row 2" in table_page.content
        
        text_page = next(p for p in pages if p.content_type == "text")
        assert "Main Title" in text_page.content
        assert "This is some introductory text." in text_page.content

@pytest.mark.asyncio
async def test_crawl_incremental(crawler):
    html = "<html><body><p>Text</p></body></html>"
    
    with respx.mock(assert_all_called=True) as mock_respx:
        # First call: returns 200 and Last-Modified header
        mock_respx.get("https://test.local").respond(
            200, 
            html=html,
            headers={"Last-Modified": "Wed, 21 Oct 2015 07:28:00 GMT"}
        )
        pages1 = await crawler.crawl(["test.local"], max_pages_per_domain=1)
        assert len(pages1) == 1
        
    with respx.mock(assert_all_called=True) as mock_respx2:
        # Second call: simulated 304 Not Modified
        mock_respx2.get("https://test.local").respond(304)
        pages2 = await crawler.crawl(["test.local"], max_pages_per_domain=1)
        assert len(pages2) == 0  # No new pages extracted
