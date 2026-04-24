from typing import Any, Dict, List, Optional
from src.skills.base import BaseSkill, SkillResult
from .indexer import VectorIndexer
from .cache import DeepSearchCache
from src.logger import get_logger

logger = get_logger(__name__)

class DeepSearchSkill(BaseSkill):
    """Skill para busca profunda em bases de conhecimento indexadas localmente."""

    name = "deep_search"
    description = (
        "Use esta skill para buscar em profundidade dentro de fontes indexadas e confiáveis. "
        "Forneça uma query em linguagem natural. Opcionalmente filtre por domínio. "
        "Retorna trechos relevantes com fonte e score de relevância."
    )

    def __init__(self, indexer: Optional[VectorIndexer] = None, cache: Optional[DeepSearchCache] = None):
        self.indexer = indexer or VectorIndexer()
        self.cache = cache or DeepSearchCache()

    async def run(self, query: str, domain: Optional[str] = None, limit: int = 5, **kwargs) -> SkillResult:
        """Executa a busca profunda."""
        try:
            # Verifica cache primeiro
            cached_results = self.cache.get(query, {"domain": domain})
            if cached_results:
                logger.info(f"Resultados de busca profunda recuperados do cache para: {query}")
                return SkillResult(success=True, output=cached_results, metadata={"source": "cache"})

            # Realiza busca no índice
            results = await self.indexer.search(query, limit=limit, domain=domain)
            
            # Armazena no cache
            self.cache.set(query, results, filters={"domain": domain})
            
            return SkillResult(
                success=True, 
                output=results, 
                metadata={"source": "index", "count": len(results)}
            )

        except Exception as e:
            logger.error(f"Erro na execução da DeepSearchSkill: {e}")
            return SkillResult(success=False, output=[], error=str(e))
