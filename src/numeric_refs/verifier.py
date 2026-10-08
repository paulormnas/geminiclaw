"""Verificador de números do texto final (design §5): marca com ``[não verificado]`` os números sem origem.

O texto do número **não** é apagado nem alterado. As exclusões são a lista fechada X1–X9 do design (ampliar exige
alterar a spec): spans renderizados, seções do orquestrador, código, numeração, identificadores, datas, anos em
contexto, contagens iguais às do orquestrador e artigos/ordinais.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from src.numeric_refs.numbers import NumberSpan, find_numbers

UNVERIFIED_MARK = "[não verificado]"

# X2: seções do orquestrador registradas (delimitadas por <!-- nome:begin --> ... <!-- nome:end -->).
DEFAULT_SECTION_NAMES = (
    "numeric-provenance", "claims", "operation-metrics", "allocation-profile", "provenance-chain",
    "execution-metadata", "report-results", "researcher-decisions", "input-data",
)

_MONTHS = (
    "janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
)
_YEAR_CONTEXT_WORDS = {"em", "de", "desde", "até", "ate", "ano", "anos", "do", "no"}
_MASK_PATTERNS = [
    re.compile(r"```.*?```", re.DOTALL),  # X3 bloco de código
    re.compile(r"`[^`\n]*`"),  # X3 código inline
    re.compile(r"<!--.*?-->", re.DOTALL),  # X3 comentários HTML
    re.compile(r"https?://[^\s)>\]]+"),  # X3 URLs
    re.compile(r"\]\([^)\s]*\)"),  # X3 alvos de links
    re.compile(r"\b10\.\d{4,9}/[^\s)>\]]+"),  # X3 DOIs
    re.compile(r"(?m)^(#{1,6}[ \t]+)(\d+(?:\.\d+)*[.)]?)(?=[ \t])"),  # X4 numeração de títulos (grupo 2)
    re.compile(r"(?m)^([ \t]*)(\d+[.)])(?=[ \t])"),  # X4 marcadores de lista (grupo 2)
    re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]"),  # X4 marcadores de citação
    re.compile(r"\[(?:R|C|S|A)\d+\]"),  # X4 códigos de origem
    re.compile(r"\b(?:[Pp]ython|[Vv]ers[ãa]o|[Vv]ersion|[Vv])\s?\d+(?:\.\d+)*"),  # X5 versões
    re.compile(r"\b\d+\.\d+\.\d+(?:\.\d+)*\b"),  # X5 versões pontuadas
    re.compile(r"\b[0-9a-f]{8,}\b"),  # X5 hashes
    re.compile(r"[\w\-]+\.(?:csv|tsv|json|jsonl|xlsx|xls|pdf|docx|pptx|txt|md|png|jpg|jpeg|py|yaml|yml)\b"),  # X5
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"),  # X6 ISO
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),  # X6 dd/mm/aaaa
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),  # X6 hh:mm
    re.compile(rf"\b\d{{1,2}}\s+de\s+(?:{_MONTHS})(?:\s+de\s+\d{{4}})?\b", re.IGNORECASE),  # X6 data por extenso
    re.compile(rf"\b(?:{_MONTHS})\s+(?:de\s+)?\d{{4}}\b", re.IGNORECASE),  # X6 mês e ano
]
_GROUPED = {6, 7}  # índices cujo trecho a mascarar é o grupo 2

_COUNT_NOUNS: dict[str, str] = {}
for _canon, _forms in {
    "subtarefa": ("subtarefa", "subtarefas"),
    "hipotese": ("hipótese", "hipóteses", "hipotese", "hipoteses"),
    "experimento": ("experimento", "experimentos"),
    "execucao": ("execução", "execuções", "execucao", "execucoes"),
    "tentativa": ("tentativa", "tentativas"),
    "sessao": ("sessão", "sessões", "sessao", "sessoes"),
    "afirmacao": ("afirmação", "afirmações", "afirmacao", "afirmacoes"),
    "insumo": ("insumo", "insumos"),
    "artigo": ("artigo", "artigos"),
    "abordagem": ("abordagem", "abordagens"),
    "ciclo": ("ciclo", "ciclos"),
}.items():
    for _form in _forms:
        _COUNT_NOUNS[_form] = _canon
_MASK_CHAR = "\x00"
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]+")
_HEADING_RE = re.compile(r"(?m)^#{1,6}[ \t]+(.+?)[ \t]*$")


@dataclass(frozen=True)
class UnverifiedNumber:
    texto: str
    local: str
    motivo: str = "sem_origem"
    posicao: int = 0


@dataclass
class VerifyOutcome:
    texto: str
    nao_verificados: list[UnverifiedNumber] = field(default_factory=list)
    total_numeros: int = 0


def _section_spans(text: str, names: Iterable[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for name in names:
        pattern = re.compile(
            rf"<!--\s*{re.escape(name)}:begin\s*-->.*?<!--\s*{re.escape(name)}:end\s*-->", re.DOTALL
        )
        spans.extend(m.span() for m in pattern.finditer(text))
        # seção aberta e não fechada: protege até o fim (falha para o lado de não marcar o conteúdo do orquestrador)
        opened = re.compile(rf"<!--\s*{re.escape(name)}:begin\s*-->").finditer(text)
        for m in opened:
            if not any(lo <= m.start() < hi for lo, hi in spans):
                spans.append((m.start(), len(text)))
    return spans


def _masked(text: str, protected: Iterable[tuple[int, int]], section_names: Iterable[str]) -> str:
    chars = list(text)

    def cover(lo: int, hi: int) -> None:
        for i in range(max(lo, 0), min(hi, len(chars))):
            if chars[i] != "\n":
                chars[i] = _MASK_CHAR

    for lo, hi in protected:
        cover(lo, hi)
    for lo, hi in _section_spans(text, section_names):
        cover(lo, hi)
    for index, pattern in enumerate(_MASK_PATTERNS):
        for match in pattern.finditer(text):
            if index in _GROUPED:
                cover(*match.span(2))
            else:
                cover(*match.span())
    return "".join(chars)


def _prev_word(masked: str, pos: int) -> str:
    before = masked[:pos].rstrip("  \t")
    words = list(_WORD_RE.finditer(before[-40:]))
    if not words or words[-1].end() != len(before[-40:]):
        return ""
    return unicodedata.normalize("NFC", words[-1].group(0).lower())


def _is_year_in_context(masked: str, span: NumberSpan, year_min: int, year_max: int) -> bool:
    if not re.fullmatch(r"\d{4}", span.text.strip()):
        return False
    year = int(span.text.strip())
    if not year_min <= year <= year_max:
        return False
    prev = _prev_word(masked, span.start)
    if prev in _YEAR_CONTEXT_WORDS or re.fullmatch(_MONTHS, prev or "x", re.IGNORECASE):
        return True
    before = masked[max(0, span.start - 80) : span.start]
    return bool(re.search(r"\([^()]*,\s*$", before))


def _count_category(masked: str, span: NumberSpan) -> str | None:
    tail = masked[span.end : span.end + 60]
    words = [unicodedata.normalize("NFC", m.group(0).lower()) for m in _WORD_RE.finditer(tail)][:3]
    # "artigo de referência", "ciclo de planejamento": o substantivo vem em até duas palavras depois do número
    for word in words[:2]:
        if word in _COUNT_NOUNS:
            return _COUNT_NOUNS[word]
    return None


def _heading_at(text: str, pos: int) -> str:
    heading = ""
    for match in _HEADING_RE.finditer(text):
        if match.start() > pos:
            break
        heading = match.group(1).strip()
    return f"relatorio:{heading}" if heading else "relatorio"


def verify_numbers(
    text: str,
    *,
    protected_spans: Iterable[tuple[int, int]] = (),
    section_names: Iterable[str] = DEFAULT_SECTION_NAMES,
    counts: Mapping[str, int] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
) -> VerifyOutcome:
    """Marca os números sem origem de ``text`` com ``[não verificado]``.

    Args:
        text: Texto já renderizado.
        protected_spans: Trechos produzidos pelo renderizador (X1), em posições de ``text``.
        section_names: Seções do orquestrador registradas (X2).
        counts: Contagens da sessão por categoria canônica (``subtarefa``, ``hipotese``, ...) para a exclusão X8.
        year_min, year_max: Intervalo de anos (padrão: ``NUMREF_YEAR_MIN``/``NUMREF_YEAR_MAX``).
    """
    from src import config

    lo_year = year_min if year_min is not None else config.NUMREF_YEAR_MIN
    hi_year = year_max if year_max is not None else config.NUMREF_YEAR_MAX
    masked = _masked(text, protected_spans, section_names)
    numbers = find_numbers(masked)
    outcome = VerifyOutcome(texto=text, total_numeros=len(numbers))
    inserts: list[int] = []
    for span in numbers:
        if _MASK_CHAR in masked[span.start : span.end]:
            continue
        if _is_year_in_context(masked, span, lo_year, hi_year):
            continue
        category = _count_category(masked, span)
        if category is not None and counts is not None and span.value is not None:
            if span.kind in ("algarismo", "extenso") and counts.get(category) == int(span.value) == span.value:
                continue
        if text[span.end : span.end + 1 + len(UNVERIFIED_MARK)].lstrip().startswith(UNVERIFIED_MARK):
            continue  # já marcado (ex.: referência não resolvida)
        inserts.append(span.end)
        outcome.nao_verificados.append(
            UnverifiedNumber(texto=text[span.start : span.end], local=_heading_at(text, span.start), posicao=span.start)
        )
    out = text
    for position in sorted(inserts, reverse=True):
        out = f"{out[:position]} {UNVERIFIED_MARK}{out[position:]}"
    outcome.texto = out
    return outcome
