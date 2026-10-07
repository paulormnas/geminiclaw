"""Descritores sem valores para dados de pesquisa (v17-input-document-index, design §2; ADR 019 §3.1).

Conjuntos de dados, imagens e arquivos de outros tipos entram no índice como **um único ponto
descritor**: nome, formato, tamanho e estrutura (colunas com tipo inferido, contagens, dimensões).
Nenhum valor de registro, célula ou texto de OCR é lido para o texto do descritor.
"""

from __future__ import annotations

import csv
import json
import re
import struct
from pathlib import Path

from src.logger import get_logger

logger = get_logger(__name__)

IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"})
_MAX_COLUMNS = 200
_MAX_NAME_CHARS = 80
_TYPE_SAMPLE_ROWS = 1000
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+[.,]?\d*|[.,]\d+)([eE][+-]?\d+)?$")
_BOOL = frozenset({"true", "false", "sim", "não", "nao", "yes", "no"})


def _name(value: object) -> str:
    return " ".join(str(value).split())[:_MAX_NAME_CHARS]


def _is_number(cell: str) -> bool:
    return bool(_INT_RE.match(cell) or _FLOAT_RE.match(cell))


def _cell_type(cell: str) -> str | None:
    cell = cell.strip()
    if not cell:
        return None
    if _INT_RE.match(cell):
        return "inteiro"
    if _FLOAT_RE.match(cell):
        return "decimal"
    if cell.lower() in _BOOL:
        return "booleano"
    return "texto"


def _merge_types(seen: set[str]) -> str:
    if not seen:
        return "vazio"
    if len(seen) == 1:
        return next(iter(seen))
    if seen <= {"inteiro", "decimal"}:
        return "decimal"
    return "misto"


def _base(path: Path, formato: str) -> str:
    size = path.stat().st_size
    return f"Arquivo: {_name(path.name)} | formato: {formato} | tamanho: {size} bytes"


def _delimited(path: Path, delimiter: str) -> str:
    encoding = "utf-8"
    try:
        path.open("r", encoding="utf-8").read(1 << 20)
    except UnicodeDecodeError:
        encoding = "latin-1"
    rows = 0
    types: list[set[str]] = []
    header: list[str] = []
    with path.open("r", encoding=encoding, newline="") as handle:
        for row in csv.reader(handle, delimiter=delimiter):
            if not header:
                header = row[:_MAX_COLUMNS]
                types = [set() for _ in header]
                continue
            rows += 1
            if rows <= _TYPE_SAMPLE_ROWS:
                for i, cell in enumerate(row[: len(types)]):
                    kind = _cell_type(cell)
                    if kind:
                        types[i].add(kind)
    # Cabeçalho feito só de números seria dado, não nome de coluna: nunca vai ao descritor.
    if header and all(_is_number(c.strip()) for c in header if c.strip()):
        header = [f"coluna_{i + 1}" for i in range(len(header))]
        rows += 1
    cols = ", ".join(f"{_name(c)} ({_merge_types(t)})" for c, t in zip(header, types))
    sep = {",": "vírgula", "\t": "tabulação", ";": "ponto e vírgula"}.get(delimiter, "outro")
    return (
        f"{rows} linhas | {len(header)} colunas | codificação: {encoding} | separador: {sep}\n"
        f"Colunas: {cols}"
    )


def _json_structure(path: Path, jsonl: bool) -> str:
    def keys_of(obj: object) -> str:
        if isinstance(obj, dict):
            return ", ".join(f"{_name(k)} ({type(v).__name__})" for k, v in list(obj.items())[:_MAX_COLUMNS])
        return type(obj).__name__

    if jsonl:
        count, first = 0, None
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    count += 1
                    if first is None:
                        first = json.loads(line)
        return f"{count} registros\nCampos: {keys_of(first)}"
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return f"{len(data)} registros\nCampos: {keys_of(data[0]) if data else ''}"
    return f"objeto com {len(data) if isinstance(data, dict) else 0} chaves\nCampos: {keys_of(data)}"


def _pandas_structure(path: Path, ext: str) -> str:
    import pandas as pd

    if ext == ".parquet":
        frames = {"": pd.read_parquet(path)}
    else:
        frames = pd.read_excel(path, sheet_name=None)
    parts = []
    for sheet, df in frames.items():
        cols = ", ".join(f"{_name(c)} ({_pandas_kind(df[c])})" for c in list(df.columns)[:_MAX_COLUMNS])
        label = f"Aba {_name(sheet)}: " if sheet else ""
        parts.append(f"{label}{len(df)} linhas | {len(df.columns)} colunas\nColunas: {cols}")
    return "\n".join(parts)


def _pandas_kind(series: object) -> str:
    kind = getattr(getattr(series, "dtype", None), "kind", "O")
    return {"i": "inteiro", "u": "inteiro", "f": "decimal", "b": "booleano", "M": "data"}.get(kind, "texto")


def describe_dataset(path: Path) -> str:
    """Descritor de um conjunto de dados: colunas com tipo, contagens; nunca valores.

    Formatos que não puderem ser lidos (biblioteca ausente, arquivo corrompido) recebem só nome,
    formato e tamanho, com um aviso no log.
    """
    ext = path.suffix.lower()
    head = f"Conjunto de dados — {_base(path, ext.lstrip('.') or 'desconhecido')}"
    try:
        if ext == ".csv":
            body = _delimited(path, ",")
        elif ext == ".tsv":
            body = _delimited(path, "\t")
        elif ext in (".json", ".jsonl"):
            body = _json_structure(path, ext == ".jsonl")
        elif ext in (".xlsx", ".xls", ".ods", ".parquet"):
            body = _pandas_structure(path, ext)
        else:
            body = ""
    except Exception as exc:  # noqa: BLE001 - descritor mínimo em vez de falhar a indexação
        logger.warning(
            "Estrutura do conjunto de dados não pôde ser lida; descritor mínimo",
            extra={"arquivo": _name(path.name), "erro": type(exc).__name__},
        )
        body = ""
    return f"{head}\n{body}" if body else head


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:  # noqa: BLE001 - sem Pillow ou formato não suportado: lê o cabeçalho
        pass
    try:
        with path.open("rb") as handle:
            data = handle.read(32)
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", data[16:24])
            if data[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", data[6:10])
            if data[:2] == b"BM":
                w, h = struct.unpack("<ii", data[18:26])
                return w, abs(h)
            if data[:2] == b"\xff\xd8":
                handle.seek(2)
                while True:
                    marker = handle.read(4)
                    if len(marker) < 4 or marker[0] != 0xFF:
                        return None
                    length = struct.unpack(">H", marker[2:4])[0]
                    if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                        h, w = struct.unpack(">HH", handle.read(5)[1:5])
                        return w, h
                    handle.seek(length - 2, 1)
    except (OSError, struct.error):
        return None
    return None


def describe_image(path: Path) -> str:
    """Descritor de imagem: nome, formato e dimensões; sem OCR nem descrição por modelo."""
    ext = path.suffix.lower().lstrip(".")
    head = f"Imagem — {_base(path, ext)}"
    size = _image_size(path)
    return f"{head}\nDimensões: {size[0]}x{size[1]} px" if size else head


def describe_other(path: Path) -> str:
    """Descritor de arquivo de tipo desconhecido: nome, formato e tamanho."""
    return f"Arquivo — {_base(path, path.suffix.lower().lstrip('.') or 'desconhecido')}"
