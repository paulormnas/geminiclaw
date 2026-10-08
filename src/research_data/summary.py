"""Resumo seguro de datasets: esquema, descritores de formato e estatísticas pela regra de k (design §4).

O resumo nunca contém valores de célula, rótulos de categorias, mínimo, máximo ou quantis exatos. Abaixo de ``k``
valores não nulos só a contagem e o tipo aparecem; a partir de ``k``, média, desvio e faixa arredondada (numéricas),
número de valores distintos (categóricas) e anos extremos (datas). ``k=None`` (não configurado) é tratado como "toda
coluna abaixo de k": falha para o lado seguro.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

_UNIT_RE = re.compile(r"[\(\[]\s*([^\)\]]{1,32}?)\s*[\)\]]\s*$")
_DECIMAL_COMMA_RE = re.compile(r"^-?\d+,\d+$")
_DECIMAL_DOT_RE = re.compile(r"^-?\d+\.\d+$")
_NUMBER_LIKE_RE = re.compile(r"^[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?$")
_SNIFF_BYTES = 64 * 1024
_SNIFF_LINES = 50
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
)
_DATE_SAMPLE = 200
_DATE_MIN_FRACTION = 0.9

KIND_NUMERIC = "numerica"
KIND_CATEGORICAL = "categorica"
KIND_DATE = "data"
KIND_OTHER = "outro"


@dataclass(frozen=True)
class FormatInfo:
    """Descritores de formato de um arquivo de texto delimitado (sem valores)."""

    codificacao: str = "utf-8"
    separador: str = ","
    decimal: str = "."
    cabecalho: bool = True


@dataclass
class ColumnSummary:
    """Resumo seguro de uma coluna."""

    nome: str
    dtype: str
    unidade: str | None
    n: int
    nulos: int
    tipo: str
    abaixo_de_k: bool
    media: float | None = None
    desvio: float | None = None
    faixa: tuple[str, str] | None = None
    distintos: int | None = None
    ano_inicial: int | None = None
    ano_final: int | None = None
    formato_data: str | None = None

    def render(self) -> str:
        label = self.nome + (f" [unidade {self.unidade}]" if self.unidade else "")
        nulls = f", nulos={self.nulos}" if self.nulos else ""
        if self.abaixo_de_k:
            return f"- {label}: {self.dtype}, n={self.n}{nulls} (abaixo de k: sem estatísticas)"
        if self.tipo == KIND_NUMERIC and self.faixa is not None:
            return (
                f"- {label}: {self.dtype}, n={self.n}{nulls}, média {_fmt(self.media)}, desvio {_fmt(self.desvio)}, "
                f"faixa ≈ [{self.faixa[0]}, {self.faixa[1]}]"
            )
        if self.tipo == KIND_DATE:
            fmt = f" ({self.formato_data})" if self.formato_data else ""
            return f"- {label}: datetime{fmt}, n={self.n}{nulls}, anos {self.ano_inicial}–{self.ano_final}"
        if self.tipo == KIND_CATEGORICAL:
            return f"- {label}: {self.dtype}, n={self.n}{nulls}, {self.distintos} valores distintos"
        return f"- {label}: {self.dtype}, n={self.n}{nulls}"


@dataclass
class SafeDatasetSummary:
    """Trecho ``esquema_agregado`` de um dataset."""

    nome: str
    formato: str
    tamanho_bytes: int
    linhas: int
    colunas: list[ColumnSummary] = field(default_factory=list)
    aba: str | None = None
    formato_texto: FormatInfo | None = None
    k: int | None = None

    def render(self) -> str:
        label = self.nome + (f" [{self.aba}]" if self.aba else "")
        lines = [f"Dataset: {label} ({self.formato}, {self.tamanho_bytes} bytes)"]
        info = self.formato_texto
        if info is not None:
            header = "presente" if info.cabecalho else "ausente"
            lines.append(
                f"Formato: codificação {info.codificacao}; separador {_show_sep(info.separador)}; "
                f"decimal '{info.decimal}'; cabeçalho {header}"
            )
        lines.append(f"Linhas: {self.linhas} | Colunas: {len(self.colunas)}")
        lines.extend(col.render() for col in self.colunas)
        return "\n".join(lines)


def _show_sep(sep: str) -> str:
    return "TAB" if sep == "\t" else f"'{sep}'"


def _fmt(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/d"
    return f"{value:.4g}"


# --- faixa a um algarismo significativo ---------------------------------------------------------------------------

def _step(value: Decimal) -> Decimal:
    return Decimal(1).scaleb(value.adjusted())


def _fmt_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def floor_1sig(value: float) -> str:
    """Arredonda para baixo a um algarismo significativo (``12.3`` -> ``10``; ``-12.3`` -> ``-20``)."""
    number = Decimal(repr(float(value)))
    if number == 0:
        return "0"
    step = _step(number)
    return _fmt_decimal((number / step).to_integral_value(rounding="ROUND_FLOOR") * step)


def ceil_1sig(value: float) -> str:
    """Arredonda para cima a um algarismo significativo (``38.9`` -> ``40``; ``-3.2`` -> ``-3``)."""
    number = Decimal(repr(float(value)))
    if number == 0:
        return "0"
    step = _step(number)
    return _fmt_decimal((number / step).to_integral_value(rounding="ROUND_CEILING") * step)


# --- descritores de formato ---------------------------------------------------------------------------------------

def detect_text_format(path: Path, fmt: str) -> FormatInfo:
    """Codificação, separador, decimal e cabeçalho de um CSV/TSV, lidos dos primeiros bytes (sem expor valores)."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(_SNIFF_BYTES)
    except OSError:
        return FormatInfo(separador="\t" if fmt == "tsv" else ",")
    encoding = "utf-8"
    try:
        text = _decode_prefix(raw)
    except UnicodeDecodeError:
        encoding = "latin-1"
        text = raw.decode("latin-1")
    lines = [line for line in text.splitlines() if line.strip()][:_SNIFF_LINES]
    sample = "\n".join(lines)
    separator = "\t" if fmt == "tsv" else ","
    if fmt != "tsv" and sample:
        try:
            separator = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            separator = _most_common_separator(lines)
    rows = [row for row in csv.reader(io.StringIO(sample), delimiter=separator)] if sample else []
    decimal = _detect_decimal(rows, separator)
    header = _has_header(rows)
    return FormatInfo(encoding, separator, decimal, header)


def _decode_prefix(raw: bytes) -> str:
    import codecs

    return codecs.getincrementaldecoder("utf-8")().decode(raw, final=False)


def _most_common_separator(lines: list[str]) -> str:
    counts = {sep: sum(line.count(sep) for line in lines) for sep in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)  # type: ignore[arg-type]
    return best if counts[best] else ","


def _detect_decimal(rows: list[list[str]], separator: str) -> str:
    if separator == ",":
        return "."
    comma = dot = 0
    for row in rows[1:] or rows:
        for cell in row:
            token = cell.strip()
            if _DECIMAL_COMMA_RE.match(token):
                comma += 1
            elif _DECIMAL_DOT_RE.match(token):
                dot += 1
    return "," if comma > dot else "."


def _has_header(rows: list[list[str]]) -> bool:
    if not rows:
        return True
    first = [cell.strip() for cell in rows[0] if cell.strip()]
    if not first:
        return True
    return not any(_NUMBER_LIKE_RE.match(token) for token in first)


# --- colunas ------------------------------------------------------------------------------------------------------

def _unit_from_header(name: str) -> str | None:
    match = _UNIT_RE.search(name)
    return match.group(1) if match else None


def _detect_date_format(series) -> str | None:  # noqa: ANN001
    import pandas as pd

    sample = series.dropna().astype(str).head(_DATE_SAMPLE)
    if sample.empty:
        return None
    for fmt in _DATE_FORMATS:
        parsed = pd.to_datetime(sample, format=fmt, errors="coerce")
        if parsed.notna().mean() >= _DATE_MIN_FRACTION:
            return fmt
    return None


def summarize_column(series, name: str, k: int | None) -> ColumnSummary:  # noqa: ANN001
    """Resumo seguro de uma coluna (``series`` do pandas)."""
    import pandas as pd
    from pandas.api import types as pdt

    n = int(series.notna().sum())
    nulls = int(series.isna().sum())
    dtype = str(series.dtype)
    unit = _unit_from_header(name)
    below = k is None or n < k
    date_format: str | None = None
    parsed_dates = None
    if pdt.is_datetime64_any_dtype(series):
        kind = KIND_DATE
        parsed_dates = series
        date_format = "nativo"
    elif pdt.is_bool_dtype(series):
        kind = KIND_CATEGORICAL
    elif pdt.is_numeric_dtype(series):
        kind = KIND_NUMERIC
    elif pdt.is_object_dtype(series) or pdt.is_string_dtype(series):
        date_format = None if below else _detect_date_format(series)
        if date_format:
            kind = KIND_DATE
            parsed_dates = pd.to_datetime(series, format=date_format, errors="coerce")
        else:
            kind = KIND_CATEGORICAL
    else:
        kind = KIND_OTHER
    column = ColumnSummary(name, dtype, unit, n, nulls, kind, below)
    if below or n == 0:
        column.abaixo_de_k = True
        return column
    if kind == KIND_NUMERIC:
        values = series.dropna().astype(float)
        column.media = float(values.mean())
        column.desvio = float(values.std()) if len(values) > 1 else 0.0
        column.faixa = (floor_1sig(float(values.min())), ceil_1sig(float(values.max())))
    elif kind == KIND_CATEGORICAL:
        column.distintos = int(series.dropna().nunique())
    elif kind == KIND_DATE and parsed_dates is not None:
        valid = parsed_dates.dropna()
        if len(valid):
            column.ano_inicial = int(valid.min().year)
            column.ano_final = int(valid.max().year)
        column.formato_data = date_format
    return column


def build_safe_summary(
    df: Any,
    *,
    name: str,
    fmt: str,
    size_bytes: int,
    k: int | None,
    sheet: str | None = None,
    format_info: FormatInfo | None = None,
) -> SafeDatasetSummary:
    """Resumo seguro de um ``DataFrame`` (``k`` = ``LOCALITY_MIN_GROUP_SIZE``)."""
    columns = [summarize_column(df[col], str(col), k) for col in df.columns]
    return SafeDatasetSummary(
        nome=name,
        formato=fmt,
        tamanho_bytes=size_bytes,
        linhas=int(len(df)),
        colunas=columns,
        aba=sheet,
        formato_texto=format_info,
        k=k,
    )
