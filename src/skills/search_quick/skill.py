import os
from typing import List, Optional
from src.logger import get_logger
from ..base import BaseSkill, SkillResult
from .scraper import DuckDuckGoScraper, SearchResult
from .ddg_lite import DuckDuckGoLiteScraper
from .brave import BraveSearchClient
from .cache import SearchCache

logger = get_logger(__name__)

class QuickSearchSkill(BaseSkill):
    """Skill de busca rápida que utiliza múltiplos backends com fallback."""
    
    name = "quick_search"
    description = (
        "Use esta skill para buscar informações atuais na internet de forma rápida. "
        "Forneça uma query específica. Retorna títulos, URLs e resumos dos primeiros resultados."
    )

    def __init__(self, timeout: Optional[int] = None, ttl: Optional[int] = None):
        search_timeout = timeout or int(os.getenv("QUICK_SEARCH_TIMEOUT_SECONDS", "10"))
        cache_ttl = ttl or int(os.getenv("QUICK_SEARCH_CACHE_TTL_SECONDS", "3600"))
        
        self.strategy = os.getenv("QUICK_SEARCH_STRATEGY", "ddg,ddg_lite,brave").split(",")
        self.backends = {}
        
        if "ddg" in self.strategy:
            self.backends["ddg"] = DuckDuckGoScraper(timeout=search_timeout)
        if "ddg_lite" in self.strategy:
            self.backends["ddg_lite"] = DuckDuckGoLiteScraper(timeout=search_timeout)
        if "brave" in self.strategy:
            self.backends["brave"] = BraveSearchClient(timeout=search_timeout)
            
        self.cache = SearchCache(ttl=cache_ttl)

    async def run(self, query: str, max_results: int = 5) -> SkillResult:
        """Executa a busca, verificando o cache e tentando os backends em cascata.

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
                return SkillResult(
                    success=True, 
                    output=[r.__dict__ for r in cached_results[:max_results]],
                    metadata={"source": "cache"}
                )

            # 2. Tentar backends em ordem (fallback)
            results = []
            errors = []
            successful_backend = None
            
            for backend_name in self.strategy:
                backend = self.backends.get(backend_name.strip())
                if not backend:
                    continue
                    
                try:
                    logger.info(f"Tentando busca rápida com backend: {backend_name}")
                    results = await backend.search(query, max_results=max_results)
                    if results:
                        successful_backend = backend_name
                        break
                    else:
                        errors.append(f"{backend_name} retornou 0 resultados.")
                except Exception as e:
                    logger.warning(f"Backend {backend_name} falhou: {e}")
                    errors.append(f"{backend_name} error: {str(e)}")
            
            if not results:
                return SkillResult(
                    success=False, 
                    output=[], 
                    error=f"Todos os backends falharam ou retornaram vazio. Erros: {errors}"
                )
                
            # 3. Armazenar no cache
            self.cache.set(query, results)
            
            return SkillResult(
                success=True,
                output=[r.__dict__ for r in results],
                metadata={"source": successful_backend}
            )
        except Exception as e:
            return SkillResult(success=False, output=[], error=str(e))
