import httpx
import asyncio
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import List, Optional
from src.logger import get_logger

logger = get_logger(__name__)

@dataclass
class SearchResult:
    """Representa um resultado de busca individual."""
    title: str
    url: str
    snippet: str

class DuckDuckGoScraper:
    """Scraper para o DuckDuckGo que extrai resultados de busca sem API."""
    
    SEARCH_URL = "https://html.duckduckgo.com/html/"
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Realiza uma busca no DuckDuckGo.

        Args:
            query: Termo de busca.
            max_results: Número máximo de resultados a retornar.

        Returns:
            List[SearchResult]: Lista de resultados encontrados.
        """
        params = {"q": query}
        
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.get(self.SEARCH_URL, params=params)
                    response.raise_for_status()
                    return self._parse_results(response.text, max_results)
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(f"Erro na busca (tentativa {attempt + 1}/3): {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)  # Backoff exponencial
        
        return []

    def _parse_results(self, html: str, max_results: int) -> List[SearchResult]:
        """Parseia o HTML do DuckDuckGo e extrai os resultados."""
        soup = BeautifulSoup(html, "lxml")
        results = []
        
        # O seletor .links_main.result__body é o padrão para os resultados no HTML do DDG
        for result in soup.select(".result__body")[:max_results]:
            title_tag = result.select_one(".result__title a")
            snippet_tag = result.select_one(".result__snippet")
            
            if title_tag and snippet_tag:
                title = title_tag.get_text(strip=True)
                url = title_tag["href"]
                snippet = snippet_tag.get_text(strip=True)
                
                # O DDG às vezes usa links internos ou redirecionamentos, pegamos o destino final se possível
                if url.startswith("//"):
                    url = "https:" + url
                
                results.append(SearchResult(title=title, url=url, snippet=snippet))
        
        return results
