import sqlite3
import json
import datetime
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any, Optional

@dataclass
class Session:
    """Representação de uma sessão de agente."""
    id: str
    agent_id: str
    status: str
    created_at: str
    updated_at: str
    payload: dict[str, Any]

import functools
import time

def _retry_db(max_retries: int = 10, delay: float = 1.0):
    """Decorator para repetir operações de banco em caso de lock ou I/O error."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_err: Optional[Exception] = None
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
                    last_err = e
                    err_msg = str(e).lower()
                    if "locked" in err_msg or "io error" in err_msg or "i/o error" in err_msg or "malformed" in err_msg:
                        time.sleep(delay * (i + 1))
                        continue
                    raise
            if last_err:
                raise last_err
            return None
        return wrapper
    return decorator

def init_db(db_path: str) -> None:
    """Inicializado o banco apenas se necessário."""
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    
    last_err = None
    for i in range(5):
        try:
            conn = sqlite3.connect(db_path, timeout=300.0)
            try:
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=300000")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_sessions (
                        id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        payload TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_id ON agent_sessions(agent_id)")
                conn.commit()
                return
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" in str(e):
                time.sleep(1)
                continue
            raise
    pass

class SessionManager:
    """Gerenciador de sessões persistidas no SQLite."""

    def __init__(self, db_path: str, lt_memory_db_path: Optional[str] = None):
        self.db_path = db_path
        self.lt_memory_db_path = lt_memory_db_path or db_path.replace("sessions.db", "memory.db")
        init_db(self.db_path)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=300.0)
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=300000")
        return conn

    @_retry_db()
    def create(self, agent_id: str) -> Session:
        """Cria uma nova sessão para o agente.

        Args:
            agent_id: Identificador do agente.

        Returns:
            O objeto Session criado com contexto de memória de longo prazo se disponível.
        """
        from src.skills.memory.long_term import LongTermMemory
        
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        # Carrega resumo da memória de longo prazo
        lt_memory = LongTermMemory(self.lt_memory_db_path)
        lt_summary = lt_memory.summarize_for_context(limit=5)
        
        payload = {}
        if lt_summary:
            payload["long_term_memory_summary"] = lt_summary

        session = Session(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            status="active",
            created_at=now,
            updated_at=now,
            payload=payload
        )

        conn = self._get_connection()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO agent_sessions (id, agent_id, status, created_at, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
                    (session.id, session.agent_id, session.status, session.created_at, session.updated_at, json.dumps(session.payload))
                )
        finally:
            conn.close()
        return session

    @_retry_db()
    def get(self, session_id: str) -> Session | None:
        """Recupera uma sessão pelo seu ID.

        Args:
            session_id: ID da sessão.

        Returns:
            O objeto Session ou None se não encontrado.
        """
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            
            if row is not None:
                return Session(
                    id=row["id"],
                    agent_id=row["agent_id"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    payload=json.loads(row["payload"])
                )
            return None
        finally:
            conn.close()

    @_retry_db()
    def update(self, session_id: str, status: str | None = None, payload: dict | None = None) -> Session:
        """Atualiza o estado ou payload de uma sessão.

        Args:
            session_id: ID da sessão.
            status: Novo status (opcional).
            payload: Novo payload (opcional).

        Returns:
            O objeto Session atualizado.

        Raises:
            ValueError: Se a sessão não existir.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        conn = self._get_connection()
        try:
            conn.row_factory = sqlite3.Row
            # Inicia a transação IMEDIATA antes de qualquer SELECT para evitar deadlocks
            conn.execute("BEGIN IMMEDIATE")
            
            row = conn.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
            if not row:
                raise ValueError(f"Sessão '{session_id}' não encontrada.")

            current_status = status if status is not None else row["status"]
            current_payload = payload if payload is not None else json.loads(row["payload"])

            conn.execute(
                "UPDATE agent_sessions SET status = ?, payload = ?, updated_at = ? WHERE id = ?",
                (current_status, json.dumps(current_payload), now, session_id)
            )
            conn.commit()

            return Session(
                id=session_id,
                agent_id=row["agent_id"],
                status=current_status,
                created_at=row["created_at"],
                updated_at=now,
                payload=current_payload
            )
        finally:
            conn.close()

    @_retry_db()
    def close(self, session_id: str) -> None:
        """Fecha uma sessão (marca como closed).

        Args:
            session_id: ID da sessão.
        """
        self.update(session_id, status="closed")

    def list_active(self) -> list[Session]:
        """Lista todas as sessões ativas.

        Returns:
            Lista de objetos Session.
        """
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM agent_sessions WHERE status = 'active'")
            rows = cursor.fetchall()
            
            return [
                Session(
                    id=row["id"],
                    agent_id=row["agent_id"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    payload=json.loads(row["payload"])
                )
                for row in rows
            ]

    def list_recent(self, limit: int = 10) -> list[Session]:
        """Lista as sessões mais recentes (ativas ou fechadas).

        Args:
            limit: Quantidade máxima de sessões a retornar.

        Returns:
            Lista de objetos Session ordenados por criação descrescente.
        """
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM agent_sessions ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            
            return [
                Session(
                    id=row["id"],
                    agent_id=row["agent_id"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    payload=json.loads(row["payload"])
                )
                for row in rows
            ]
