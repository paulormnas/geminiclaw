"""Reconhecedor de números em português do Brasil (design §5.1): algarismos, por extenso e multiplicadores.

Usado pelo verificador de números do relatório e pela resolução de ``{{src}}`` (o trecho precisa conter exatamente um
número). Trabalha sobre texto em que as zonas protegidas já foram mascaradas (mesmo comprimento), por isso devolve
posições do texto original.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

NumberKind = Literal["algarismo", "extenso", "multiplicador", "fracao", "faixa"]

_SIGN = r"[-−+±]"
_DIGITS = r"(?:\d{1,3}(?:[.  ]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
_SUPER = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_SCI = (
    rf"(?:{_DIGITS}\s*[×x]\s*10(?:\^[-−+]?\d+|[⁻⁺]?[{_SUPER}]+)"
    rf"|{_DIGITS}[eE][-+]?\d+"
    rf"|10(?:\^[-−+]?\d+|[⁻⁺]?[{_SUPER}]+))"
)
_PERCENT = r"(?:\s?%|\s+por\s+cento|\s+pontos?\s+percentuais?|\s?p\.p\.)"
_MULT = r"(?:\s?[x×](?![A-Za-z0-9_])|\s+vezes(?:\s+(?:mais|menos))?)"

_RANGE_RE = re.compile(rf"(?<![\w.,]){_SIGN}?{_DIGITS}\s*[–—-]\s*{_DIGITS}(?:{_PERCENT})?(?![\w])")
_NUMBER_RE = re.compile(
    rf"(?<![\w.,]){_SIGN}?(?:{_SCI}|{_DIGITS})(?:{_PERCENT}|{_MULT})?(?![\w]|[.,]\d)"
)

_UNIT_WORDS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
    "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14,
    "quinze": 15, "dezesseis": 16, "dezasseis": 16, "dezessete": 17, "dezassete": 17, "dezoito": 18, "dezenove": 19,
    "dezanove": 19,
}
_TENS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80,
    "noventa": 90,
}
_HUNDREDS = {
    "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200, "trezentos": 300, "trezentas": 300,
    "quatrocentos": 400, "quatrocentas": 400, "quinhentos": 500, "quinhentas": 500, "seiscentos": 600,
    "seiscentas": 600, "setecentos": 700, "setecentas": 700, "oitocentos": 800, "oitocentas": 800,
    "novecentos": 900, "novecentas": 900,
}
_SCALES = {
    "mil": 10**3, "milhão": 10**6, "milhao": 10**6, "milhões": 10**6, "milhoes": 10**6,
    "bilhão": 10**9, "bilhao": 10**9, "bilhões": 10**9, "bilhoes": 10**9,
}
_FRACTION_WORDS = {
    "terço": 3, "terco": 3, "terços": 3, "tercos": 3, "quarto": 4, "quartos": 4, "quinto": 5, "quintos": 5,
    "sexto": 6, "sextos": 6, "sétimo": 7, "setimo": 7, "sétimos": 7, "setimos": 7, "oitavo": 8, "oitavos": 8,
    "nono": 9, "nonos": 9, "décimo": 10, "decimo": 10, "décimos": 10, "decimos": 10,
}
_STANDALONE_MULTIPLIERS = {"dobro": 2, "triplo": 3, "quádruplo": 4, "quadruplo": 4, "quíntuplo": 5, "quintuplo": 5}
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]+")


@dataclass(frozen=True)
class NumberSpan:
    start: int
    end: int
    text: str
    kind: NumberKind
    value: float | None = None


def _norm(word: str) -> str:
    return unicodedata.normalize("NFC", word.lower())


def parse_digits(token: str) -> float | None:
    """Valor de um literal em algarismos pt-BR (``1.234,5``; ``0,95``; ``0.95``; ``1,2e-3``); ``None`` se inválido."""
    text = token.strip().replace("−", "-").replace(" ", "").replace(" ", "")
    sign = 1.0
    if text and text[0] in "+-±":
        sign = -1.0 if text[0] == "-" else 1.0
        text = text[1:]
    text = re.sub(r"\s?(%|por cento|pontos? percentuais?|p\.p\.)$", "", text.strip())
    text = re.sub(r"\s?(vezes(?:\s+(?:mais|menos))?|[x×])$", "", text.strip())
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", text):
        text = text.replace(".", "")
    text = text.replace(",", ".")
    try:
        return sign * float(text)
    except ValueError:
        return None


def _digits_spans(text: str) -> list[NumberSpan]:
    spans: list[NumberSpan] = []
    taken: list[tuple[int, int]] = []
    for match in _RANGE_RE.finditer(text):
        spans.append(NumberSpan(match.start(), match.end(), match.group(0), "faixa", None))
        taken.append(match.span())
    for match in _NUMBER_RE.finditer(text):
        if any(lo <= match.start() < hi for lo, hi in taken):
            continue
        raw = match.group(0)
        kind: NumberKind = "multiplicador" if re.search(_MULT + "$", raw) else "algarismo"
        spans.append(NumberSpan(match.start(), match.end(), raw, kind, parse_digits(raw)))
    return spans


def _word_tokens(text: str) -> list[tuple[str, int, int]]:
    return [(_norm(m.group(0)), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


def _number_word_value(word: str) -> tuple[str, int] | None:
    if word in _UNIT_WORDS:
        return "unit", _UNIT_WORDS[word]
    if word in _TENS:
        return "tens", _TENS[word]
    if word in _HUNDREDS:
        return "hundred", _HUNDREDS[word]
    if word in _SCALES:
        return "scale", _SCALES[word]
    return None


def _gap_ok(text: str, a_end: int, b_start: int) -> bool:
    """Só espaço entre duas palavras consecutivas (sem pontuação)."""
    return text[a_end:b_start].strip() == ""


def _parse_word_number(tokens: list[tuple[str, int, int]], i: int, text: str) -> tuple[int, int, int] | None:
    """Número por extenso a partir do token ``i``: ``(valor, índice_final_exclusivo, fim_do_texto)`` ou ``None``."""
    total = 0
    current = 0
    j = i
    consumed_any = False
    last_end = tokens[i][2]
    while j < len(tokens):
        word, start, end = tokens[j]
        if consumed_any and not _gap_ok(text, last_end, start):
            break
        if word == "e" and consumed_any and j + 1 < len(tokens) and _number_word_value(tokens[j + 1][0]) is not None:
            if not _gap_ok(text, end, tokens[j + 1][1]):
                break
            j += 1
            last_end = end
            continue
        info = _number_word_value(word)
        if info is None:
            break
        kind, value = info
        if kind == "scale":
            if value == 1000:
                current = current or 1
                total += current * 1000
            else:
                current = current or 1
                total += current * value
            current = 0
        else:
            current += value
        consumed_any = True
        last_end = end
        j += 1
    if not consumed_any:
        return None
    return total + current, j, last_end


def _is_of_magnitude(tokens: list[tuple[str, int, int]], i: int) -> bool:
    """``tokens[i]`` é "ordem(ns)" seguida de "de grandeza"."""
    return i + 2 < len(tokens) and tokens[i + 1][0] == "de" and tokens[i + 2][0] == "grandeza"


def _extenso_spans(text: str) -> list[NumberSpan]:
    tokens = _word_tokens(text)
    spans: list[NumberSpan] = []
    i = 0
    while i < len(tokens):
        word, start, end = tokens[i]
        if word == "metade":
            spans.append(NumberSpan(start, end, text[start:end], "fracao", 0.5))
            i += 1
            continue
        if word in _STANDALONE_MULTIPLIERS and i > 0 and tokens[i - 1][0] in {"o", "do", "ao", "um", "no", "pelo"}:
            spans.append(NumberSpan(start, end, text[start:end], "multiplicador", float(_STANDALONE_MULTIPLIERS[word])))
            i += 1
            continue
        if word in ("ordem", "ordens") and _is_of_magnitude(tokens, i):
            # "N ordens de grandeza": o número por extenso anterior (se houver) já foi capturado; aqui só "uma ordem".
            if i > 0 and tokens[i - 1][0] in ("uma", "um"):
                begin = tokens[i - 1][1]
                spans.append(NumberSpan(begin, tokens[i + 2][2], text[begin : tokens[i + 2][2]], "multiplicador", 10.0))
                i += 3
                continue
        parsed = _parse_word_number(tokens, i, text)
        if parsed is None:
            i += 1
            continue
        value, j, last_end = parsed
        begin = start
        kind: NumberKind = "extenso"
        number_value: float | None = float(value)
        only_article = j == i + 1 and word in ("um", "uma")
        # decimais por extenso: "dois vírgula cinco"
        if j + 1 < len(tokens) and tokens[j][0] == "vírgula" and _gap_ok(text, last_end, tokens[j][1]):
            frac = _parse_word_number(tokens, j + 1, text)
            if frac is not None:
                _fv, k, last_end = frac
                digits = "".join(str(_UNIT_WORDS.get(tokens[x][0], "")) for x in range(j + 1, k))
                number_value = float(f"{value}.{digits}") if digits.isdigit() else None
                j = k
                only_article = False
        nxt = tokens[j][0] if j < len(tokens) and _gap_ok(text, last_end, tokens[j][1]) else None
        end_pos = last_end
        if nxt in _FRACTION_WORDS:
            kind, end_pos = "fracao", tokens[j][2]
            j += 1
            only_article = False
        elif nxt in ("vez", "vezes"):
            kind, end_pos = "multiplicador", tokens[j][2]
            j += 1
            if j < len(tokens) and tokens[j][0] in ("mais", "menos") and _gap_ok(text, end_pos, tokens[j][1]):
                end_pos = tokens[j][2]
                j += 1
            only_article = False
        elif nxt in ("ordem", "ordens") and _is_of_magnitude(tokens, j):
            kind, end_pos = "multiplicador", tokens[j + 2][2]
            j += 3
            only_article = False
        if only_article:
            i = j
            continue  # "um"/"uma" como artigo (X9)
        spans.append(NumberSpan(begin, end_pos, text[begin:end_pos], kind, number_value))
        i = max(j, i + 1)
    return spans


def find_numbers(text: str) -> list[NumberSpan]:
    """Todos os números do texto (algarismos, por extenso, multiplicadores e frações), em ordem, sem sobreposição."""
    spans = sorted(_digits_spans(text) + _extenso_spans(text), key=lambda s: (s.start, -(s.end - s.start)))
    result: list[NumberSpan] = []
    for span in spans:
        if result and span.start < result[-1].end:
            continue
        result.append(span)
    return result
