"""Memória de longo prazo persistida no PostgreSQL.

Substitui a implementação anterior baseada em SQLite (sqlite3).
As entradas são armazenadas na tabela ``long_term_memory`` criada
pelo ``scripts/init_db.sql``.
"""

import json
import datetime
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Any

from src.logger import get_logger
from src.db import get_connection

logger = get_logger(__name__)


@dataclass
class LongTermMemoryEntry:
    """Uma entrada na memória de longo prazo persistida no PostgreSQL."""

    id: str
    key: str
    value: str
    source: str
    importance: float = 0.5
    tags: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
    )
    last_used: str = field(
        default_factory=lambda: datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
    )
    use_count: int = 0


def _row_to_entry(row: dict) -> LongTermMemoryEntry:
    """Converte uma row do PostgreSQL em LongTermMemoryEntry.

    Args:
        row: Dicionário retornado pela query (dict_row).

    Returns:
        LongTermMemoryEntry populada.
    """
    def _to_str(v) -> str:
        if isinstance(v, datetime.datetime):
            return v.isoformat()
        return str(v)

    # tags pode vir como list (JSONB) ou string (fallback)
    tags = row["tags"]
    if isinstance(tags, str):
        tags = json.loads(tags)

    return LongTermMemoryEntry(
        id=row["id"],
        key=row["key"],
        value=row["value"],
        source=row["source"],
        importance=float(row["importance"]),
        tags=tags,
        created_at=_to_str(row["created_at"]),
        last_used=_to_str(row["last_used"]),
        use_count=int(row["use_count"]),
    )


class LongTermMemory:
    """Implementa memória de longo prazo usando PostgreSQL."""

    def write(
        self,
        key: str,
        value: Any,
        source: str,
        importance: float = 0.5,
        tags: List[str] = [],
    ) -> LongTermMemoryEntry:
        """Escreve uma nova entrada na memória de longo prazo.

        Args:
            key: Chave identificadora da memória.
            value: Valor a persistir (será serializado para string se não for).
            source: Origem desta entrada (ex: nome do agente).
            importance: Relevância entre 0.0 e 1.0 (padrão: 0.5).
            tags: Lista de tags para categorização.

        Returns:
            LongTermMemoryEntry criada.
        """
        entry_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        entry = LongTermMemoryEntry(
            id=entry_id,
            key=key,
            value=json.dumps(value) if not isinstance(value, str) else value,
            source=source,
            importance=importance,
            tags=tags,
            created_at=now,
            last_used=now,
            use_count=0,
        )

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO long_term_memory
                    (id, key, value, source, importance, tags, created_at, last_used, use_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    entry.id,
                    entry.key,
                    entry.value,
                    entry.source,
                    entry.importance,
                    json.dumps(entry.tags),
                    entry.created_at,
                    entry.last_used,
                    entry.use_count,
                ),
            )

        logger.info(
            f"Memória de longo prazo registrada: {key} (fonte: {source})"
        )
        return entry

    def read(self, key: str) -> Optional[LongTermMemoryEntry]:
        """Lê a entrada mais recente com a chave especificada e atualiza estatísticas.

        Args:
            key: Chave da memória.

        Returns:
            LongTermMemoryEntry mais recente ou None.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM long_term_memory
                WHERE key = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (key,),
            ).fetchone()

            if row:
                conn.execute(
                    """
                    UPDATE long_term_memory
                    SET last_used = %s, use_count = use_count + 1
                    WHERE id = %s
                    """,
                    (now, row["id"]),
                )
                entry = _row_to_entry(row)
                entry.last_used = now
                entry.use_count += 1
                return entry

        return None

    def search(
        self,
        tags: List[str] = [],
        min_importance: float = 0.0,
        limit: int = 10,
    ) -> List[LongTermMemoryEntry]:
        """Busca entradas por importância mínima e tags.

        Args:
            tags: Lista de tags que a entrada deve conter (OR — ao menos uma).
            min_importance: Importância mínima (padrão: 0.0).
            limit: Máximo de resultados.

        Returns:
            Lista de LongTermMemoryEntry ordenadas por importância decrescente.
        """
        with get_connection() as conn:
            if tags:
                # Usa o operador JSONB ?| para verificar se alguma tag existe
                # A coluna tags é JSONB (array de strings)
                placeholders = ", ".join(["%s"] * len(tags))
                query = f"""
                    SELECT * FROM long_term_memory
                    WHERE importance >= %s
                      AND tags ?| ARRAY[{placeholders}]
                    ORDER BY importance DESC, created_at DESC
                    LIMIT %s
                """
                params = [min_importance] + tags + [limit]
            else:
                query = """
                    SELECT * FROM long_term_memory
                    WHERE importance >= %s
                    ORDER BY importance DESC, created_at DESC
                    LIMIT %s
                """
                params = [min_importance, limit]

            rows = conn.execute(query, params).fetchall()

        return [_row_to_entry(row) for row in rows]

    def update_importance(self, key: str, delta: float) -> bool:
        """Ajusta a importância de uma entrada.

        Args:
            key: Chave da memória.
            delta: Variação a aplicar (+/-). Resultado será clampado em [0.0, 1.0].

        Returns:
            True se a entrada foi encontrada e atualizada, False caso contrário.
        """
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, importance FROM long_term_memory
                WHERE key = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (key,),
            ).fetchone()

            if row:
                new_importance = max(0.0, min(1.0, float(row["importance"]) + delta))
                conn.execute(
                    "UPDATE long_term_memory SET importance = %s WHERE id = %s",
                    (new_importance, row["id"]),
                )
                return True

        return False

    def forget(self, key: str) -> int:
        """Remove entradas com a chave especificada.

        Args:
            key: Chave a remover.

        Returns:
            Número de entradas removidas.
        """
        with get_connection() as conn:
            result = conn.execute(
                "DELETE FROM long_term_memory WHERE key = %s",
                (key,),
            )
            return result.rowcount if result.rowcount is not None else 0

    def summarize_for_context(self, limit: int = 5) -> str:
        """Gera um resumo textual das memórias mais importantes para o contexto.

        Args:
            limit: Máximo de memórias a incluir no resumo.

        Returns:
            String com o resumo, ou string vazia se não houver memórias relevantes.
        """
        memories = self.search(min_importance=0.7, limit=limit)
        if not memories:
            return ""

        summary = "Memórias de longo prazo relevantes:\n"
        for m in memories:
            summary += f"- {m.key}: {m.value}\n"
        return summary
