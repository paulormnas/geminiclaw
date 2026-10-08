"""Filtros de egresso (v18.5-egress-gate, design §3 e §4).

Funções puras e determinísticas sobre texto. O :class:`ExecutionOutputFilter` aplica, na ordem, tracebacks, despejos
tabulares e estatísticas, e a elisão por tamanho (design §3.1-§3.4); :func:`mask_numbers` troca números literais por
marcadores tipados (design §4); :func:`sanitize_artifact_name` trata nomes de artefatos (design §3.5).

Os filtros são **heurísticos** (ADR 019 §3, limite declarado): reduzem e registram o egresso, não o impedem de forma
absoluta. Cada intervenção é contada por tipo para o registro de egresso.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Iterable

# Tipos de intervenção (design §8).
IV_TRACEBACK = "traceback_literal"
IV_TABELA = "tabela_retida"
IV_ESTATISTICA_RETIDA = "estatistica_retida"
IV_EXTREMO = "extremo_em_faixa"
IV_SEM_N = "estatistica_sem_n"
IV_ELISAO = "elisao"
IV_NUMERO = "numero_contaminado"
IV_DADO_RETIDO = "dado_de_pesquisa_retido"
IV_COMPARTILHAVEL = "compartilhavel_liberado"
IV_SEM_ORIGEM = "fragmento_sem_origem"
IV_CONSULTA_RECUSADA = "consulta_recusada"
IV_LIMITE_EGRESSO = "saida_retida_limite_egresso"

# Nomes de tipo que são esquema, não valor (podem ficar em mensagens de exceção entre aspas).
_TYPE_NAMES = frozenset(
    {
        "int", "float", "str", "bool", "list", "dict", "tuple", "set", "bytes", "object", "complex", "NoneType",
        "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "float16", "float32", "float64",
        "category", "datetime64[ns]", "timedelta64[ns]", "string", "boolean", "Int64", "Float64",
    }
)


@dataclass
class FilterContext:
    """Parâmetros do filtro para uma saída."""

    k: int  # LOCALITY_MIN_GROUP_SIZE
    output_max_chars: int  # EGRESS_OUTPUT_MAX_CHARS
    table_min_rows: int  # EGRESS_TABLE_MIN_ROWS
    known_identifiers: frozenset[str] = frozenset()
    integral_path: str | None = None
    interventions: Counter = field(default_factory=Counter)

    def note(self, kind: str, amount: int = 1) -> None:
        if amount:
            self.interventions[kind] += amount

    @property
    def where(self) -> str:
        return f"integral em {self.integral_path}" if self.integral_path else "integral no nó"


# --------------------------------------------------------------------------------------------------------------
# Números literais (design §4)
# --------------------------------------------------------------------------------------------------------------

_PROTECTED_RE = re.compile(
    r"\{\{(?:res|calc|src):[^}]*\}\}"  # referências (renderização é da v18.5-numeric-references)
    r"|<(?:num|str)\b[^>]*>"  # marcadores já emitidos
    r"|<estatística retida[^>]*>"
    r"|\[(?:dado de pesquisa retido|saída tabular retida|saída de execução retida|\.\.\.)[^\]]*\]"
)
_NUM_RE = re.compile(
    r"(?<![\w.])[-+]?(?:\d+(?:[.,]\d+)*|\.\d+)(?:[eE][-+]?\d+)?%?"
)


def number_pattern(literal: str) -> str:
    """Padrão de um literal numérico: cada dígito vira ``d``; os demais caracteres são mantidos."""
    return re.sub(r"\d", "d", literal)


def number_marker(literal: str) -> str:
    return f"<num padrão={number_pattern(literal)}>"


def mask_numbers(text: str) -> tuple[str, int]:
    """Troca números literais isolados por ``<num padrão=...>``; mantém referências, marcadores e identificadores.

    Returns:
        ``(texto, quantidade de números trocados)``.
    """
    count = 0

    def _mask_piece(piece: str) -> str:
        nonlocal count

        def repl(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return number_marker(match.group(0))

        return _NUM_RE.sub(repl, piece)

    out: list[str] = []
    pos = 0
    for match in _PROTECTED_RE.finditer(text):
        out.append(_mask_piece(text[pos : match.start()]))
        out.append(match.group(0))
        pos = match.end()
    out.append(_mask_piece(text[pos:]))
    return "".join(out), count


# --------------------------------------------------------------------------------------------------------------
# Faixas arredondadas (design §3.3)
# --------------------------------------------------------------------------------------------------------------

def _fmt_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def rounded_range(literal: str) -> str | None:
    """Faixa arredondada de um literal numérico: ``12.537`` -> ``[10, 20)``; zero -> ``0``; inválido -> ``None``."""
    raw = literal.strip()
    suffix = ""
    if raw.endswith("%"):
        raw, suffix = raw[:-1], "%"
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    if value == 0:
        return "0"
    magnitude = Decimal(1).scaleb(value.adjusted())
    quotient = math.floor(value / magnitude)
    low = quotient * magnitude
    high = (quotient + 1) * magnitude
    return f"[{_fmt_decimal(low)}{suffix}, {_fmt_decimal(high)}{suffix})"


# --------------------------------------------------------------------------------------------------------------
# Tracebacks (design §3.1)
# --------------------------------------------------------------------------------------------------------------

_TB_HEADER = "Traceback (most recent call last):"
_EXC_SEARCH_RE = re.compile(
    r"(?P<type>\b[A-Za-z_][\w.]{0,80}(?:Error|Exception|Warning|Exit|Interrupt))(?P<sep>:[ \t]*)(?P<msg>\S.*)$"
)
_TB_FINAL_RE = re.compile(r"^(?P<type>[A-Za-z_][\w.]{0,80})(?P<sep>:[ \t]*)(?P<msg>.*)$")
_QUOTED_RE = re.compile(r"(?<!\w)(?P<q>['\"])(?P<s>(?:\\.|(?!(?P=q)).)*?)(?P=q)(?!\w)")
_STR_PATTERN_MAX = 32


def _string_marker(inner: str) -> str:
    length = len(inner)
    if length > _STR_PATTERN_MAX:
        return f"<str len={length}>"
    pattern = "".join("d" if c.isdigit() else "a" if c.isalpha() else c for c in inner)
    return f"<str len={length} padrão={pattern}>"


def _mask_exception_message(message: str, ctx: FilterContext) -> str:
    """Troca literais (aspas e números) da mensagem por marcadores tipados; identificadores conhecidos ficam."""
    out: list[str] = []
    pos = 0
    changed = 0
    for match in _QUOTED_RE.finditer(message):
        out.append(_mask_numbers_counting(message[pos : match.start()], ctx))
        inner = match.group("s")
        if inner in ctx.known_identifiers or inner in _TYPE_NAMES:
            out.append(match.group(0))
        else:
            out.append(_string_marker(inner))
            changed += 1
        pos = match.end()
    out.append(_mask_numbers_counting(message[pos:], ctx))
    ctx.note(IV_TRACEBACK, changed)
    return "".join(out)


def _mask_numbers_counting(piece: str, ctx: FilterContext) -> str:
    masked, count = mask_numbers(piece)
    ctx.note(IV_TRACEBACK, count)
    return masked


def _mask_exception_line(line: str, ctx: FilterContext, *, final: bool) -> str:
    match = _TB_FINAL_RE.match(line) if final else None
    if match is None:
        match = _EXC_SEARCH_RE.search(line)
    if match is None:
        # Fim de traceback sem o formato `Tipo: mensagem` (ex.: `StopIteration`): nada a trocar.
        return line
    start = match.start("msg")
    return line[:start] + _mask_exception_message(match.group("msg"), ctx)


def filter_tracebacks(text: str, ctx: FilterContext) -> str:
    """Mantém tipo, arquivo, linha e forma da mensagem; literais da mensagem viram marcadores tipados."""
    if "Error" not in text and "Exception" not in text and _TB_HEADER not in text and "Warning" not in text:
        return text
    out: list[str] = []
    in_traceback = False
    for line in text.split("\n"):
        if _TB_HEADER in line:
            in_traceback = True
            out.append(line)
        elif in_traceback:
            if not line.strip() or line[:1] in (" ", "\t"):
                out.append(line)  # linhas `File "...", line N, in f` e a linha de código ecoada
            else:
                in_traceback = False
                out.append(_mask_exception_line(line, ctx, final=True))
        else:
            out.append(_mask_exception_line(line, ctx, final=False) if _EXC_SEARCH_RE.search(line) else line)
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------------------
# Tokens e linhas numéricas
# --------------------------------------------------------------------------------------------------------------

_NUMTOK_RE = re.compile(r"^[-+]?(?:\d+(?:[.,]\d*)?|\.\d+)(?:[eE][-+]?\d+)?%?$")
_SPECIAL_NUM = frozenset({"nan", "inf", "-inf", "+inf", "NaN", "NA", "<NA>", "None"})
_FIELD_SPLIT_RE = re.compile(r"[\t;,]|\s+")


def _is_numeric_token(token: str) -> bool:
    return bool(_NUMTOK_RE.match(token)) or token in _SPECIAL_NUM


def _fields(line: str) -> list[str]:
    """Campos de uma linha, separados por espaço, vírgula, ponto e vírgula ou tab."""
    return [f for f in _FIELD_SPLIT_RE.split(line.strip()) if f != ""]


_KEYVALUE_RE = re.compile(r"^\s{0,16}[A-Za-z_%][\w .%/\-]{0,63}\s{0,8}[:=]\s{0,8}\S")


def _is_keyvalue_line(line: str) -> bool:
    return bool(_KEYVALUE_RE.match(line))


def _table_marker(rows: int, cols: int, columns: str, ctx: FilterContext) -> str:
    ctx.note(IV_TABELA)
    names = columns or "(não reconhecidas)"
    return f"[saída tabular retida: {rows} linhas × {cols} colunas; colunas: {names}; {ctx.where}]"


def _header_columns(line: str) -> list[str]:
    tokens = _fields(line)
    if tokens and not any(_is_numeric_token(t) for t in tokens):
        return tokens
    return []


# --------------------------------------------------------------------------------------------------------------
# describe() (design §3.3)
# --------------------------------------------------------------------------------------------------------------

_DESC_NUMERIC = ("count", "mean", "std", "min", "25%", "50%", "75%", "max")
_DESC_LABELS = frozenset(_DESC_NUMERIC) | {"unique", "top", "freq"}
_EXTREME_ROWS = frozenset({"min", "25%", "50%", "75%", "max"})


def _split_columns(header: str, n_values: int) -> list[str] | None:
    """Nomes de coluna do cabeçalho de ``describe()`` quando a contagem confere; senão ``None``."""
    parts = header.split()
    if len(parts) == n_values:
        return parts
    wide = [p for p in re.split(r"\s{2,}", header.strip()) if p]
    if len(wide) == n_values:
        return wide
    return None


def filter_describe(lines: list[str], ctx: FilterContext) -> list[str]:
    """Troca o bloco de ``describe()`` por uma linha por coluna sob a regra de k e de extremos em faixa."""
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        first = lines[i].split()
        if first and first[0] == "count" and len(first) >= 2:
            j = i
            rows: dict[str, list[str]] = {}
            while j < n:
                parts = lines[j].split()
                if not parts or parts[0] not in _DESC_LABELS or len(parts) < 2:
                    break
                rows[parts[0]] = parts[1:]
                j += 1
            labels = set(rows)
            width = len(rows["count"])
            numeric_block = {"count", "mean", "std", "min", "max"} <= labels
            object_block = {"count", "unique", "top", "freq"} <= labels
            if (numeric_block or object_block) and all(len(v) == width for v in rows.values()):
                columns: list[str] | None = None
                if out and out[-1].strip() and not any(_is_numeric_token(t) for t in out[-1].split()):
                    columns = _split_columns(out[-1], width)
                    if columns is not None:
                        out.pop()
                if columns is None:
                    columns = ["valor"] if width == 1 else [f"coluna_{c + 1}" for c in range(width)]
                if j < n and lines[j].startswith("Name:"):
                    j += 1
                out.extend(_describe_column_lines(columns, rows, ctx))
                i = j
                continue
        out.append(lines[i])
        i += 1
    return out


def _describe_column_lines(columns: list[str], rows: dict[str, list[str]], ctx: FilterContext) -> list[str]:
    result: list[str] = []
    for index, column in enumerate(columns):
        count_token = rows["count"][index]
        try:
            n_value: float | None = float(count_token.replace(",", "."))
        except ValueError:
            n_value = None
        pieces = [f"count={count_token}"]
        for label in ("unique", "freq"):
            if label in rows:
                pieces.append(f"{label}={rows[label][index]}")
        if "top" in rows:
            pieces.append("top=<valor retido>")
            ctx.note(IV_ESTATISTICA_RETIDA)
        for label in ("mean", "std"):
            if label not in rows:
                continue
            value = rows[label][index]
            if n_value is None:
                ctx.note(IV_SEM_N)
                pieces.append(f"{label}={value}")
            elif n_value < ctx.k:
                ctx.note(IV_ESTATISTICA_RETIDA)
                pieces.append(f"{label}=<estatística retida: n<k>")
            else:
                pieces.append(f"{label}={value}")
        for label in ("min", "25%", "50%", "75%", "max"):
            if label not in rows:
                continue
            value = rows[label][index]
            ranged = rounded_range(value)
            ctx.note(IV_EXTREMO)
            pieces.append(f"{label}={ranged if ranged is not None else '<valor retido>'}")
        result.append(f"{column}: " + ", ".join(pieces))
    return result


# --------------------------------------------------------------------------------------------------------------
# Despejos tabulares (design §3.2)
# --------------------------------------------------------------------------------------------------------------

_DF_FOOTER_RE = re.compile(r"\[(\d+) rows x (\d+) columns\]")
_SERIES_FOOTER_RE = re.compile(r"^(?:Name: (?P<name>.*?), )?(?:Length: (?P<length>\d+), )?dtype: [\w\[\]]+\s*$")
_DTYPE_NAME_RE = re.compile(
    r"^(?:u?int\d*|float\d*|object|bool|boolean|string|category|datetime64\[\w+\]|timedelta64\[\w+\]|complex\d*)$"
)


def _dtype_listing_start(out: list[str]) -> int | None:
    """Início do sufixo de ``out`` que é uma listagem de ``df.dtypes`` (`coluna  tipo`): é esquema, não dado."""
    start = len(out)
    while start > 0:
        parts = out[start - 1].split()
        if len(parts) >= 2 and _DTYPE_NAME_RE.match(parts[-1]):
            start -= 1
        else:
            break
    return start if start < len(out) else None


def _repr_header(block: list[str]) -> list[str]:
    """Cabeçalho de um `repr` de DataFrame: a linha de nomes que antecede a primeira linha com índice inteiro."""
    for index in range(len(block) - 1):
        names = _header_columns(block[index])
        following = block[index + 1].split()
        if names and following and following[0].isdigit():
            return names
    return _header_columns(block[0]) if block else []


def filter_footer_tables(lines: list[str], ctx: FilterContext) -> list[str]:
    """Retém reprs de DataFrame (rodapé `[N rows x M columns]`) e de Series (rodapé `dtype:`), em qualquer tamanho."""
    out: list[str] = []
    for line in lines:
        footer = _DF_FOOTER_RE.search(line)
        series = _SERIES_FOOTER_RE.match(line.strip()) if not footer else None
        if footer is None and series is None:
            out.append(line)
            continue
        # O bloco já emitido é o sufixo contíguo e não vazio de `out` (uma linha em branco antes do rodapé é tolerada).
        while out and not out[-1].strip():
            out.pop()
        start = len(out)
        while start > 0 and out[start - 1].strip() and not out[start - 1].startswith("[saída tabular retida"):
            start -= 1
        block = out[start:]
        if footer is not None:
            rows, cols = int(footer.group(1)), int(footer.group(2))
            columns = ", ".join(_repr_header(block))
        else:
            if _dtype_listing_start(out) is not None:
                out.append(line)
                continue
            rows = int(series.group("length")) if series.group("length") else max(len(block), 0)
            cols = 1
            columns = series.group("name") or ""
        del out[start:]
        out.append(_table_marker(rows, cols, columns, ctx))
    return out


_MARKER_PREFIXES = ("[saída", "[dado", "[...", "[estat")


def filter_numeric_lists(text: str, ctx: FilterContext) -> str:
    """Retém listas (JSON/Python/ndarray) com mais de ``table_min_rows`` elementos numéricos."""
    if "[" not in text:
        return text
    spans: list[tuple[int, int]] = []
    stack: list[int] = []
    for pos, char in enumerate(text):
        if char == "[":
            stack.append(pos)
        elif char == "]" and stack:
            start = stack.pop()
            if not stack:
                spans.append((start, pos + 1))
    if not spans:
        return text
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        span = text[start:end]
        out.append(text[cursor:start])
        cursor = end
        if span.startswith(_MARKER_PREFIXES):
            out.append(span)
            continue
        words = [w for w in re.split(r"[\s,\[\]]+", span) if w]
        numeric = [w for w in words if _is_numeric_token(w)]
        if len(numeric) > ctx.table_min_rows and len(numeric) * 2 >= len(words):
            inner = re.findall(r"\[[^\[\]]*\]", span[1:-1]) if span.count("[") > 1 else []
            if inner:
                rows = len(inner)
                first_words = [w for w in re.split(r"[\s,\[\]]+", inner[0]) if w]
                cols = max(len(first_words), 1)
            else:
                rows, cols = len(numeric), 1
            out.append(_table_marker(rows, cols, "", ctx))
        else:
            out.append(span)
    out.append(text[cursor:])
    return "".join(out)


def filter_indexed_tables(lines: list[str], ctx: FilterContext) -> list[str]:
    """Retém cabeçalho + linhas com índice de um `repr` de DataFrame sem rodapé (qualquer tamanho)."""
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        header = _header_columns(lines[i])
        if len(header) >= 1 and not _is_keyvalue_line(lines[i]) and not lines[i].startswith("["):
            j = i + 1
            rows = 0
            while j < n:
                fields = _fields(lines[j])
                if len(fields) != len(header) + 1:
                    break
                tail = fields[1:]
                if sum(_is_numeric_token(t) for t in tail) * 2 < len(tail):
                    break
                rows += 1
                j += 1
            if rows >= 1:
                out.append(_table_marker(rows, len(header), ", ".join(header), ctx))
                i = j
                continue
        out.append(lines[i])
        i += 1
    return out


def filter_generic_tables(lines: list[str], ctx: FilterContext) -> list[str]:
    """Retém ``table_min_rows`` ou mais linhas consecutivas com o mesmo número (>= 2) de campos, metade numéricos."""

    def shape(line: str) -> int | None:
        if not line.strip() or _is_keyvalue_line(line) or line.startswith("[saída"):
            return None
        fields = _fields(line)
        if len(fields) < 2:
            return None
        if sum(_is_numeric_token(t) for t in fields) * 2 < len(fields):
            return None
        return len(fields)

    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        width = shape(lines[i])
        if width is None:
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < n and shape(lines[j]) == width:
            j += 1
        count = j - i
        if count >= ctx.table_min_rows:
            columns = ""
            if out and out[-1].strip():
                header = _header_columns(out[-1])
                if len(header) == width:
                    out.pop()
                    columns = ", ".join(header)
            out.append(_table_marker(count, width, columns, ctx))
        else:
            out.extend(lines[i:j])
        i = j
    return out


# --------------------------------------------------------------------------------------------------------------
# Estatísticas impressas (design §3.3)
# --------------------------------------------------------------------------------------------------------------

_EXTREME_TOKENS = frozenset(
    {"min", "max", "minimo", "maximo", "mínimo", "máximo", "minimum", "maximum", "median", "mediana", "q1", "q2",
     "minima", "maxima", "mínima", "máxima", "mín", "máx", "range", "amplitude",
     "q3", "quantile", "quantil", "percentil", "percentile"}
)
_AGGREGATE_TOKENS = frozenset(
    {"mean", "media", "média", "std", "stdev", "desvio", "var", "variance", "variancia", "variância", "sum", "soma",
     "avg", "average"}
)
_NAME_TOKEN_RE = re.compile(r"[^\W_]+(?:%)?", re.UNICODE)
_STAT_RE = re.compile(
    # O nome vai do início da linha (ou de um delimitador) até o separador, com espaços e parênteses (limitado a 64).
    r"(?:^|(?<=[\s,;|]))(?P<name>[^,;|:=\n]{1,64}?)(?P<sep>\s{0,8}[:=]\s{0,8})"
    r"(?P<val>[-+]?(?:\d+(?:[.,]\d+)?|\.\d+)(?:[eE][-+]?\d+)?%?)(?!\w)(?!\.\d)"
)
_N_RE = re.compile(
    r"(?<![\w.])(?:n|N|count|n_samples|num_samples|samples|amostras|n_obs)\s*[:=]?\s*(\d+)(?:\.0+)?(?![\w.])"
)
_PERCENTILE_NAME_RE = re.compile(r"^(?:p\d{1,3}|q[0-4]|\d{1,3}%)$", re.IGNORECASE)


def _stat_kind(name: str) -> str | None:
    # Tokens em qualquer posição do nome ("val_max", "Max value (mV)", "temperatura máxima"); extremo vence agregado.
    tokens = [t for t in _NAME_TOKEN_RE.findall(name.lower()) if t]
    if any(t in _EXTREME_TOKENS or _PERCENTILE_NAME_RE.match(t) for t in tokens):
        return "extreme"
    if any(t in _AGGREGATE_TOKENS for t in tokens):
        return "aggregate"
    return None


def filter_statistics(lines: list[str], ctx: FilterContext) -> list[str]:
    """Aplica extremos em faixa e a regra de k às estatísticas ``nome: valor`` reconhecidas, bloco a bloco."""
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if not lines[i].strip():
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < n and lines[j].strip():
            j += 1
        block = lines[i:j]
        sizes = [int(m.group(1)) for line in block for m in _N_RE.finditer(line)]
        n_min = min(sizes) if sizes else None
        for line in block:
            out.append(_filter_stat_line(line, n_min, ctx))
        i = j
    return out


def _filter_stat_line(line: str, n_min: int | None, ctx: FilterContext) -> str:
    def repl(match: re.Match[str]) -> str:
        kind = _stat_kind(match.group("name"))
        if kind is None:
            return match.group(0)
        prefix = f"{match.group('name')}{match.group('sep')}"
        if kind == "extreme":
            ranged = rounded_range(match.group("val"))
            ctx.note(IV_EXTREMO)
            return prefix + (ranged if ranged is not None else "<estatística retida: valor>")
        if n_min is None:
            ctx.note(IV_SEM_N)
            return match.group(0)
        if n_min < ctx.k:
            ctx.note(IV_ESTATISTICA_RETIDA)
            return prefix + "<estatística retida: n<k>"
        return match.group(0)

    return _STAT_RE.sub(repl, line)


# --------------------------------------------------------------------------------------------------------------
# Elisão (design §3.4)
# --------------------------------------------------------------------------------------------------------------

def elide_long_output(text: str, ctx: FilterContext) -> str:
    """Saídas acima de ``output_max_chars``: primeiras e últimas linhas e o marcador do trecho omitido."""
    limit = ctx.output_max_chars
    if len(text) <= limit:
        return text
    half = max(limit // 2, 1)
    lines = text.split("\n")
    head: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > half:
            break
        head.append(line)
        used += len(line) + 1
    tail: list[str] = []
    used = 0
    for line in reversed(lines[len(head) :]):
        if used + len(line) + 1 > half:
            break
        tail.append(line)
        used += len(line) + 1
    tail.reverse()
    if not head and not tail:  # uma única linha gigante: corta por caracteres
        omitted = len(text) - 2 * half
        marker = f"[... 1 linhas / {omitted} caracteres omitidos; {ctx.where} ...]"
        ctx.note(IV_ELISAO)
        return text[:half] + "\n" + marker + "\n" + text[-half:]
    omitted_lines = len(lines) - len(head) - len(tail)
    omitted_chars = len(text) - len("\n".join(head)) - len("\n".join(tail))
    marker = f"[... {omitted_lines} linhas / {max(omitted_chars, 0)} caracteres omitidos; {ctx.where} ...]"
    ctx.note(IV_ELISAO)
    return "\n".join(head + [marker] + tail)


# --------------------------------------------------------------------------------------------------------------
# Pipeline e artefatos
# --------------------------------------------------------------------------------------------------------------

# Limites aplicados ANTES de qualquer regex (contenção no Pi 5 e contra ReDoS por entrada adversarial).
MAX_LINE_CHARS = 2000
MAX_INPUT_CHARS = 400_000


def bound_input(text: str, ctx: FilterContext) -> str:
    """Limita o tamanho da entrada e de cada linha antes das regexes; o excedente fica só na saída integral."""
    if len(text) > MAX_INPUT_CHARS:
        half = MAX_INPUT_CHARS // 2
        omitted = len(text) - 2 * half
        ctx.note(IV_ELISAO)
        text = f"{text[:half]}\n[... {omitted} caracteres omitidos; {ctx.where} ...]\n{text[-half:]}"
    if any(len(line) > MAX_LINE_CHARS for line in text.split("\n")):
        lines = []
        for line in text.split("\n"):
            if len(line) > MAX_LINE_CHARS:
                ctx.note(IV_ELISAO)
                line = f"[... linha longa omitida: {len(line)} caracteres; {ctx.where} ...]"
            lines.append(line)
        text = "\n".join(lines)
    return text


def filter_execution_output(text: str, ctx: FilterContext) -> str:
    """Filtro de saída de execução: tracebacks, despejos tabulares e estatísticas, e elisão por tamanho."""
    if not text:
        return text
    text = bound_input(text, ctx)
    text = filter_tracebacks(text, ctx)
    lines = filter_describe(text.split("\n"), ctx)
    lines = filter_footer_tables(lines, ctx)
    text = filter_numeric_lists("\n".join(lines), ctx)
    lines = filter_indexed_tables(text.split("\n"), ctx)
    lines = filter_statistics(lines, ctx)
    lines = filter_generic_tables(lines, ctx)
    return elide_long_output("\n".join(lines), ctx)


_ARTIFACT_OK_RE = re.compile(r"^[\w\-.]+$")
_DECIMAL_IN_NAME_RE = re.compile(r"\d+[.,]\d+(?:[.,]\d+)*")


def sanitize_artifact_name(name: str, ctx: FilterContext | None = None) -> str:
    """Nome de artefato: mantido se casar ``^[\\w\\-.]+$`` sem número com separador decimal; senão o trecho numérico
    vira marcador (design §3.5)."""
    if _ARTIFACT_OK_RE.match(name) and not _DECIMAL_IN_NAME_RE.search(name):
        return name
    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        changed += 1
        return number_marker(match.group(0))

    cleaned = _DECIMAL_IN_NAME_RE.sub(repl, name)
    if ctx is not None:
        ctx.note(IV_NUMERO, changed)
    return cleaned


def known_identifier_set(names: Iterable[str]) -> frozenset[str]:
    """Conjunto de identificadores conhecidos (colunas, nomes de arquivos) normalizado."""
    return frozenset(str(n) for n in names if n)
