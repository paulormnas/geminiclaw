"""Renderização das referências numéricas (design §4): valor pt-BR, unidade e código de origem.

Os códigos são ``[R1]`` (execução), ``[C1]`` (cálculo) e ``[S1]`` (fonte citada)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from src.numeric_refs.resolver import ReferenceResolver, ResolvedValue
from src.numeric_refs.syntax import find_malformed, find_references

NARROW_NBSP = " "
UNVERIFIED_MARK = "[não verificado]"
LITERAL_MARK = "[literal no código]"
_SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
_CODE_PREFIX = {"res": "R", "calc": "C", "src": "S"}


def format_number(value: float, *, max_sig: int, decimals: int | None = None, integer: bool = False) -> str:
    """Número em pt-BR: vírgula decimal, espaço fino acima de 10 000 e notação científica fora de [1e-3, 1e6)."""
    if integer and decimals is None:
        return _group(str(int(value)))
    number = Decimal(repr(float(value)))
    if decimals is not None:
        quantum = Decimal(1).scaleb(-decimals)
        shown = number.quantize(quantum, rounding=ROUND_HALF_UP)
        return _group(format(shown, "f")).replace(".", ",")
    if number == 0:
        return "0"
    magnitude = abs(float(number))
    if magnitude < 1e-3 or magnitude >= 1e6:
        return _scientific(number, max_sig)
    exponent = number.adjusted()
    rounded = number.quantize(Decimal(1).scaleb(exponent - max_sig + 1), rounding=ROUND_HALF_UP)
    text = format(rounded, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return _group(text).replace(".", ",")


def _group(text: str) -> str:
    sign = "-" if text.startswith("-") else ""
    body = text.lstrip("-")
    integer, _, fraction = body.partition(".")
    if len(integer) > 4:
        groups: list[str] = []
        while integer:
            groups.insert(0, integer[-3:])
            integer = integer[:-3]
        integer = NARROW_NBSP.join(groups)
    return f"{sign}{integer}.{fraction}" if fraction else f"{sign}{integer}"


def _scientific(number: Decimal, max_sig: int) -> str:
    exponent = number.adjusted()
    mantissa = (number.scaleb(-exponent)).quantize(Decimal(1).scaleb(-(max_sig - 1)), rounding=ROUND_HALF_UP)
    text = format(mantissa, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text.replace('.', ',')} × 10{str(exponent).translate(_SUPERSCRIPT)}"


def display_value(rv: ResolvedValue) -> str:
    """Valor e unidade de um ``ResolvedValue`` ok, no formato do relatório (``0,4498 mm``, ``7,1 %``)."""
    from src import config

    sig = config.NUMREF_CALC_SIG_DIGITS if rv.origem == "calc" else config.NUMREF_DISPLAY_MAX_SIG_DIGITS
    text = format_number(float(rv.valor), max_sig=sig, decimals=rv.decimais, integer=rv.inteiro)
    return f"{text} {rv.unidade}" if rv.unidade else text


@dataclass
class RenderedCode:
    codigo: str
    tipo: str
    valor_exato: float | None
    unidade: str | None
    detalhe: dict[str, Any]
    ocorrencias: int = 1
    literal: bool = False


@dataclass
class RenderResult:
    texto: str
    spans: list[tuple[int, int]] = field(default_factory=list)
    codigos: list[RenderedCode] = field(default_factory=list)
    nao_resolvidos: list[dict[str, Any]] = field(default_factory=list)
    contagens: dict[str, int] = field(default_factory=lambda: {"res": 0, "calc": 0, "src": 0})


def render_text(text: str, resolver: ReferenceResolver) -> RenderResult:
    """Troca cada referência pelo valor renderizado; o que não resolve (ou é malformado) fica em código inline com
    ``[não verificado]`` e o motivo vai para ``nao_resolvidos``. Nada é apagado."""
    refs = find_references(text)
    items: list[tuple[int, int, Any, str | None]] = [(r.span[0], r.span[1], r, None) for r in refs]
    for issue in find_malformed(text):
        items.append((issue.posicao, issue.posicao + len(issue.trecho), None, issue.motivo))
    items.sort(key=lambda item: item[0])
    result = RenderResult(texto="")
    codes: dict[tuple, RenderedCode] = {}
    counters = {"R": 0, "C": 0, "S": 0}
    out: list[str] = []
    pos = 0
    length = 0

    def emit(chunk: str, protected: bool = False) -> None:
        nonlocal length
        if protected and chunk:
            result.spans.append((length, length + len(chunk)))
        out.append(chunk)
        length += len(chunk)

    for start, end, ref, malformed_reason in items:
        if start < pos:
            continue
        emit(text[pos:start])
        raw = text[start:end]
        if ref is None:
            emit(f"`{raw}` {UNVERIFIED_MARK}", protected=True)
            result.nao_resolvidos.append({"texto": raw, "motivo": "sintaxe_invalida", "detalhe": malformed_reason})
            pos = end
            continue
        resolved = resolver.resolve(ref)
        result.contagens[ref.kind] += 1
        if not resolved.ok:
            emit(f"`{raw}` {UNVERIFIED_MARK}", protected=True)
            result.nao_resolvidos.append(
                {"texto": raw, "motivo": resolved.motivo, "detalhe": resolved.mensagem or ""}
            )
            pos = end
            continue
        code = codes.get(ref.key)
        if code is None:
            prefix = _CODE_PREFIX[ref.kind]
            counters[prefix] += 1
            literal = (
                ref.kind == "res"
                and (resolved.detalhe.get("exec_id"), resolved.detalhe.get("metrica")) in resolver.literal_metrics
            )
            code = RenderedCode(
                f"{prefix}{counters[prefix]}", ref.kind, resolved.valor, resolved.unidade, resolved.detalhe,
                literal=literal,
            )
            codes[ref.key] = code
            result.codigos.append(code)
        else:
            code.ocorrencias += 1
        rendered = f"{display_value(resolved)} [{code.codigo}]" + (f" {LITERAL_MARK}" if code.literal else "")
        emit(rendered, protected=True)
        pos = end
    emit(text[pos:])
    result.texto = "".join(out)
    return result
