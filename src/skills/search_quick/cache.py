import hashlib
import time
from typing import Dict, List, Optional, Any, Generic, TypeVar
from src.logger import get_logger
from src.config import SEARCH_CACHE_TTL_SECONDS
from .scraper import SearchResult

logger = get_logger(__name__)

T = TypeVar("T")

class SearchCache(Generic[T]):
    """Cache em memória para resultados de busca com TTL.
    
    Utiliza monotonic time para evitar problemas com saltos no relógio do sistema.
    """
    
    def __init__(self, ttl: Optional[int] = None):
        self._ttl = ttl if ttl is not None else SEARCH_CACHE_TTL_SECONDS
        self._cache: Dict[str, Dict[str, Any]] = {}
        logger.info("SearchCache inicializado", extra={"ttl_seconds": self._ttl})

    @property
    def ttl(self) -> int:
        """Retorna o TTL configurado."""
        return self._ttl

    def _get_key(self, query: str) -> str:
        """Gera uma chave única para a query baseada em hash SHA-256."""
        normalized = query.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()

    def get(self, query: str) -> Optional[T]:
        """Recupera resultados do cache se ainda forem válidos."""
        key = self._get_key(query)
        entry = self._cache.get(key)
        
        if entry:
            elapsed = time.monotonic() - entry["timestamp"]
            if elapsed < self._ttl:
                logger.info("Cache hit", extra={"query": query[:50]})
                return entry["results"]
            else:
                # Cache expirado
                del self._cache[key]
                logger.info("Cache expirado", extra={"query": query[:50], "elapsed": round(elapsed, 1)})
        
        return None

    def set(self, query: str, results: T) -> None:
        """Armazena resultados no cache com o timestamp atual."""
        key = self._get_key(query)
        self._cache[key] = {
            "results": results,
            "timestamp": time.monotonic()
        }
        logger.info("Cache set", extra={"query": query[:50], "size": len(self._cache)})

    def invalidate(self, query: str) -> None:
        """Remove explicitamente uma entrada do cache."""
        key = self._get_key(query)
        if key in self._cache:
            del self._cache[key]

    def clear(self) -> None:
        """Limpa todo o cache."""
        count = len(self._cache)
        self._cache.clear()
        logger.info("Cache limpo", extra={"removed": count})
