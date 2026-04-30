"""Cache persistente para consultas ao índice vetorial (Deep Search).

Substitui a implementação anterior baseada em sqlite_utils.
Os resultados são armazenados na tabela ``deep_search_cache`` criada
pelo ``scripts/init_db.sql``.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from src.db import get_connection


class DeepSearchCache:
    """Cache persistente para consultas ao índice vetorial."""

    def get(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Recupera resultados do cache se existirem e não estiverem expirados.

        Args:
            query: Consulta original realizada.
            filters: Filtros aplicados à consulta (opcional).

        Returns:
            Lista de resultados deserializados ou None se não encontrado/expirado.
        """
        query_hash = self._generate_hash(query, filters)
        now = datetime.now(timezone.utc)

        with get_connection() as conn:
            row = conn.execute(
                "SELECT results, expires_at FROM deep_search_cache WHERE query_hash = %s",
                (query_hash,),
            ).fetchone()

        if row is None:
            return None

        expires_at = row["expires_at"]
        # expires_at pode vir como datetime (TIMESTAMPTZ) ou string
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at > now:
            results = row["results"]
            if isinstance(results, str):
                results = json.loads(results)
            return results
        else:
            # Expirado — remove entrada
            with get_connection() as conn:
                conn.execute(
                    "DELETE FROM deep_search_cache WHERE query_hash = %s",
                    (query_hash,),
                )

        return None

    def set(
        self,
        query: str,
        results: List[Dict[str, Any]],
        ttl_seconds: int = 86400,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Armazena resultados no cache.

        Args:
            query: Consulta original realizada.
            results: Lista de resultados a armazenar.
            ttl_seconds: Tempo de vida em segundos (padrão: 86400 = 1 dia).
            filters: Filtros aplicados à consulta (opcional).
        """
        query_hash = self._generate_hash(query, filters)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO deep_search_cache
                    (query_hash, query, results, expires_at, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (query_hash) DO UPDATE SET
                    results    = EXCLUDED.results,
                    expires_at = EXCLUDED.expires_at,
                    created_at = EXCLUDED.created_at
                """,
                (
                    query_hash,
                    query,
                    json.dumps(results),
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )

    def _generate_hash(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Gera um hash único para a query e filtros.

        Args:
            query: Consulta normalizada.
            filters: Filtros adicionais (opcional).

        Returns:
            String hexadecimal SHA-256.
        """
        data = {"query": query.strip().lower(), "filters": filters or {}}
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def clear_expired(self) -> None:
        """Remove todas as entradas expiradas do cache."""
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM deep_search_cache WHERE expires_at < %s",
                (now,),
            )
