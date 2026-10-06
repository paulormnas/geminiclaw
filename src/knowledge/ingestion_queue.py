"""Fila local de reenvio da ingestão de fatos (``knowledge_pending.jsonl``).

Quando o grafo está indisponível, a ingestão **não interrompe a sessão**: o evento é guardado em
``outputs/<sessão>/knowledge_pending.jsonl`` e reprocessado depois por ``geminiclaw knowledge sync``
(idempotente). O evento guarda só o contexto e os identificadores da subtarefa — os valores de
pesquisa são relidos do disco na hora do reenvio, nunca copiados para a fila.

Segurança do arquivo (a pasta da sessão é gravável pelo sandbox):

- escrita atômica: arquivo temporário exclusivo (``0600``) + ``os.replace`` (nunca segue link no destino);
- leitura sem seguir link simbólico, só arquivo comum do próprio usuário, com tamanho limitado;
- linhas malformadas são ignoradas e contadas (nunca derrubam o reenvio);
- tamanhos limitados (por evento, por arquivo e em número de eventos).
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterator

from src.logger import get_logger

try:  # pragma: no cover - fcntl existe em Linux/macOS (alvos do projeto)
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

logger = get_logger(__name__)

PENDING_FILENAME = "knowledge_pending.jsonl"
DEAD_FILENAME = "knowledge_pending.dead.jsonl"
LOCK_FILENAME = ".knowledge_pending.lock"
MAX_EVENT_BYTES = 64 * 1024
MAX_EVENTS = 2000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SYNC_ATTEMPTS = 5

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(key: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


class PendingQueue:
    """Fila de eventos pendentes de uma sessão (``session_dir/knowledge_pending.jsonl``)."""

    def __init__(self, session_dir: Path, *, filename: str = PENDING_FILENAME) -> None:
        self._dir = Path(session_dir)
        self._path = self._dir / filename

    @property
    def path(self) -> Path:
        """Caminho do arquivo da fila."""
        return self._path

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        with _thread_lock(str(self._path)):
            if fcntl is None:  # pragma: no cover
                yield
                return
            lock_path = self._dir / LOCK_FILENAME
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def read(self) -> tuple[list[dict[str, Any]], int]:
        """Lê os eventos válidos.

        Returns:
            ``(eventos, ignoradas)``: eventos (dicionários) e a contagem de linhas inválidas.

        Raises:
            OSError: Arquivo suspeito (link simbólico, não comum, de outro usuário ou grande demais).
        """
        with self._locked():
            return self._read_unlocked()

    def _read_unlocked(self) -> tuple[list[dict[str, Any]], int]:
        if not self._path.exists() and not self._path.is_symlink():
            return [], 0
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(self._path, flags)  # ELOOP em link simbólico
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise OSError(f"arquivo de pendências suspeito: {self._path.name}")
            if info.st_size > MAX_FILE_BYTES:
                raise OSError(f"arquivo de pendências maior que {MAX_FILE_BYTES} bytes")
            with os.fdopen(fd, "rb") as handle:
                raw = handle.read(MAX_FILE_BYTES + 1)
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(fd)
            raise
        events: list[dict[str, Any]] = []
        ignored = 0
        for line in raw.splitlines()[:MAX_EVENTS]:
            if not line.strip():
                continue
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                ignored += 1
                continue
            if isinstance(event, dict):
                events.append(event)
            else:
                ignored += 1
        return events, ignored

    def append(self, event: dict[str, Any]) -> bool:
        """Acrescenta um evento (escrita atômica do arquivo inteiro).

        Returns:
            ``True`` se gravado; ``False`` (com aviso) se o evento ou a fila excedem os limites.
        """
        try:
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            logger.warning("Evento de ingestão não serializável; descartado")
            return False
        if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
            logger.warning("Evento de ingestão acima do limite; descartado", extra={"extra": {"max": MAX_EVENT_BYTES}})
            return False
        with self._locked():
            try:
                events, _ = self._read_unlocked()
            except OSError as exc:
                logger.warning("Fila de pendências ilegível; evento não gravado", extra={"extra": {"error": str(exc)}})
                return False
            if len(events) >= MAX_EVENTS:
                logger.warning("Fila de pendências cheia; evento descartado", extra={"extra": {"limit": MAX_EVENTS}})
                return False
            events.append(json.loads(line))
            return self._write_unlocked(events)

    def rewrite(self, events: list[dict[str, Any]]) -> bool:
        """Substitui o conteúdo da fila (remove o arquivo se ``events`` estiver vazio)."""
        with self._locked():
            if not events:
                with contextlib.suppress(FileNotFoundError):
                    self._path.unlink()
                return True
            return self._write_unlocked(events)

    def _write_unlocked(self, events: list[dict[str, Any]]) -> bool:
        payload = "".join(
            json.dumps(e, ensure_ascii=False, separators=(",", ":"), default=str) + "\n" for e in events
        ).encode("utf-8")
        if len(payload) > MAX_FILE_BYTES:
            logger.warning("Fila de pendências acima do limite de tamanho; evento descartado")
            return False
        try:
            fd, tmp = tempfile.mkstemp(prefix=".knowledge_pending.", suffix=".tmp", dir=self._dir)  # 0600
        except OSError as exc:
            logger.warning("Não foi possível gravar a fila de pendências", extra={"extra": {"error": str(exc)}})
            return False
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        except OSError as exc:
            logger.warning("Não foi possível gravar a fila de pendências", extra={"extra": {"error": str(exc)}})
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            return False
        return True
