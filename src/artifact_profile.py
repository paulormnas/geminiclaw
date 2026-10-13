"""Perfil estrutural de artefatos de dados para o revisor (``v18.6-review-evidence`` §4).

Descreve a *forma* de um CSV/TSV ou JSON (linhas, colunas, tipos, chaves, tamanhos de listas, nulos por coluna) sem
nenhum valor de célula. O perfil é calculado no nó, sobre arquivos já gravados em ``outputs/``, e sai rotulado
``esquema_agregado`` (ADR 019 §3). Só biblioteca padrão; a leitura de CSV é em fluxo, limitada a ``max_bytes``.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from src import config
from src.knowledge.normalization import clean_free_text

_NULL_TOKENS = frozenset({"", "na", "n/a", "nan", "null", "none"})
_MAX_DEPTH = 3
_MAX_COLUMN_NAME_CHARS = 80
_TABULAR_SUFFIXES = {".csv": "csv", ".tsv": "tsv"}


def profile_artifact(
    path: Path, *, max_bytes: int, max_chars: int, k: int | None = None
) -> str | None:
    """Descrição estrutural de um CSV/TSV ou JSON, sem nenhum valor de célula; ``None`` para outros tipos.

    Args:
        path: Arquivo a descrever.
        max_bytes: Limite de leitura; acima dele o CSV vira contagem parcial e o JSON não é interpretado.
        max_chars: Tamanho máximo do perfil (excedente é cortado com ``…``).
        k: Tamanho mínimo de grupo (``LOCALITY_MIN_GROUP_SIZE``); padrão, o valor da configuração. Contagem de nulos
            entre 1 e ``k - 1`` é omitida (grupo pequeno, ADR 019 §3).

    Returns:
        Texto do perfil ou ``None`` se o tipo não é suportado.
    """
    suffix = path.suffix.lower()
    if suffix in _TABULAR_SUFFIXES:
        min_group = k if k is not None else config.require_locality_min_group_size()
        text = _profile_table(path, _TABULAR_SUFFIXES[suffix], max_bytes, min_group)
    elif suffix == ".json":
        text = _profile_json(path, max_bytes)
    else:
        return None
    return text if len(text) <= max_chars else text[: max(0, max_chars - 1)].rstrip() + "…"


def _read_prefix(path: Path, max_bytes: int) -> tuple[str, bool]:
    with path.open("rb") as handle:
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
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        header = next(reader, None)
        if not header:
            return f"perfil: {kind}, arquivo vazio"
        width = len(header)
        nulls = [0] * width
        numeric = [True] * width
        seen = [False] * width
        rows = 0
        for row in reader:
            if not row:
                continue
            rows += 1
            for i in range(width):
                cell = row[i].strip() if i < len(row) else ""
                if cell.lower() in _NULL_TOKENS:
                    nulls[i] += 1
                    continue
                seen[i] = True
                if numeric[i] and not _is_number(cell):
                    numeric[i] = False
    except csv.Error:
        return f"perfil: {kind}, não foi possível interpretar o arquivo"
    count = f"≥ {rows} linhas (lidas até o limite)" if truncated else f"{rows} linhas de dados"
    columns = []
    for i, name in enumerate(header):
        label = clean_free_text(name)[:_MAX_COLUMN_NAME_CHARS] or f"coluna_{i + 1}"
        kind_name = "numérica" if seen[i] and numeric[i] else "texto"
        null_text = "nulos: omitido" if 0 < nulls[i] < k else f"{nulls[i]} nulos"
        columns.append(f"{label} ({kind_name}, {null_text})")
    return f"perfil: {kind}, {count}, {width} colunas\ncolunas: " + ", ".join(columns)


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


def _describe(value: Any, path: str, depth: int, lines: list[str]) -> None:
    if depth >= _MAX_DEPTH:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{clean_free_text(str(key))[:_MAX_COLUMN_NAME_CHARS]}" if path else (
                clean_free_text(str(key))[:_MAX_COLUMN_NAME_CHARS]
            )
            lines.append(f"{child_path}: {_type_name(child)}")
            _describe(child, child_path, depth + 1, lines)
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        _describe(value[0], f"{path}[]", depth, lines)


def _profile_json(path: Path, max_bytes: int) -> str:
    try:
        size = path.stat().st_size
        if size > max_bytes:
            return f"perfil: json, {size} bytes acima do limite de leitura; estrutura não interpretada"
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return "perfil: json, não foi possível interpretar o arquivo"
    lines = [f"perfil: json, {_type_name(data)}"]
    _describe(data, "", 0, lines)
    return "\n".join(lines)
