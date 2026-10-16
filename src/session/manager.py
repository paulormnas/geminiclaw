"""Gerenciador de sessões persistidas no PostgreSQL.

Substitui a implementação anterior baseada em SQLite (sqlite3).
As sessões são armazenadas na tabela ``agent_sessions`` criada pelo
``scripts/init_db.sql``.
"""

import dataclasses
import datetime
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional

from src.db import get_connection
from src.logger import get_logger
from src.session.states import FINISHED_STATUSES

logger = get_logger(__name__)


@dataclass
class Session:
    """Representação de uma sessão de agente.

    Os campos do processo (``pid`` em diante) são preenchidos pelo processo da sessão mestra
    (v18.7-background-sessions); ``resumo`` é a tarefa da pesquisa em poucas linhas, para as listas do terminal.
    """

    id: str
    agent_id: str
    status: str
    created_at: str
    updated_at: str
    payload: dict[str, Any]
    pid: int | None = None
    host: str | None = None
    process_started_at: str | None = None
    loop_beat_at: str | None = None
    terminal_id: str | None = None
    alias: str | None = None
    resumo: str | None = None


def _col(row: Any, key: str) -> Any:
    """Coluna opcional da linha (``None`` se o banco ainda não tem a coluna)."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else value.isoformat()


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

        # Carrega resumo da memória de longo prazo (import tardio: o REPL não carrega embeddings ao abrir)
        from src.skills.memory.long_term import LongTermMemory

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
            return self._row_to_session(row)
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

        return dataclasses.replace(
            self._row_to_session(row), status=current_status, updated_at=now, payload=current_payload
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

        return [self._row_to_session(row) for row in rows]

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

        return [self._row_to_session(row) for row in rows]

    @staticmethod
    def _row_to_session(row: Any) -> Session:
        return Session(
            id=row["id"],
            agent_id=row["agent_id"],
            status=row["status"],
            created_at=_iso(row["created_at"]) or "",
            updated_at=_iso(row["updated_at"]) or "",
            payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            pid=_col(row, "pid"),
            host=_col(row, "host"),
            process_started_at=_iso(_col(row, "process_started_at")),
            loop_beat_at=_iso(_col(row, "loop_beat_at")),
            terminal_id=_col(row, "terminal_id"),
            alias=_col(row, "alias"),
            resumo=_col(row, "resumo"),
        )

    def heartbeat(self, session_id: str, loop_beat_at: str | None = None) -> bool:
        """Batimento da sessão: atualiza só ``updated_at`` (nunca o payload) enquanto ela está ``active``.

        Args:
            session_id: ID da sessão mestra.
            loop_beat_at: Último sinal do laço (``ISO 8601``); quando informado, grava ``loop_beat_at`` junto
                (v18.7-background-sessions §1.8: quem confere vê há quanto tempo o laço não dá sinal).

        Returns:
            ``True`` se a sessão ainda estava ``active``; ``False`` se outro processo já a marcou
            ``interrompida`` (ou ela foi fechada).
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_connection() as conn:
            if loop_beat_at is None:
                row = conn.execute(
                    "UPDATE agent_sessions SET updated_at = %s WHERE id = %s AND status = 'active' RETURNING id",
                    (now, session_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "UPDATE agent_sessions SET updated_at = %s, loop_beat_at = %s "
                    "WHERE id = %s AND status = 'active' RETURNING id",
                    (now, loop_beat_at, session_id),
                ).fetchone()
        return row is not None

    def register_process(
        self,
        session_id: str,
        *,
        pid: int,
        host: str,
        process_started_at: str,
        terminal_id: str | None = None,
        alias: str | None = None,
        resumo: str | None = None,
    ) -> bool:
        """Registra o processo que executa a sessão (PID, host, início do processo, terminal, apelido e resumo).

        O terminal confere esses campos para saber se o processo ainda existe (PID e início do processo, só no
        mesmo host). ``loop_beat_at`` começa no instante do registro.

        Returns:
            ``True`` se a sessão existe.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "UPDATE agent_sessions SET pid = %s, host = %s, process_started_at = %s, loop_beat_at = %s, "
                "terminal_id = COALESCE(%s, terminal_id), alias = COALESCE(%s, alias), "
                "resumo = COALESCE(%s, resumo), updated_at = %s WHERE id = %s RETURNING id",
                (pid, host, process_started_at, now, terminal_id, alias, resumo, now, session_id),
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

    def claim_continuation(self, source_id: str, new_id: str, expected: str | None = None) -> bool:
        """Reivindica, de forma atômica, a continuação de ``source_id`` por ``new_id`` (compare-and-set no payload).

        Só uma retomada simultânea vence: o ``UPDATE`` grava ``payload.continued_by`` apenas se ele ainda não existe
        (ou, em ``expected``, se ainda vale o valor de uma continuação falha anterior). Sem esquema novo (JSONB).

        Args:
            source_id: Sessão continuada.
            new_id: Sessão nova que a continua.
            expected: ``continued_by`` anterior (continuação que falhou sem checkpoint) a ser substituído.

        Returns:
            ``True`` se a reivindicação foi gravada; ``False`` se outra retomada chegou antes.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_connection() as conn:
            if expected is None:
                row = conn.execute(
                    "UPDATE agent_sessions SET payload = payload || jsonb_build_object('continued_by', %s::text), "
                    "updated_at = %s WHERE id = %s AND NOT (payload ? 'continued_by') RETURNING id",
                    (new_id, now, source_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "UPDATE agent_sessions SET payload = payload || jsonb_build_object('continued_by', %s::text), "
                    "updated_at = %s WHERE id = %s AND payload->>'continued_by' = %s RETURNING id",
                    (new_id, now, source_id, expected),
                ).fetchone()
        return row is not None

    def release_continuation(self, source_id: str, new_id: str) -> bool:
        """Libera a reivindicação de ``new_id`` sobre ``source_id`` (a continuação falhou cedo)."""
        with get_connection() as conn:
            row = conn.execute(
                "UPDATE agent_sessions SET payload = payload - 'continued_by' "
                "WHERE id = %s AND payload->>'continued_by' = %s RETURNING id",
                (source_id, new_id),
            ).fetchone()
        return row is not None

    def reassert_active(self, session_id: str) -> bool:
        """Reafirma ``active`` numa sessão viva marcada ``interrompida`` por engano (falso positivo de obsolescência).

        Limpa o ``motivo_parada`` herdado da marcação. Só age se o status ainda é ``interrompida`` **e** a sessão não
        foi continuada por outra (``payload.continued_by``): reativá-la criaria duas sessões vivas para a mesma
        pesquisa (v18.7-background-sessions §1.8).
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "UPDATE agent_sessions SET status = 'active', payload = payload - 'motivo_parada', updated_at = %s "
                "WHERE id = %s AND status = 'interrompida' AND NOT (payload ? 'continued_by') RETURNING id",
                (now, session_id),
            ).fetchone()
        return row is not None

    def aliases_in_use(self, slug: str) -> list[str]:
        """Apelidos já gravados com o prefixo ``<slug>-`` (para ``next_alias`` escolher o próximo número livre)."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT alias FROM agent_sessions WHERE alias LIKE %s",
                (slug.replace("%", "").replace("_", r"\_") + "-%",),
            ).fetchall()
        return [r["alias"] for r in rows or []]

    def list_orchestrator(
        self, statuses: Sequence[str] | None = None, *, updated_after: str | None = None, limit: int = 200
    ) -> list[Session]:
        """Sessões mestras (``agent_id='orchestrator'``), da alterada há mais tempo à mais recente.

        Args:
            statuses: Só estes status (todos, se omitido).
            updated_after: Só as alteradas depois deste instante (ISO 8601).
            limit: Quantidade máxima.
        """
        clauses, params = ["agent_id = 'orchestrator'"], []
        if statuses is not None:
            clauses.append("status = ANY(%s)")
            params.append(list(statuses))
        if updated_after is not None:
            clauses.append("updated_at > %s")
            params.append(updated_after)
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM agent_sessions WHERE {' AND '.join(clauses)} ORDER BY updated_at ASC LIMIT %s",
                (*params, limit),
            ).fetchall()
        return [self._row_to_session(r) for r in rows or []]

    def mark_interrupted(self, session_id: str, expected_updated_at: str) -> Session | None:
        """Marca ``interrompida`` a sessão ``active`` cujo ``updated_at`` ainda é o lido (transição condicional).

        Um batimento que chegou entre a leitura e a escrita muda ``updated_at`` e impede a marcação.

        Returns:
            A sessão marcada, ou ``None`` se ela já não estava ``active`` com aquele ``updated_at``.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        patch = json.dumps({"motivo_parada": "interrompida"})
        with get_connection() as conn:
            row = conn.execute(
                "UPDATE agent_sessions SET status = 'interrompida', payload = payload || %s::jsonb, updated_at = %s "
                "WHERE id = %s AND agent_id = 'orchestrator' AND status = 'active' AND updated_at = %s RETURNING *",
                (patch, now, session_id, expected_updated_at),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def close_by_researcher(
        self, session_id: str, statuses: Sequence[str], motivo: str = "encerrada_pesquisador"
    ) -> bool:
        """Fecha a sessão parada por decisão do pesquisador: ``closed`` com ``motivo_parada`` (padrão
        ``encerrada_pesquisador``; ``solucao_encontrada`` ou ``planos_rejeitados`` nas respostas de continuidade).

        Condicional ao status atual estar em ``statuses`` (uma sessão que voltou a ``active`` não é encerrada).
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        patch = json.dumps({"motivo_parada": motivo})
        with get_connection() as conn:
            row = conn.execute(
                "UPDATE agent_sessions SET status = 'closed', payload = payload || %s::jsonb, updated_at = %s "
                "WHERE id = %s AND agent_id = 'orchestrator' AND status = ANY(%s) RETURNING id",
                (patch, now, session_id, list(statuses)),
            ).fetchone()
        return row is not None

    def find_by_launch_id(self, launch_id: str) -> Session | None:
        """Sessão criada pelo lançamento ``launch_id`` (``payload.launch_id``), ou ``None`` se ainda não existe."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE agent_id = 'orchestrator' AND payload->>'launch_id' = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (launch_id,),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def find_by_alias(self, alias: str) -> Session | None:
        """Folha da cadeia com o apelido (a sessão mais recente sem ``continued_by``); ``None`` se não existe."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM agent_sessions WHERE agent_id = 'orchestrator' AND alias = %s "
                "AND NOT (payload ? 'continued_by') ORDER BY created_at DESC LIMIT 1",
                (alias,),
            ).fetchone()
        return self._row_to_session(row) if row else None

    def purge_finished(self, retention_days: float) -> int:
        """Remove do registro as sessões mestras **terminadas** há mais de ``retention_days`` dias.

        O registro de sessões não precisa durar para sempre (decisão do pesquisador, 2026-10-16). Nunca remove:
        sessão com trabalho por terminar (``active``, ``interrompida``, ``aguarda_pesquisador``,
        ``suspensa_sem_pesquisador``, ``suspended``) nem as antecessoras de uma cadeia que ainda tem sessão assim
        (a retomada precisa da cadeia). Os arquivos de ``outputs/`` não são tocados. ``0`` ou menos desliga a purga.

        Returns:
            Quantidade de sessões removidas.
        """
        if retention_days <= 0:
            return 0
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=retention_days)).isoformat()
        with get_connection() as conn:
            rows = conn.execute(
                """
                WITH RECURSIVE keep(id) AS (
                    SELECT id FROM agent_sessions
                    WHERE agent_id = 'orchestrator' AND NOT (status = ANY(%s))
                    UNION
                    SELECT s.payload->>'continues_session_id'
                    FROM agent_sessions s JOIN keep k ON s.id = k.id
                    WHERE s.payload ? 'continues_session_id'
                )
                DELETE FROM agent_sessions
                WHERE agent_id = 'orchestrator' AND status = ANY(%s) AND updated_at < %s
                  AND id NOT IN (SELECT id FROM keep WHERE id IS NOT NULL)
                RETURNING id
                """,
                (list(FINISHED_STATUSES), list(FINISHED_STATUSES), cutoff),
            ).fetchall()
            conn.execute(
                "DELETE FROM terminal_presence WHERE ended_at IS NOT NULL AND ended_at < %s",
                (cutoff,),
            )
        removed = len(rows or [])
        if removed:
            logger.info("Sessões antigas removidas do registro", extra={"extra": {"removidas": removed}})
        return removed
