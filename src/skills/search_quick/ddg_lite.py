import httpx
import asyncio
from bs4 import BeautifulSoup
from typing import List
from src.logger import get_logger
from .scraper import SearchResult

logger = get_logger(__name__)

class DuckDuckGoLiteScraper:
    """Scraper para a versão Lite do DuckDuckGo (HTML simplificado)."""
    
    SEARCH_URL = "https://lite.duckduckgo.com/lite/"
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded"
        }

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        data = {"q": query}
        
        for attempt in range(3):
            try:
                # DDG Lite frequentemente usa POST na home form
                async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.post(self.SEARCH_URL, data=data)
                    response.raise_for_status()
                    return self._parse_results(response.text, max_results)
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(f"Erro na busca DDG Lite (tentativa {attempt + 1}/3): {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        return []

    def _parse_results(self, html: str, max_results: int) -> List[SearchResult]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        
        # DDG Lite exibe resultados em tabelas <tr>
        for tr in soup.find_all("tr"):
            td_result = tr.find("td", class_="result-snippet")
            if not td_result:
                continue
                
            prev_tr = tr.find_previous_sibling("tr")
            if not prev_tr:
                continue
                
            title_tag = prev_tr.find("a", class_="result-url") or prev_tr.find("a")
            if title_tag and "href" in title_tag.attrs:
                title = title_tag.get_text(strip=True)
                url = title_tag["href"]
                snippet = td_result.get_text(strip=True)
                
                if url.startswith("//"):
                    url = "https:" + url
                    
                results.append(SearchResult(title=title, url=url, snippet=snippet))
                
            if len(results) >= max_results:
                break
                
        return results
