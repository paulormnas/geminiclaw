"""sha256 de arquivos com cache local por tamanho e data de modificação (design §6)."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

from src.logger import get_logger

logger = get_logger(__name__)

BLOCK_SIZE = 1024 * 1024


def sha256_file(path: Path | str) -> str:
    """sha256 (hex) do conteúdo, lido em blocos de 1 MiB."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


class HashCache:
    """Cache SQLite de hashes de arquivos grandes, chaveado por ``(caminho, dispositivo, inode, tamanho, mtime_ns)``.

    Usa só a biblioteca padrão. Falha do cache (disco, trava) nunca derruba a execução: o hash é recalculado.
    """

    def __init__(self, path: Path | str, min_bytes: int) -> None:
        self.path = Path(path)
        self.min_bytes = min_bytes
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self.hits = 0
        self.misses = 0

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS hashes (path TEXT NOT NULL, dev INTEGER NOT NULL, ino INTEGER NOT NULL, "
                "size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL, "
                "PRIMARY KEY (path, dev, ino, size, mtime_ns))"
            )
            self._conn.commit()
        return self._conn

    def lookup(self, key: tuple[str, int, int, int, int]) -> str | None:
        try:
            with self._lock:
                row = self._connection().execute(
                    "SELECT sha256 FROM hashes WHERE path=? AND dev=? AND ino=? AND size=? AND mtime_ns=?", key
                ).fetchone()
            return row[0] if row else None
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Cache de hash indisponível; recalculando", extra={"error": type(exc).__name__})
            return None

    def store(self, key: tuple[str, int, int, int, int], digest: str) -> None:
        try:
            with self._lock:
                conn = self._connection()
                conn.execute("INSERT OR REPLACE INTO hashes VALUES (?, ?, ?, ?, ?, ?)", (*key, digest))
                conn.commit()
        except (sqlite3.Error, OSError) as exc:
            logger.warning("Cache de hash não gravado", extra={"error": type(exc).__name__})

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


def hash_file(path: Path | str, cache: HashCache | None = None, *, full: bool = False) -> tuple[str, int]:
    """``(sha256, tamanho)`` do arquivo; usa o cache quando o arquivo é grande e ``full`` é falso.

    Raises:
        OSError: Arquivo ilegível ou inexistente.
    """
    target = Path(path)
    stat = os.stat(target)
    size = stat.st_size
    use_cache = cache is not None and not full and size >= cache.min_bytes
    key = (str(target.resolve()), stat.st_dev, stat.st_ino, size, stat.st_mtime_ns)
    if use_cache:
        hit = cache.lookup(key)  # type: ignore[union-attr]
        if hit is not None:
            cache.hits += 1  # type: ignore[union-attr]
            return hit, size
        cache.misses += 1  # type: ignore[union-attr]
    digest = sha256_file(target)
    if cache is not None and size >= cache.min_bytes:
        cache.store(key, digest)
    return digest, size


def hash_files(
    paths: Iterable[Path], base: Path, cache: HashCache | None = None, *, full: bool = False
) -> list[dict[str, object]]:
    """``[{caminho, sha256, tamanho}]`` (caminho relativo a ``base``, com ``/``), em ordem de caminho.

    Raises:
        OSError: Algum arquivo é ilegível (a execução não pode ser registrada sem o hash das entradas).
    """
    rows: list[dict[str, object]] = []
    for path in paths:
        digest, size = hash_file(path, cache, full=full)
        try:
            rel = path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            rel = path.as_posix()
        rows.append({"caminho": rel, "sha256": digest, "tamanho": size})
    rows.sort(key=lambda row: str(row["caminho"]))
    return rows
