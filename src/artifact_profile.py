"""Perfil estrutural de artefatos de dados para o revisor (``v18.6-review-evidence`` §4, ``v18.6-profile-hardening``).

Descreve a *forma* de um CSV/TSV ou JSON (linhas, colunas, tipos, chaves, tamanhos de listas, nulos por coluna) sem
nenhum valor de célula. O perfil é calculado no nó, sobre arquivos já gravados em ``outputs/``, e sai rotulado
``esquema_agregado`` (ADR 019 §3). Só biblioteca padrão; a leitura de CSV é em fluxo, limitada a bytes, colunas, linhas
e tempo. Endurecimento (parecer ``docs/security/parecer_v18_6_perfil_estrutural.md``):

* arquivos são abertos sem seguir link simbólico e só se regulares (R2);
* a primeira linha só é cabeçalho se for verificada; rótulos fora do padrão seguro viram ``coluna_N``/``chave_N``
  (R1, R3);
* o perfil nunca levanta exceção (R4) e respeita limites estruturais (R5, R6).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Any, BinaryIO

from src import config
from src.egress.filters import sanitize_artifact_name
from src.logger import get_logger

logger = get_logger(__name__)

_NULL_TOKENS = frozenset({"", "na", "n/a", "nan", "null", "none"})
_MAX_DEPTH = 3
_MAX_JSON_NESTING = 32
_MAX_MAP_KEYS = 50
_MAX_COLUMN_NAME_CHARS = 80
_TIME_CHECK_EVERY_ROWS = 1000
_TABULAR_SUFFIXES = {".csv": "csv", ".tsv": "tsv"}
_SAFE_LABEL_RE = re.compile(r"[\w .\-/()%]{1,80}")
_DATE_RE = re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?")
_JSON_TOKEN_RE = re.compile(r'["\[\]{}]')
_JSON_STRING_BODY_RE = re.compile(r'[^"\\]*(?:\\.[^"\\]*)*"', re.DOTALL)


def is_confined(path: Path, root: Path) -> bool:
    """``True`` se ``path`` não é link simbólico e seu ``resolve()`` está dentro de ``root`` (R2)."""
    try:
        return not path.is_symlink() and path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError):
        return False


def _open_regular(path: Path) -> BinaryIO:
    """Abre para leitura binária recusando link simbólico (``O_NOFOLLOW``) e arquivo que não é regular."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow and path.is_symlink():
        raise OSError(f"link simbólico recusado: {path.name}")
    fd = os.open(path, os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"arquivo não regular recusado: {path.name}")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def read_head_text(path: Path, chars: int) -> str:
    """Primeiros ``chars`` caracteres de um arquivo regular (sem seguir link simbólico).

    Raises:
        OSError: Link simbólico, arquivo não regular ou ilegível.
    """
    with _open_regular(path) as handle:
        raw = handle.read(chars * 4)
    return raw.decode("utf-8", errors="replace")[:chars]


def profile_artifact(
    path: Path, *, max_bytes: int, max_chars: int, k: int | None = None
) -> str | None:
    """Descrição estrutural de um CSV/TSV ou JSON, sem nenhum valor de célula; ``None`` para outros tipos.

    Nunca levanta exceção: qualquer falha vira "não foi possível interpretar o arquivo" (R4).

    Args:
        path: Arquivo a descrever.
        max_bytes: Limite de leitura; acima dele o CSV vira contagem parcial e o JSON não é interpretado.
        max_chars: Tamanho máximo do perfil (excedente é cortado com ``…``).
        k: Tamanho mínimo de grupo (``LOCALITY_MIN_GROUP_SIZE``); padrão, o valor da configuração. Contagem de nulos
            entre 1 e ``k - 1`` é omitida (grupo pequeno, ADR 019 §3).

    Returns:
        Texto do perfil ou ``None`` se o tipo não é suportado ou o arquivo é link simbólico.
    """
    suffix = path.suffix.lower()
    kind = _TABULAR_SUFFIXES.get(suffix) or ("json" if suffix == ".json" else None)
    if kind is None or path.is_symlink():
        return None
    try:
        if kind == "json":
            text = _profile_json(path, max_bytes)
        else:
            min_group = k if k is not None else config.require_locality_min_group_size()
            text = _profile_table(path, kind, max_bytes, min_group)
    except RuntimeError as exc:
        if "LOCALITY_MIN_GROUP_SIZE" not in str(exc):
            logger.warning("Perfil de %s falhou: %s", path.name, type(exc).__name__)
            text = f"perfil: {kind}, não foi possível interpretar o arquivo"
        else:
            logger.error("Perfil de %s indisponível: %s", path.name, exc)
            text = f"perfil: {kind}, indisponível: {exc}"
    except Exception as exc:  # noqa: BLE001 - o perfil nunca derruba a revisão (inclui RecursionError, MemoryError)
        logger.warning("Perfil de %s falhou: %s", path.name, type(exc).__name__)
        text = f"perfil: {kind}, não foi possível interpretar o arquivo"
    return text if len(text) <= max_chars else text[: max(0, max_chars - 1)].rstrip() + "…"


def _read_prefix(path: Path, max_bytes: int) -> tuple[str, bool]:
    with _open_regular(path) as handle:
        raw = handle.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
        cut = raw.rfind(b"\n")
        raw = raw[: cut + 1] if cut >= 0 else raw  # descarta a última linha, possivelmente incompleta
    return raw.decode("utf-8", errors="replace"), truncated


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def _safe_label(name: str, index: int, prefix: str) -> str:
    """Rótulo de coluna/chave só com caracteres de nome; senão ``<prefix>_N``. Decimais viram marcador (R3, R6)."""
    candidate = name.strip()
    if _SAFE_LABEL_RE.fullmatch(candidate):
        return sanitize_artifact_name(candidate)
    return f"{prefix}_{index + 1}"


def _looks_like_header(cells: list[str]) -> bool:
    """Todos os campos são nomes: não vazios, nem número nem data, e casam o padrão de nome seguro (R1)."""
    for cell in cells:
        value = cell.strip()
        if not value or _is_number(value) or _DATE_RE.fullmatch(value) or not _SAFE_LABEL_RE.fullmatch(value):
            return False
        if re.search(r"\d+[.,]\d+", value):
            return False
    return True


def _profile_table(path: Path, kind: str, max_bytes: int, k: int) -> str:
    try:
        text, truncated = _read_prefix(path, max_bytes)
    except OSError:
        return f"perfil: {kind}, arquivo ilegível"
    default = "\t" if kind == "tsv" else ","
    try:
        delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = default
    if kind == "tsv" and delimiter != "\t":
        delimiter = "\t"
    max_columns = max(1, config.REVIEW_PROFILE_MAX_COLUMNS)
    max_rows = max(0, config.REVIEW_PROFILE_MAX_ROWS)
    deadline = time.monotonic() + config.REVIEW_PROFILE_MAX_SECONDS
    row_limited = timed_out = False
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        first = next(reader, None)
        if not first:
            return f"perfil: {kind}, arquivo vazio"
        total_width = len(first)
        width = min(total_width, max_columns)
        first = first[:width]
        nulls = [0] * width
        numeric = [True] * width
        seen = [False] * width

        def fold(cells: list[str]) -> None:
            for i in range(width):
                cell = cells[i].strip() if i < len(cells) else ""
                if cell.lower() in _NULL_TOKENS:
                    nulls[i] += 1
                    continue
                seen[i] = True
                if numeric[i] and not _is_number(cell):
                    numeric[i] = False

        header_ok = _looks_like_header(first)
        repeated_as_value = False
        rows = 0
        for row in reader:
            if not row:
                continue
            if rows >= max_rows:
                row_limited = True
                break
            rows += 1
            fold(row)
            if header_ok and not repeated_as_value:
                repeated_as_value = any(
                    i < len(row) and row[i].strip() == first[i].strip() for i in range(width)
                )
            if rows % _TIME_CHECK_EVERY_ROWS == 0 and time.monotonic() >= deadline:
                timed_out = True
                break
        if not (header_ok and not repeated_as_value):
            header_ok = False
            fold(first)  # a primeira linha é dado
            rows += 1
    except csv.Error:
        return f"perfil: {kind}, não foi possível interpretar o arquivo"
    if timed_out:
        count = f"≥ {rows} linhas (leitura interrompida por tempo)"
    elif truncated or row_limited:
        count = f"≥ {rows} linhas (lidas até o limite)"
    else:
        count = f"{rows} linhas de dados"
    columns = []
    for i in range(width):
        label = _safe_label(first[i], i, "coluna") if header_ok else f"coluna_{i + 1}"
        kind_name = "numérica" if seen[i] and numeric[i] else "texto"
        null_text = "nulos: omitido" if 0 < nulls[i] < k else f"{nulls[i]} nulos"
        columns.append(f"{label} ({kind_name}, {null_text})")
    head = f"perfil: {kind}, {count}, {total_width} colunas"
    if not header_ok:
        head = f"perfil: {kind}, sem cabeçalho reconhecido, {count}, {total_width} colunas"
    if total_width > width:
        return f"{head}\ncolunas: {total_width} (descrição limitada às primeiras {width})\n" + ", ".join(columns)
    return f"{head}\ncolunas: " + ", ".join(columns)


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "booleano"
    if isinstance(value, (int, float)):
        return "número"
    if isinstance(value, str):
        return "texto"
    if value is None:
        return "nulo"
    if isinstance(value, dict):
        return f"objeto com {len(value)} chaves"
    return f"lista[{len(value)}] de {_item_types(value)}"


def _item_types(items: list[Any]) -> str:
    kinds = {_type_name(i).split(" com ")[0].split("[")[0] if isinstance(i, (dict, list)) else _type_name(i)
             for i in items}
    return "|".join(sorted(kinds)) if kinds else "vazio"


def _describe(value: Any, path: str, depth: int, lines: list[str], cap: int) -> None:
    if depth >= _MAX_DEPTH or len(lines) >= cap:
        return
    if isinstance(value, dict):
        if len(value) > _MAX_MAP_KEYS:  # mapa (id -> valor): as chaves são dado, não estrutura (R6)
            return
        for index, (key, child) in enumerate(value.items()):
            if len(lines) >= cap:
                return
            label = _safe_label(str(key), index, "chave")
            child_path = f"{path}.{label}" if path else label
            lines.append(f"{child_path}: {_type_name(child)}")
            _describe(child, child_path, depth + 1, lines, cap)
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        _describe(value[0], f"{path}[]", depth, lines, cap)


def _exceeds_nesting(text: str, limit: int) -> bool:
    """``True`` se colchetes/chaves fora de strings aninham acima de ``limit`` (varredura linear, sem recursão)."""
    depth = 0
    pos = 0
    while True:
        match = _JSON_TOKEN_RE.search(text, pos)
        if match is None:
            return False
        token = match.group(0)
        pos = match.end()
        if token == '"':
            body = _JSON_STRING_BODY_RE.match(text, pos)
            if body is None:
                return False  # string sem fim: JSON inválido, o parser recusa
            pos = body.end()
        elif token in "[{":
            depth += 1
            if depth > limit:
                return True
        else:
            depth = max(0, depth - 1)


def _profile_json(path: Path, max_bytes: int) -> str:
    try:
        with _open_regular(path) as handle:
            raw = handle.read(max_bytes + 1)
    except OSError:
        return "perfil: json, não foi possível interpretar o arquivo"
    if len(raw) > max_bytes:
        return f"perfil: json, mais de {max_bytes} bytes (limite de leitura); estrutura não interpretada"
    text = raw.decode("utf-8", errors="replace")
    if _exceeds_nesting(text, _MAX_JSON_NESTING):
        return f"perfil: json, estrutura aninhada acima de {_MAX_JSON_NESTING} níveis; não interpretada"
    try:
        data = json.loads(text)
    except ValueError:
        return "perfil: json, não foi possível interpretar o arquivo"
    max_lines = max(0, config.REVIEW_PROFILE_MAX_JSON_LINES)
    lines = [f"perfil: json, {_type_name(data)}"]
    _describe(data, "", 0, lines, max_lines + 2)
    if len(lines) > max_lines + 1:
        lines = lines[: max_lines + 1]
        lines.append(f"(descrição limitada às primeiras {max_lines} linhas de chaves)")
    return "\n".join(lines)
