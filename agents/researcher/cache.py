"""Cache de resultados de busca com TTL configurável.

Armazena resultados em memória para evitar chamadas redundantes
ao Gemini CLI durante uma sessão do agente researcher.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from src.logger import get_logger
from src.config import SEARCH_CACHE_TTL_SECONDS

logger = get_logger(__name__)


@dataclass
class _CacheEntry:
    """Entrada individual do cache com timestamp de criação.

    Args:
        value: Resultado da busca.
        created_at: Timestamp Unix da criação.
    """

    value: str
    created_at: float


class SearchCache:
    """Cache em memória para resultados de busca com expiração por TTL.

    O cache é volátil — perdido quando o container reinicia.
    Isso é intencional: cada sessão de agente é efêmera.

    Args:
        ttl_seconds: Tempo de vida dos resultados em segundos.
                     Padrão: valor de SEARCH_CACHE_TTL_SECONDS (3600s).
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        """Inicializa o cache com TTL configurável.

        Args:
            ttl_seconds: Tempo de vida em segundos. Se None, usa o valor
                         da variável de ambiente SEARCH_CACHE_TTL_SECONDS.
        """
        self._ttl = ttl_seconds if ttl_seconds is not None else SEARCH_CACHE_TTL_SECONDS
        self._store: dict[str, _CacheEntry] = {}
        logger.info(
            "SearchCache inicializado",
            extra={"ttl_seconds": self._ttl},
        )

    @property
    def ttl(self) -> int:
        """Retorna o TTL configurado em segundos."""
        return self._ttl

    def get(self, query: str) -> str | None:
        """Busca um resultado no cache.

        Args:
            query: Query de busca usada como chave.

        Returns:
            Resultado cacheado se existir e estiver dentro do TTL,
            ou None caso contrário.
        """
        normalized = query.strip().lower()
        entry = self._store.get(normalized)

        if entry is None:
            return None

        elapsed = time.monotonic() - entry.created_at
        if elapsed > self._ttl:
            # Entrada expirada — remove do cache
            del self._store[normalized]
            logger.info(
                "Cache expirado",
                extra={"query": normalized[:50], "elapsed_seconds": round(elapsed, 1)},
            )
            return None

        logger.info(
            "Cache hit",
            extra={"query": normalized[:50]},
        )
        return entry.value

    def set(self, query: str, result: str) -> None:
        """Armazena um resultado no cache.

        Args:
            query: Query de busca usada como chave.
            result: Resultado a ser cacheado.
        """
        normalized = query.strip().lower()
        self._store[normalized] = _CacheEntry(
            value=result,
            created_at=time.monotonic(),
        )
        logger.info(
            "Cache set",
            extra={"query": normalized[:50], "cache_size": len(self._store)},
        )

    def clear(self) -> None:
        """Remove todas as entradas do cache."""
        count = len(self._store)
        self._store.clear()
        logger.info("Cache limpo", extra={"removed_entries": count})
