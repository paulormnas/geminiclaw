import sqlite3
import json
import datetime
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Any
from src.logger import get_logger
from src.session import _retry_db

logger = get_logger(__name__)

@dataclass
class LongTermMemoryEntry:
    """Uma entrada na memória de longo prazo persistida no SQLite."""
    id: str
    key: str
    value: str
    source: str
    importance: float = 0.5
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    last_used: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    use_count: int = 0

class LongTermMemory:
    """Implementa memória de longo prazo usando SQLite."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Inicializa o schema da tabela de memória de longo prazo."""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        last_err = None
        for i in range(5):
            try:
                conn = sqlite3.connect(self.db_path, timeout=300.0)
                try:
                    conn.execute("PRAGMA journal_mode=DELETE")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    conn.execute("PRAGMA busy_timeout=300000")
                    
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS long_term_memory (
                            id          TEXT PRIMARY KEY,
                            key         TEXT NOT NULL,
                            value       TEXT NOT NULL,
                            source      TEXT NOT NULL,
                            importance  REAL NOT NULL DEFAULT 0.5,
                            tags        TEXT NOT NULL DEFAULT '[]',
                            created_at  TEXT NOT NULL,
                            last_used   TEXT NOT NULL,
                            use_count   INTEGER NOT NULL DEFAULT 0
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_ltm_key ON long_term_memory(key)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_ltm_importance ON long_term_memory(importance DESC)")
                    conn.commit()
                    return
                finally:
                    conn.close()
            except sqlite3.OperationalError as e:
                last_err = e
                if "locked" in str(e).lower():
                    time.sleep(1)
                    continue
                raise
        if last_err:
            raise last_err

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=300.0)
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=300000")
        conn.row_factory = sqlite3.Row
        return conn

    @_retry_db()
    def write(self, key: str, value: Any, source: str, importance: float = 0.5, tags: List[str] = []) -> LongTermMemoryEntry:
        """Escreve uma nova entrada na memória de longo prazo."""
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
            use_count=0
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO long_term_memory (id, key, value, source, importance, tags, created_at, last_used, use_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entry.id, entry.key, entry.value, entry.source, entry.importance, json.dumps(entry.tags), entry.created_at, entry.last_used, entry.use_count)
                )
        finally:
            conn.close()
        
        logger.info(f"Memória de longo prazo registrada: {key} (fonte: {source})")
        return entry

    @_retry_db()
    def read(self, key: str) -> Optional[LongTermMemoryEntry]:
        """Lê a entrada mais recente com a chave especificada e atualiza estatísticas."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "SELECT * FROM long_term_memory WHERE key = ? ORDER BY created_at DESC LIMIT 1",
                (key,)
            )
            row = cursor.fetchone()
            
            if row:
                # Atualiza metadados de uso
                conn.execute(
                    "UPDATE long_term_memory SET last_used = ?, use_count = use_count + 1 WHERE id = ?",
                    (now, row["id"])
                )
                conn.commit()
                
                return LongTermMemoryEntry(
                    id=row["id"],
                    key=row["key"],
                    value=row["value"],
                    source=row["source"],
                    importance=row["importance"],
                    tags=json.loads(row["tags"]),
                    created_at=row["created_at"],
                    last_used=now,
                    use_count=row["use_count"] + 1
                )
            conn.commit()
        finally:
            conn.close()
        return None

    @_retry_db()
    def search(self, tags: List[str] = [], min_importance: float = 0.0, limit: int = 10) -> List[LongTermMemoryEntry]:
        """Busca entradas por tags e importância mínima."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM long_term_memory WHERE importance >= ?"
            params: List[Any] = [min_importance]
            
            if tags:
                # Busca simplificada: deve conter ao menos uma das tags
                tag_filters = " OR ".join(["tags LIKE ?" for _ in tags])
                query += f" AND ({tag_filters})"
                for tag in tags:
                    params.append(f'%"{tag}"%')
            
            query += " ORDER BY importance DESC, created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            
            return [
                LongTermMemoryEntry(
                    id=row["id"],
                    key=row["key"],
                    value=row["value"],
                    source=row["source"],
                    importance=row["importance"],
                    tags=json.loads(row["tags"]),
                    created_at=row["created_at"],
                    last_used=row["last_used"],
                    use_count=row["use_count"]
                )
                for row in rows
            ]
        finally:
            conn.close()

    @_retry_db()
    def update_importance(self, key: str, delta: float) -> bool:
        """Ajusta a importância de uma entrada."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id, importance FROM long_term_memory WHERE key = ? ORDER BY created_at DESC LIMIT 1", (key,))
            row = cursor.fetchone()
            if row:
                new_importance = max(0.0, min(1.0, row["importance"] + delta))
                conn.execute("UPDATE long_term_memory SET importance = ? WHERE id = ?", (new_importance, row["id"]))
                conn.commit()
                return True
        return False

    def forget(self, key: str) -> int:
        """Remove entradas com a chave especificada."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM long_term_memory WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount

    def summarize_for_context(self, limit: int = 5) -> str:
        """Gera um resumo textual das memórias mais importantes para o contexto."""
        memories = self.search(min_importance=0.7, limit=limit)
        if not memories:
            return ""
        
        summary = "Memórias de longo prazo relevantes:\n"
        for m in memories:
            summary += f"- {m.key}: {m.value}\n"
        return summary
