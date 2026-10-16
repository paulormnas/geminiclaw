"""Hash em streaming de arquivos de insumo e tipo do insumo (núcleo usado por ingestão e documentos).

Definições movidas de ``src/knowledge/ingestion.py`` e ``src/knowledge/ingestion_io.py`` sem alterar o corpo,
com as auxiliares compartilhadas de que dependem (``IngestionFileError``, ``_confined``, ``_open_regular``),
para que ``src/documents`` não importe ``src/knowledge`` (ADR 024 §2, ``v18.7-source-layout``).
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

MAX_HASH_BYTES = 2 * 1024 * 1024 * 1024  # insumos maiores que isto não são ingeridos
_CHUNK = 1024 * 1024

_DATASET_EXT = frozenset({".csv", ".tsv", ".xlsx", ".xls", ".ods", ".json", ".jsonl", ".parquet"})
_ARTIGO_EXT = frozenset({".pdf", ".docx", ".md", ".txt", ".rst"})


class IngestionFileError(Exception):
    """Arquivo ausente, inseguro, grande demais ou malformado (a ingestão tolera e registra)."""


def _confined(path: Path, root: Path) -> Path:
    """Resolve ``path`` e garante que está dentro de ``root`` (sem link simbólico no destino)."""
    if path.is_symlink():
        raise IngestionFileError("link simbólico recusado")
    try:
        resolved = path.resolve(strict=True)
        root_resolved = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise IngestionFileError(f"caminho inacessível: {type(exc).__name__}") from exc
    if not resolved.is_relative_to(root_resolved):
        raise IngestionFileError("caminho fora da pasta da sessão")
    return resolved


def _open_regular(path: Path, root: Path) -> int:
    """Abre (somente leitura) um arquivo comum confinado em ``root``; devolve o descritor."""
    resolved = _confined(path, root)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(resolved, flags)
    except OSError as exc:
        raise IngestionFileError(f"não foi possível abrir: {type(exc).__name__}") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise IngestionFileError("não é um arquivo comum")
    except BaseException:
        os.close(fd)
        raise
    return fd


def sha256_file(path: Path, root: Path, *, max_bytes: int = MAX_HASH_BYTES) -> str:
    """SHA-256 em streaming de um arquivo comum confinado em ``root``.

    Raises:
        IngestionFileError: Arquivo inseguro, ilegível ou maior que ``max_bytes``.
    """
    fd = _open_regular(path, root)
    digest = hashlib.sha256()
    total = 0
    try:
        with os.fdopen(fd, "rb") as handle:
            while chunk := handle.read(_CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise IngestionFileError(f"arquivo maior que {max_bytes} bytes")
                digest.update(chunk)
    except OSError as exc:
        raise IngestionFileError(f"falha de leitura: {type(exc).__name__}") from exc
    return digest.hexdigest()


def insumo_tipo(filename: str) -> str:
    """``Insumo.tipo`` pela extensão: dataset, artigo ou outro."""
    ext = Path(filename).suffix.lower()
    if ext in _DATASET_EXT:
        return "dataset"
    if ext in _ARTIGO_EXT:
        return "artigo"
    return "outro"
