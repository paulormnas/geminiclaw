import os
from typing import List, Optional
from ..base import BaseSkill, SkillResult
from .scraper import DuckDuckGoScraper, SearchResult
from .cache import SearchCache

class QuickSearchSkill(BaseSkill):
    """Skill de busca rápida que utiliza o DuckDuckGo via scraping."""
    
    name = "quick_search"
    description = (
        "Use esta skill para buscar informações atuais na internet de forma rápida. "
        "Forneça uma query específica. Retorna títulos, URLs e resumos dos primeiros resultados."
    )

    def __init__(self, timeout: Optional[int] = None, ttl: Optional[int] = None):
        search_timeout = timeout or int(os.getenv("QUICK_SEARCH_TIMEOUT_SECONDS", "10"))
        cache_ttl = ttl or int(os.getenv("QUICK_SEARCH_CACHE_TTL_SECONDS", "3600"))
        
        self.scraper = DuckDuckGoScraper(timeout=search_timeout)
        self.cache = SearchCache(ttl=cache_ttl)

    async def run(self, query: str, max_results: int = 5) -> SkillResult:
        """Executa a busca, verificando o cache primeiro.

        Args:
            query: Termo de busca.
            max_results: Número máximo de resultados (default 5).

        Returns:
            SkillResult: Sucesso, lista de resultados ou erro.
        """
        if not query:
            return SkillResult(success=False, output=[], error="A query de busca não pode estar vazia.")

        try:
            # 1. Tentar recuperar do cache
            cached_results = self.cache.get(query)
            if cached_results:
                # No cache, retornamos apenas o número solicitado
                return SkillResult(
                    success=True, 
                    output=[r.__dict__ for r in cached_results[:max_results]],
                    metadata={"source": "cache"}
                )

            # 2. Realizar a busca se não estiver no cache
            results = await self.scraper.search(query, max_results=max_results)
            
            # 3. Armazenar no cache
            self.cache.set(query, results)
            
            return SkillResult(
                success=True,
                output=[r.__dict__ for r in results],
                metadata={"source": "scraper"}
            )
        except Exception as e:
            return SkillResult(success=False, output=[], error=str(e))
