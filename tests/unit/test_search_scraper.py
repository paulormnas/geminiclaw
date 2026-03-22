import pytest
import respx
import httpx
from src.skills.search_quick.scraper import DuckDuckGoScraper, SearchResult

@pytest.fixture
def scraper():
    return DuckDuckGoScraper()

@pytest.mark.unit
@respx.mock
@pytest.mark.asyncio
async def test_scraper_search_success(scraper):
    mock_html = """
    <html>
        <body>
            <div class="result__body">
                <h2 class="result__title">
                    <a href="https://example.com/1">Title 1</a>
                </h2>
                <div class="result__snippet">Snippet 1</div>
            </div>
            <div class="result__body">
                <h2 class="result__title">
                    <a href="https://example.com/2">Title 2</a>
                </h2>
                <div class="result__snippet">Snippet 2</div>
            </div>
        </body>
    </html>
    """
    respx.post(DuckDuckGoScraper.SEARCH_URL).mock(return_value=httpx.Response(200, text=mock_html))
    
    # O DDG usa POST ou GET dependendo da implementação, o DuckDuckGoScraper usa client.get no código
    # Mas o html.duckduckgo.com/html/ geralmente aceita params no GET.
    # Ah, espere, eu usei client.get(self.SEARCH_URL, params=params) no scraper.py
    
    respx.get(url__startswith=DuckDuckGoScraper.SEARCH_URL).mock(return_value=httpx.Response(200, text=mock_html))

    results = await scraper.search("test query", max_results=2)
    
    assert len(results) == 2
    assert results[0].title == "Title 1"
    assert results[0].url == "https://example.com/1"
    assert results[0].snippet == "Snippet 1"

@pytest.mark.unit
@respx.mock
@pytest.mark.asyncio
async def test_scraper_retry_on_failure(scraper):
    route = respx.get(url__startswith=DuckDuckGoScraper.SEARCH_URL)
    mock_html = '<div class="result__body"><h2 class="result__title"><a href="http://ok">OK</a></h2><div class="result__snippet">OK</div></div>'
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, text=mock_html)
    ]
    
    results = await scraper.search("test retry")
    assert len(results) == 1
    assert route.call_count == 2

@pytest.mark.unit
@respx.mock
@pytest.mark.asyncio
async def test_scraper_max_retries_reached(scraper):
    route = respx.get(url__startswith=DuckDuckGoScraper.SEARCH_URL)
    route.side_effect = [httpx.Response(500), httpx.Response(500), httpx.Response(500)]
    
    with pytest.raises(httpx.HTTPStatusError):
        await scraper.search("test failure")
    
    assert route.call_count == 3
