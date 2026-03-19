import sqlite3
import json
import datetime
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class Session:
    """Representação de uma sessão de agente."""
    id: str
    agent_id: str
    status: str
    created_at: str
    updated_at: str
    payload: dict[str, Any]

def init_db(db_path: str) -> None:
    """Inicializa o banco de dados SQLite com schema e PRAGMAs otimizados.

    Args:
        db_path: Caminho para o arquivo do banco de dados.
    """
    db_dir = Path(db_path).parent
    if not db_dir.exists():
        db_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=TRUNCATE")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-32000")  # ~32MB
        
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

class SessionManager:
    """Gerenciador de sessões persistidas no SQLite."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        init_db(self.db_path)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        # PRAGMAs que devem ser definidos por conexão
        conn.execute("PRAGMA journal_mode=TRUNCATE")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA mmap_size=0")
        return conn

    def create(self, agent_id: str) -> Session:
        """Cria uma nova sessão para o agente.

        Args:
            agent_id: Identificador do agente.

        Returns:
            O objeto Session criado.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        session = Session(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            status="active",
            created_at=now,
            updated_at=now,
            payload={}
        )

        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO agent_sessions (id, agent_id, status, created_at, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (session.id, session.agent_id, session.status, session.created_at, session.updated_at, json.dumps(session.payload))
            )
            conn.commit()
        return session

    def get(self, session_id: str) -> Session | None:
        """Recupera uma sessão pelo seu ID.

        Args:
            session_id: ID da sessão.

        Returns:
            O objeto Session ou None se não encontrado.
        """
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            
            if row:
                return Session(
                    id=row["id"],
                    agent_id=row["agent_id"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    payload=json.loads(row["payload"])
                )
        return None

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
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
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
