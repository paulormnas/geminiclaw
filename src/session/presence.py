"""Presença do terminal (v18.7-background-sessions, design §1.6 e §1.7).

O REPL e o comando direto em primeiro plano gravam uma linha em ``terminal_presence`` ao abrir e a atualizam em thread
própria a cada ``TERMINAL_PRESENCE_HEARTBEAT_SECONDS``; na saída normal gravam ``ended_at`` e ``end_reason='saida'``.
A presença sem batimento há mais de ``TERMINAL_PRESENCE_STALE_SECONDS`` vale como ausência: a sessão ``assisted`` que
a lê se suspende. Só um REPL por vez. O relógio e o armazenamento são injetáveis (``FakeClock`` e um armazenamento em
memória nos testes de unidade).
"""

from __future__ import annotations

import datetime
import socket
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src import config
from src.logger import get_logger

logger = get_logger(__name__)

TIPO_REPL = "repl"
TIPO_DIRETO = "direto"
END_EXIT = "saida"
END_OBSOLETE = "obsoleta"


class TerminalAlreadyOpenError(RuntimeError):
    """Já há um REPL aberto (presença viva); o novo REPL é recusado."""


@dataclass(frozen=True)
class PresenceRow:
    """Linha de ``terminal_presence``; os instantes são segundos desde a época."""

    terminal_id: str
    tipo: str
    pid: int
    host: str
    started_at: float
    heartbeat_at: float
    ended_at: float | None = None
    end_reason: str | None = None


class PresenceStore(Protocol):
    """Armazenamento da presença (PostgreSQL em produção; memória nos testes de unidade)."""

    def open_rows(self, tipo: str) -> list[PresenceRow]: ...

    def insert(self, row: PresenceRow, *, exclusive_live_after: float | None = None) -> bool:
        """Grava a linha; com ``exclusive_live_after`` só se não há linha ``tipo`` aberta com batimento posterior."""
        ...

    def touch(self, terminal_id: str, heartbeat_at: float) -> bool: ...

    def end(self, terminal_id: str, ended_at: float, reason: str) -> bool: ...

    def get(self, terminal_id: str) -> PresenceRow | None: ...

    def last_repl_end(self) -> float | None:
        """Fim da última presença de REPL encerrada (para o resumo "desde a última vez")."""
        ...


def _dt(value: float | None) -> datetime.datetime | None:
    return None if value is None else datetime.datetime.fromtimestamp(value, datetime.timezone.utc)


def _ts(value: datetime.datetime | None) -> float | None:
    return None if value is None else value.timestamp()


def _row(raw: dict) -> PresenceRow:
    return PresenceRow(
        terminal_id=raw["terminal_id"],
        tipo=raw["tipo"],
        pid=raw["pid"],
        host=raw["host"],
        started_at=_ts(raw["started_at"]) or 0.0,
        heartbeat_at=_ts(raw["heartbeat_at"]) or 0.0,
        ended_at=_ts(raw["ended_at"]),
        end_reason=raw["end_reason"],
    )


class PgPresenceStore:
    """``terminal_presence`` no PostgreSQL. A criação do REPL é feita sob trava (sem corrida na abertura)."""

    def open_rows(self, tipo: str) -> list[PresenceRow]:
        from src.db import get_connection

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM terminal_presence WHERE tipo = %s AND ended_at IS NULL", (tipo,)
            ).fetchall()
        return [_row(r) for r in rows or []]

    def insert(self, row: PresenceRow, *, exclusive_live_after: float | None = None) -> bool:
        from src.db import get_connection

        values = (
            row.terminal_id, row.tipo, row.pid, row.host, _dt(row.started_at), _dt(row.heartbeat_at),
        )
        with get_connection() as conn:
            if exclusive_live_after is None:
                conn.execute(
                    "INSERT INTO terminal_presence (terminal_id, tipo, pid, host, started_at, heartbeat_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    values,
                )
                return True
            conn.execute("LOCK TABLE terminal_presence IN SHARE ROW EXCLUSIVE MODE")
            inserted = conn.execute(
                "INSERT INTO terminal_presence (terminal_id, tipo, pid, host, started_at, heartbeat_at) "
                "SELECT %s, %s, %s, %s, %s, %s WHERE NOT EXISTS ("
                "SELECT 1 FROM terminal_presence WHERE tipo = %s AND ended_at IS NULL AND heartbeat_at > %s) "
                "RETURNING terminal_id",
                (*values, row.tipo, _dt(exclusive_live_after)),
            ).fetchone()
        return inserted is not None

    def touch(self, terminal_id: str, heartbeat_at: float) -> bool:
        from src.db import get_connection

        with get_connection() as conn:
            done = conn.execute(
                "UPDATE terminal_presence SET heartbeat_at = %s WHERE terminal_id = %s AND ended_at IS NULL "
                "RETURNING terminal_id",
                (_dt(heartbeat_at), terminal_id),
            ).fetchone()
        return done is not None

    def end(self, terminal_id: str, ended_at: float, reason: str) -> bool:
        from src.db import get_connection

        with get_connection() as conn:
            done = conn.execute(
                "UPDATE terminal_presence SET ended_at = %s, end_reason = %s "
                "WHERE terminal_id = %s AND ended_at IS NULL RETURNING terminal_id",
                (_dt(ended_at), reason, terminal_id),
            ).fetchone()
        return done is not None

    def get(self, terminal_id: str) -> PresenceRow | None:
        from src.db import get_connection

        with get_connection() as conn:
            raw = conn.execute("SELECT * FROM terminal_presence WHERE terminal_id = %s", (terminal_id,)).fetchone()
        return _row(raw) if raw else None

    def last_repl_end(self) -> float | None:
        from src.db import get_connection

        with get_connection() as conn:
            raw = conn.execute(
                "SELECT max(ended_at) AS fim FROM terminal_presence WHERE tipo = 'repl' AND ended_at IS NOT NULL"
            ).fetchone()
        return _ts(raw["fim"]) if raw and raw["fim"] else None


def terminal_present(
    terminal_id: str | None,
    *,
    store: PresenceStore | None = None,
    stale_seconds: float | None = None,
    clock: Callable[[], float] = time.time,
) -> bool:
    """O terminal ``terminal_id`` está presente: linha sem ``ended_at`` e batimento recente (``stale_seconds``)."""
    if not terminal_id:
        return False
    row = (store or PgPresenceStore()).get(terminal_id)
    if row is None or row.ended_at is not None:
        return False
    limit = config.TERMINAL_PRESENCE_STALE_SECONDS if stale_seconds is None else stale_seconds
    return (clock() - row.heartbeat_at) <= limit


def _pid_alive(pid: int) -> bool:
    import psutil

    return psutil.pid_exists(pid)


class TerminalPresence:
    """Presença do terminal que a abriu: ``start()``, batimento em thread e ``stop()``."""

    def __init__(
        self,
        tipo: str,
        *,
        store: PresenceStore | None = None,
        clock: Callable[[], float] = time.time,
        heartbeat_seconds: float | None = None,
        stale_seconds: float | None = None,
        pid: int | None = None,
        host: str | None = None,
        pid_alive: Callable[[int], bool] = _pid_alive,
    ) -> None:
        if tipo not in (TIPO_REPL, TIPO_DIRETO):
            raise ValueError(f"tipo de terminal inválido: {tipo!r}")
        import os

        self.tipo = tipo
        self._store = store or PgPresenceStore()
        self._clock = clock
        self._heartbeat = config.TERMINAL_PRESENCE_HEARTBEAT_SECONDS if heartbeat_seconds is None else heartbeat_seconds
        self._stale = config.TERMINAL_PRESENCE_STALE_SECONDS if stale_seconds is None else stale_seconds
        self._pid = pid if pid is not None else os.getpid()
        self._host = host or socket.gethostname()
        self._pid_alive = pid_alive
        self.terminal_id: str | None = None
        self._last_beat = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        """Grava a presença. REPL: marca as obsoletas e recusa se já há um REPL vivo.

        Raises:
            TerminalAlreadyOpenError: Há outro REPL aberto (batimento recente e, no mesmo host, PID vivo).
        """
        now = self._clock()
        row = PresenceRow(str(uuid.uuid4()), self.tipo, self._pid, self._host, now, now)
        if self.tipo == TIPO_REPL:
            for old in self._store.open_rows(TIPO_REPL):
                stale = (now - old.heartbeat_at) > self._stale
                dead = old.host == self._host and not self._pid_alive(old.pid)
                if stale or dead:
                    self._store.end(old.terminal_id, now, END_OBSOLETE)
            if not self._store.insert(row, exclusive_live_after=now - self._stale):
                raise TerminalAlreadyOpenError("já há um terminal (REPL) aberto; feche-o antes de abrir outro.")
        else:
            self._store.insert(row)
        self.terminal_id = row.terminal_id
        self._last_beat = now
        return row.terminal_id

    def tick(self) -> bool:
        """Grava o batimento se passou ``heartbeat_seconds`` desde o último; ``True`` se gravou."""
        if self.terminal_id is None:
            return False
        now = self._clock()
        if now - self._last_beat < self._heartbeat:
            return False
        self._last_beat = now
        try:
            self._store.touch(self.terminal_id, now)
        except Exception as exc:  # noqa: BLE001 - falha de batimento nunca derruba o terminal
            logger.warning("Batimento de presença falhou", extra={"error": type(exc).__name__})
            return False
        return True

    def start_heartbeat(self) -> "TerminalPresence":
        """Inicia a thread do batimento (daemon)."""
        self._thread = threading.Thread(target=self._run, name="geminiclaw-presence", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(max(self._heartbeat, 0.01)):
            self.tick()

    def stop(self, reason: str = END_EXIT) -> None:
        """Para o batimento e grava ``ended_at`` e ``end_reason`` (saída normal: ``saida``)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self.terminal_id is not None:
            try:
                self._store.end(self.terminal_id, self._clock(), reason)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Fim da presença não gravado", extra={"error": type(exc).__name__})

    def is_present(self, terminal_id: str | None = None) -> bool:
        """``terminal_id`` (padrão: o deste terminal) está presente (batimento dentro de ``stale_seconds``)."""
        return terminal_present(
            terminal_id or self.terminal_id, store=self._store, stale_seconds=self._stale, clock=self._clock
        )
