"""Cache de respostas do LLM baseado em PostgreSQL.

Substitui a implementação anterior baseada em SQLite (sqlite3).
Usa hash SHA-256 (prompt + model) como chave primária.
Suporta TTL e limite máximo de entradas (FIFO eviction).

As tabelas ``llm_cache`` e ``llm_cache_stats`` são criadas pelo
``scripts/init_db.sql``.
"""

import hashlib
import time
from typing import Optional, Dict, Any

from src.logger import get_logger
from src.db import get_connection

logger = get_logger(__name__)


class LLMResponseCache:
    """Implementa um cache PostgreSQL para respostas do LLM.

    Usa um hash SHA-256 (prompt + model) como chave.
    Suporta TTL e limite máximo de entradas (FIFO eviction).
    """

    def __init__(self):
        """Inicializa o cache lendo configurações de variáveis de ambiente."""
        import os
        self.enabled = str(os.environ.get("LLM_CACHE_ENABLED", "true")).lower() == "true"
        self.ttl_seconds = int(os.environ.get("LLM_CACHE_TTL_SECONDS", "3600"))
        self.max_entries = int(os.environ.get("LLM_CACHE_MAX_ENTRIES", "1000"))

        if self.enabled:
            logger.info(
                "LLMResponseCache inicializado",
                extra={"extra": {"ttl": self.ttl_seconds, "max_entries": self.max_entries}},
            )

    def _generate_hash(self, prompt: str, model: str) -> str:
        """Gera o hash SHA-256 normalizado para a chave.

        Args:
            prompt: Prompt enviado ao LLM.
            model: Modelo utilizado.

        Returns:
            String hexadecimal do hash SHA-256.
        """
        raw = f"{model}:{prompt.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, prompt: str, model: str) -> Optional[str]:
        """Obtém uma resposta do cache se existir e estiver válida.

        Args:
            prompt: Prompt enviado ao LLM.
            model: Modelo utilizado.

        Returns:
            String com a resposta cacheada ou None se não existir/expirado.
        """
        if not self.enabled:
            return None

        hash_key = self._generate_hash(prompt, model)
        current_time = time.time()

        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT response, timestamp FROM llm_cache WHERE hash_key = %s",
                    (hash_key,),
                ).fetchone()

                if row:
                    age = current_time - row["timestamp"]
                    if age <= self.ttl_seconds:
                        conn.execute(
                            "UPDATE llm_cache_stats SET hits = hits + 1 WHERE id = 1"
                        )
                        logger.info(
                            "LLM Cache HIT",
                            extra={"extra": {"hash": hash_key[:8], "age_seconds": round(age, 2)}},
                        )
                        return row["response"]
                    else:
                        # Expirou — apaga e contabiliza como miss
                        conn.execute(
                            "DELETE FROM llm_cache WHERE hash_key = %s",
                            (hash_key,),
                        )

                # Miss
                conn.execute(
                    "UPDATE llm_cache_stats SET misses = misses + 1 WHERE id = 1"
                )
                logger.info("LLM Cache MISS", extra={"extra": {"hash": hash_key[:8]}})
                return None
        except Exception as e:
            logger.error("Erro ao ler LLM cache", extra={"error": str(e)})
            return None

    def set(self, prompt: str, model: str, response: str) -> None:
        """Armazena ou atualiza uma resposta no cache e aplica eviction se necessário.

        V12.1.2: Respostas vazias, compostas apenas de espaços ou com menos de
        51 caracteres são rejeitadas — elas correspondem a erros ou respostas
        triviais que nunca devem ser cacheadas.

        Args:
            prompt: Prompt enviado ao LLM.
            model: Modelo utilizado.
            response: Resposta do LLM.
        """
        if not self.enabled:
            return

        # V12.1.2 — Nunca cachear respostas vazias ou trivialmente curtas
        if not response or len(response.strip()) <= 50:
            logger.debug(
                "Cache SET ignorado: resposta vazia ou muito curta",
                extra={"extra": {"response_len": len(response.strip()) if response else 0}},
            )
            return

        hash_key = self._generate_hash(prompt, model)
        current_time = time.time()

        try:
            with get_connection() as conn:
                # Inserir ou atualizar (upsert)
                conn.execute(
                    """
                    INSERT INTO llm_cache (hash_key, prompt, model, response, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (hash_key) DO UPDATE SET
                        response = EXCLUDED.response,
                        timestamp = EXCLUDED.timestamp
                    """,
                    (hash_key, prompt, model, response, current_time),
                )

                # Checar eviction
                count_row = conn.execute("SELECT COUNT(*) AS cnt FROM llm_cache").fetchone()
                count = count_row["cnt"] if count_row else 0

                if count > self.max_entries:
                    to_delete = count - self.max_entries
                    conn.execute(
                        """
                        DELETE FROM llm_cache
                        WHERE hash_key IN (
                            SELECT hash_key FROM llm_cache
                            ORDER BY timestamp ASC
                            LIMIT %s
                        )
                        """,
                        (to_delete,),
                    )
                    logger.debug(
                        "LLM Cache Eviction rodou",
                        extra={"extra": {"removed": to_delete}},
                    )

            logger.info("LLM Cache SET", extra={"extra": {"hash": hash_key[:8]}})
        except Exception as e:
            logger.error("Erro ao gravar no LLM cache", extra={"error": str(e)})

    def invalidate(self, prompt: str, model: str) -> None:
        """Remove uma entrada do cache pelo hash do prompt+model.

        V12.1.3: Chamado antes de iniciar um novo ciclo de replanejamento para
        garantir que hashes de prompts de subtarefas falhas não sejam servidos
        como Cache HIT nas próximas tentativas.

        Args:
            prompt: Prompt cujo cache deve ser invalidado.
            model: Modelo associado ao prompt.
        """
        if not self.enabled:
            return

        hash_key = self._generate_hash(prompt, model)
        try:
            with get_connection() as conn:
                conn.execute(
                    "DELETE FROM llm_cache WHERE hash_key = %s",
                    (hash_key,),
                )
            logger.info(
                "LLM Cache INVALIDADO",
                extra={"extra": {"hash": hash_key[:8]}},
            )
        except Exception as e:
            logger.error("Erro ao invalidar LLM cache", extra={"error": str(e)})

    def stats(self) -> Dict[str, Any]:
        """Retorna as estatísticas de hits/misses do cache.

        Returns:
            Dicionário com hits, misses, hit_rate e total_requests.
        """
        if not self.enabled:
            return {"enabled": False}

        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT hits, misses FROM llm_cache_stats WHERE id = 1"
                ).fetchone()

                if row:
                    hits = row["hits"]
                    misses = row["misses"]
                    total = hits + misses
                    rate = (hits / total) if total > 0 else 0.0
                    return {
                        "enabled": True,
                        "hits": hits,
                        "misses": misses,
                        "hit_rate": round(rate, 4),
                        "total_requests": total,
                    }
        except Exception:
            pass
        return {"enabled": False}
