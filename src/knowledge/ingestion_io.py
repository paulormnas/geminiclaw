"""Leitura segura da pasta da sessão para a ingestão de fatos (v17-structural-fact-ingestion).

Tudo o que a ingestão lê em ``outputs/<sessão>/`` (``params.json``, ``metrics.json``, ``manifest.json``,
scripts ``step_NN.py`` e arquivos de ``input_snapshot/``) é **dado não confiável**: o código gerado
por LLM roda no sandbox com escrita nessa pasta e o pesquisador pode colocar qualquer nome de arquivo
em ``input_context/``. Por isso:

- nomes de subtarefa e de dataset são validados (sem separadores, sem ``..``);
- o caminho é resolvido e precisa ficar **dentro** da pasta da sessão; links simbólicos, FIFOs e
  demais arquivos especiais são recusados (``O_NOFOLLOW`` + ``fstat``);
- JSON malformado, grande demais ou de tipo inesperado vira ``IngestionFileError`` (tolerada pelo
  chamador, que registra a falha e segue);
- tamanhos são limitados.

Nenhuma função daqui escreve no grafo.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.logger import get_logger

logger = get_logger(__name__)

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STEP_FILE_RE = re.compile(r"^step_\d{1,4}\.py$")

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SCRIPT_BYTES = 1024 * 1024
MAX_HASH_BYTES = 2 * 1024 * 1024 * 1024  # insumos maiores que isto não são ingeridos
MAX_INPUT_FILES = 500
MAX_METRICS = 200
MAX_DATASETS = 100
MAX_MANIFEST_STEPS = 500
MAX_SEARCH_DEPTH = 3
MAX_SEARCH_ENTRIES = 2000
MAX_NAME_CHARS = 200
_CHUNK = 1024 * 1024


class IngestionFileError(Exception):
    """Arquivo ausente, inseguro, grande demais ou malformado (a ingestão tolera e registra)."""


def is_safe_name(name: object) -> bool:
    """True se ``name`` é um único componente de caminho seguro (sem separadores nem ``..``)."""
    return isinstance(name, str) and bool(SAFE_NAME_RE.fullmatch(name)) and ".." not in name


def finite_number(value: object) -> float | None:
    """Converte número JSON em ``float`` finito; ``None`` para bool, texto, NaN e infinitos."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


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


def read_bytes_limited(path: Path, root: Path, limit: int) -> bytes:
    """Lê até ``limit`` bytes de um arquivo comum confinado em ``root``.

    Raises:
        IngestionFileError: Arquivo inseguro, ilegível ou maior que ``limit``.
    """
    fd = _open_regular(path, root)
    try:
        with os.fdopen(fd, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise IngestionFileError(f"falha de leitura: {type(exc).__name__}") from exc
    if len(data) > limit:
        raise IngestionFileError(f"arquivo maior que {limit} bytes")
    return data


def read_json_object(path: Path, root: Path) -> dict[str, Any]:
    """Lê um JSON cuja raiz é um objeto, com tolerância explícita a malformação.

    Raises:
        IngestionFileError: Inseguro, grande demais, JSON inválido ou raiz que não é objeto.
    """
    raw = read_bytes_limited(path, root, MAX_JSON_BYTES)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise IngestionFileError("JSON malformado") from exc
    if not isinstance(data, dict):
        raise IngestionFileError("a raiz do JSON não é um objeto")
    return data


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


def list_regular_files(directory: Path, root: Path, *, limit: int = MAX_INPUT_FILES) -> list[Path]:
    """Arquivos comuns (não links) do primeiro nível de ``directory``, em ordem, até ``limit``.

    Entradas com link simbólico, subdiretórios e arquivos especiais são ignorados.
    """
    try:
        base = _confined(directory, root)
        entries = sorted(os.scandir(base), key=lambda e: e.name)
    except (OSError, IngestionFileError):
        return []
    files: list[Path] = []
    for entry in entries:
        try:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
        except OSError:
            continue
        files.append(base / entry.name)
        if len(files) >= limit:
            logger.warning("Limite de arquivos do input_snapshot atingido", extra={"extra": {"limit": limit}})
            break
    return files


def find_artifact(task_dir: Path, root: Path, filename: str) -> Path | None:
    """Localiza ``filename`` na pasta da subtarefa (direto ou em subpasta rasa), sem seguir links.

    A busca é limitada em profundidade e em número de entradas; o primeiro caminho em ordem
    alfabética vence (mesma convenção do Validator).
    """
    try:
        base = _confined(task_dir, root)
    except IngestionFileError:
        return None
    direct = base / filename
    if direct.is_file() and not direct.is_symlink():
        return direct
    seen = 0
    candidates: list[Path] = []
    for current, dirs, files in os.walk(base, followlinks=False):
        depth = len(Path(current).relative_to(base).parts)
        dirs[:] = sorted(d for d in dirs if not (Path(current) / d).is_symlink()) if depth < MAX_SEARCH_DEPTH else []
        seen += len(dirs) + len(files)
        if filename in files and not (Path(current) / filename).is_symlink():
            candidates.append(Path(current) / filename)
        if seen > MAX_SEARCH_ENTRIES:
            break
    return sorted(candidates)[0] if candidates else None


@dataclass
class SubtaskEvidence:
    """O que a ingestão leu do disco sobre uma subtarefa.

    Attributes:
        params: Conteúdo de ``params.json`` (``None`` se ausente/inválido).
        metrics: Conteúdo de ``metrics.json`` (``None`` se ausente/inválido).
        metrics_status: ``"ausente"``, ``"ok"`` ou ``"invalido"``.
        metrics_path: Caminho relativo da pasta da sessão até ``metrics.json``.
        steps: Steps do ``manifest.json`` atribuídos à subtarefa (somente dicionários).
        code_hash: Hash dos scripts executados (``None`` sem scripts legíveis).
        warnings: Falhas de leitura toleradas (sem conteúdo de pesquisa).
    """

    params: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    metrics_status: str = "ausente"
    metrics_path: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    code_hash: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def last_run(self) -> dict[str, Any] | None:
        """Saída estruturada do sandbox do último step da subtarefa (``None`` sem steps)."""
        if not self.steps:
            return None
        run = self.steps[-1].get("run")
        return run if isinstance(run, dict) else {}


def collect_evidence(session_dir: Path, task_name: str) -> SubtaskEvidence:
    """Lê com segurança os artefatos de uma subtarefa em ``session_dir``.

    Args:
        session_dir: ``outputs/<sessão>/``.
        task_name: Nome da subtarefa (pasta ``session_dir/<task_name>/``); nome inseguro
            devolve evidência vazia.

    Returns:
        ``SubtaskEvidence``; nunca levanta por arquivo ausente ou malformado.
    """
    ev = SubtaskEvidence()
    try:
        root = session_dir.resolve(strict=True)
    except OSError:
        ev.warnings.append("pasta da sessão inacessível")
        return ev

    _read_manifest(root, task_name, ev)

    if not is_safe_name(task_name):
        ev.warnings.append("task_name inseguro: artefatos não lidos")
        return ev
    task_dir = root / task_name
    metrics_file = find_artifact(task_dir, root, "metrics.json")
    if metrics_file is not None:
        try:
            ev.metrics = read_json_object(metrics_file, root)
            ev.metrics_status = "ok"
        except IngestionFileError as exc:
            ev.metrics_status = "invalido"
            ev.warnings.append(f"metrics.json: {exc}")
        ev.metrics_path = metrics_file.relative_to(root).as_posix() if metrics_file.is_relative_to(root) else None
    params_file = find_artifact(
        metrics_file.parent if metrics_file is not None else task_dir, root, "params.json"
    ) or find_artifact(task_dir, root, "params.json")
    if params_file is not None:
        try:
            ev.params = read_json_object(params_file, root)
        except IngestionFileError as exc:
            ev.warnings.append(f"params.json: {exc}")
    return ev


def _read_manifest(root: Path, task_name: str, ev: SubtaskEvidence) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return
    try:
        manifest = read_json_object(manifest_path, root)
    except IngestionFileError as exc:
        ev.warnings.append(f"manifest.json: {exc}")
        return
    steps = manifest.get("steps")
    if not isinstance(steps, list):
        return
    mine = [s for s in steps[:MAX_MANIFEST_STEPS] if isinstance(s, dict) and s.get("task_name") == task_name]
    ev.steps = mine
    digests: set[str] = set()
    for step in mine:
        code_file = step.get("code_file")
        if not isinstance(code_file, str) or not _STEP_FILE_RE.fullmatch(code_file):
            continue
        try:
            digests.add(hashlib.sha256(read_bytes_limited(root / code_file, root, MAX_SCRIPT_BYTES)).hexdigest())
        except IngestionFileError as exc:
            ev.warnings.append(f"{code_file}: {exc}")
    if len(digests) == 1:
        ev.code_hash = next(iter(digests))
    elif digests:
        ev.code_hash = hashlib.sha256("\n".join(sorted(digests)).encode("ascii")).hexdigest()
