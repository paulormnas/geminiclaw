"""Detecção de sessões paradas pelo terminal (v18.7-background-sessions, design §1.7 e §1.8).

Ao abrir e a cada ``TERMINAL_STALE_CHECK_SECONDS`` o terminal marca ``interrompida``, por transição condicional, a
sessão ``active`` cujo processo não existe no mesmo host (ou existe com outra hora de início: reuso de PID), cujo
batimento passou de ``SESSION_STALE_SECONDS`` ou cujo sinal do laço passou de ``SESSION_LOOP_STALE_SECONDS``. Em outro
host só valem o batimento e o sinal do laço (o PID não se confere). Depois da marcação, ``recover`` grava o checkpoint
``interrompido`` e converte as subtarefas em andamento em falha de infraestrutura.
"""

from __future__ import annotations

import datetime
import socket
import time
from collections.abc import Callable
from typing import Any

from src import config
from src.logger import get_logger
from src.session.manager import Session, SessionManager

logger = get_logger(__name__)

PID_REUSE_TOLERANCE_SECONDS = 2.0


def _epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def process_create_time(pid: int) -> float | None:
    """Hora de início do processo ``pid`` neste host, ou ``None`` se ele não existe."""
    import psutil

    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


class SessionWatch:
    """Varredura de sessões ``active`` que pararam sem fechar."""

    def __init__(
        self,
        session_manager: SessionManager | Any,
        *,
        recover: Callable[[Session], None] | None = None,
        host: str | None = None,
        clock: Callable[[], float] = time.time,
        stale_seconds: float | None = None,
        loop_stale_seconds: float | None = None,
        create_time: Callable[[int], float | None] = process_create_time,
    ) -> None:
        self._manager = session_manager
        self._recover = recover
        self._host = host or socket.gethostname()
        self._clock = clock
        self._stale = config.SESSION_STALE_SECONDS if stale_seconds is None else stale_seconds
        self._loop_stale = config.SESSION_LOOP_STALE_SECONDS if loop_stale_seconds is None else loop_stale_seconds
        self._create_time = create_time

    def reason(self, session: Session) -> str | None:
        """Por que a sessão ``active`` é considerada parada (texto curto), ou ``None`` se está viva."""
        now = self._clock()
        if session.pid is not None and session.host == self._host:
            created = self._create_time(session.pid)
            if created is None:
                return "processo inexistente"
            started = _epoch(session.process_started_at)
            if started is not None and abs(created - started) > PID_REUSE_TOLERANCE_SECONDS:
                return "PID reutilizado por outro processo"
        updated = _epoch(session.updated_at)
        if updated is not None and now - updated > self._stale:
            return f"sem batimento há mais de {self._stale:g} s"
        beat = _epoch(session.loop_beat_at)
        if beat is not None and now - beat > self._loop_stale:
            return f"laço sem sinal há mais de {self._loop_stale:g} s"
        return None

    def sweep(self) -> list[Session]:
        """Marca ``interrompida`` as sessões paradas e chama ``recover`` em cada uma. Nunca levanta.

        Returns:
            As sessões marcadas nesta varredura.
        """
        marked: list[Session] = []
        try:
            candidates = self._manager.list_orchestrator(["active"])
        except Exception as exc:  # noqa: BLE001 - a varredura nunca derruba o terminal
            logger.warning("Varredura de sessões paradas falhou", extra={"error": type(exc).__name__})
            return marked
        for session in candidates:
            why = self.reason(session)
            if why is None:
                continue
            try:
                done = self._manager.mark_interrupted(session.id, session.updated_at)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Marcação de sessão parada falhou", extra={"error": type(exc).__name__})
                continue
            if done is None:  # um batimento chegou entre a leitura e a escrita
                continue
            logger.warning("Sessão parada marcada interrompida", extra={"session_id": session.id, "motivo": why})
            marked.append(done)
            if self._recover is not None:
                try:
                    self._recover(done)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Recuperação da sessão parada falhou", extra={"error": type(exc).__name__})
        return marked
