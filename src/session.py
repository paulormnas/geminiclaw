"""Gerenciador de sessões persistidas no PostgreSQL.

Substitui a implementação anterior baseada em SQLite (sqlite3).
As sessões são armazenadas na tabela ``agent_sessions`` criada pelo
``scripts/init_db.sql``.
"""

import json
import datetime
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from src.db import get_connection
from src.logger import get_logger
from src.skills.memory.long_term import LongTermMemory

logger = get_logger(__name__)


@dataclass
class Session:
    """Representação de uma sessão de agente."""

    id: str
    agent_id: str
    status: str
    created_at: str
    updated_at: str
    payload: dict[str, Any]


class SessionManager:
    """Gerenciador de sessões persistidas no PostgreSQL."""

    def create(self, agent_id: str, session_id: Optional[str] = None) -> Session:
        """Cria uma nova sessão para o agente.

        Args:
            agent_id: Identificador do agente.
            session_id: ID customizado para a sessão (opcional).

        Returns:
            O objeto Session criado com contexto de memória de longo prazo
            se disponível.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        final_id = session_id or str(uuid.uuid4())

        # Carrega resumo da memória de longo prazo
        lt_memory = LongTermMemory()
        lt_summary = lt_memory.summarize_for_context(limit=5)

        payload: dict[str, Any] = {}
        if lt_summary:
            payload["long_term_memory_summary"] = lt_summary

        session = Session(
            id=final_id,
            agent_id=agent_id,
            status="active",
            created_at=now,
            updated_at=now,
            payload=payload,
        )

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_sessions
                    (id, agent_id, status, created_at, updated_at, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    session.id,
                    session.agent_id,
                    session.status,
                    session.created_at,
                    session.updated_at,
                    json.dumps(session.payload),
                ),
            )

        logger.info(
            "Sessão criada",
            extra={"extra": {"session_id": session.id, "agent_id": agent_id}},
        )
        return session

    def get(self, session_id: str) -> Session | None:
        """Recupera uma sessão pelo seu ID.

        Args:
            session_id: ID da sessão.

        Returns:
            O objeto Session ou None se não encontrado.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE id = %s",
                (session_id,),
            ).fetchone()

        if row is not None:
            return Session(
                id=row["id"],
                agent_id=row["agent_id"],
                status=row["status"],
                created_at=row["created_at"] if isinstance(row["created_at"], str) else row["created_at"].isoformat(),
                updated_at=row["updated_at"] if isinstance(row["updated_at"], str) else row["updated_at"].isoformat(),
                payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            )
        return None

    def update(
        self,
        session_id: str,
        status: str | None = None,
        payload: dict | None = None,
    ) -> Session:
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

        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE id = %s",
                (session_id,),
            ).fetchone()

            if not row:
                raise ValueError(f"Sessão '{session_id}' não encontrada.")

            current_status = status if status is not None else row["status"]
            existing_payload = (
                json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            )
            current_payload = payload if payload is not None else existing_payload

            conn.execute(
                """
                UPDATE agent_sessions
                SET status = %s, payload = %s, updated_at = %s
                WHERE id = %s
                """,
                (current_status, json.dumps(current_payload), now, session_id),
            )

        return Session(
            id=session_id,
            agent_id=row["agent_id"],
            status=current_status,
            created_at=row["created_at"] if isinstance(row["created_at"], str) else row["created_at"].isoformat(),
            updated_at=now,
            payload=current_payload,
        )

    def close(self, session_id: str) -> None:
        """Fecha uma sessão (marca como closed).

        Args:
            session_id: ID da sessão.
        """
        self.update(session_id, status="closed")
        logger.info(
            "Sessão encerrada",
            extra={"extra": {"session_id": session_id}},
        )

    def list_active(self) -> list[Session]:
        """Lista todas as sessões ativas.

        Returns:
            Lista de objetos Session com status 'active'.
        """
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_sessions WHERE status = 'active'"
            ).fetchall()

        return [
            Session(
                id=row["id"],
                agent_id=row["agent_id"],
                status=row["status"],
                created_at=row["created_at"] if isinstance(row["created_at"], str) else row["created_at"].isoformat(),
                updated_at=row["updated_at"] if isinstance(row["updated_at"], str) else row["updated_at"].isoformat(),
                payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
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
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_sessions ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()

        return [
            Session(
                id=row["id"],
                agent_id=row["agent_id"],
                status=row["status"],
                created_at=row["created_at"] if isinstance(row["created_at"], str) else row["created_at"].isoformat(),
                updated_at=row["updated_at"] if isinstance(row["updated_at"], str) else row["updated_at"].isoformat(),
                payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_session(row: Any) -> Session:
        return Session(
            id=row["id"],
            agent_id=row["agent_id"],
            status=row["status"],
            created_at=row["created_at"] if isinstance(row["created_at"], str) else row["created_at"].isoformat(),
            updated_at=row["updated_at"] if isinstance(row["updated_at"], str) else row["updated_at"].isoformat(),
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
        )

    def heartbeat(self, session_id: str) -> bool:
        """Batimento da sessão: atualiza só ``updated_at`` (nunca o payload) enquanto ela está ``active``.

        Args:
            session_id: ID da sessão mestra.

        Returns:
            ``True`` se a sessão ainda estava ``active``; ``False`` se outro processo já a marcou
            ``interrompida`` (ou ela foi fechada).
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "UPDATE agent_sessions SET updated_at = %s WHERE id = %s AND status = 'active' RETURNING id",
                (now, session_id),
            ).fetchone()
        return row is not None

    def mark_stale(self, stale_seconds: float) -> list[Session]:
        """Marca ``interrompida`` as sessões mestras ``active`` sem batimento há mais de ``stale_seconds``.

        A transição é atômica e condicional (``status='active'`` e ``updated_at`` antigo no mesmo
        ``UPDATE``): uma sessão viva, cujo batimento chegou entre a leitura e a escrita, não é marcada.
        Só sessões do orquestrador (``agent_id='orchestrator'``) entram; as sessões por agente são efêmeras.

        Returns:
            As sessões marcadas (com o ``status`` já ``interrompida``).
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = (now - datetime.timedelta(seconds=stale_seconds)).isoformat()
        patch = json.dumps({"motivo_parada": "interrompida"})
        with get_connection() as conn:
            rows = conn.execute(
                """
                UPDATE agent_sessions
                SET status = 'interrompida', payload = payload || %s::jsonb, updated_at = %s
                WHERE agent_id = 'orchestrator' AND status = 'active' AND updated_at < %s
                RETURNING *
                """,
                (patch, now.isoformat(), cutoff),
            ).fetchall()
        sessions = [self._row_to_session(r) for r in rows or []]
        for sess in sessions:
            logger.warning("Sessão obsoleta marcada interrompida", extra={"extra": {"session_id": sess.id}})
        return sessions

    def find_continuation(self, session_id: str) -> Session | None:
        """Sessão que continua ``session_id`` (``payload.continues_session_id``), a mais recente, se houver."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE agent_id = 'orchestrator' "
                "AND payload->>'continues_session_id' = %s ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def list_by_project(self, project_id: str, limit: int = 20) -> list[Session]:
        """Sessões mestras do projeto (``payload.project_id``), da mais recente para a mais antiga."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_sessions WHERE agent_id = 'orchestrator' "
                "AND payload->>'project_id' = %s ORDER BY created_at DESC LIMIT %s",
                (project_id, limit),
            ).fetchall()
        return [self._row_to_session(r) for r in rows or []]
