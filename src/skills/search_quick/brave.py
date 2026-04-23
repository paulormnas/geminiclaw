import os
import httpx
import asyncio
from typing import List
from src.logger import get_logger
from .scraper import SearchResult

logger = get_logger(__name__)

class BraveSearchClient:
    """Cliente para a API do Brave Search."""
    
    SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.api_key = os.environ.get("BRAVE_API_KEY")
        self.headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip"
        }
        if self.api_key:
            self.headers["X-Subscription-Token"] = self.api_key

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        if not self.api_key:
            logger.info("BRAVE_API_KEY não configurada. Ignorando busca no Brave.")
            return []
            
        params = {"q": query, "count": min(max_results, 20)}
        
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout) as client:
                    response = await client.get(self.SEARCH_URL, params=params)
                    
                    if response.status_code == 401 or response.status_code == 403:
                        logger.error("Falha de autenticação na API do Brave Search.")
                        return []
                        
                    response.raise_for_status()
                    data = response.json()
                    
                    return self._parse_results(data, max_results)
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(f"Erro na busca Brave API (tentativa {attempt + 1}/3): {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        return []

    def _parse_results(self, data: dict, max_results: int) -> List[SearchResult]:
        results = []
        web_results = data.get("web", {}).get("results", [])
        
        for item in web_results[:max_results]:
            title = item.get("title", "")
            url = item.get("url", "")
            snippet = item.get("description", "")
            
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet))
                
        return results
