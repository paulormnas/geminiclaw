"""Conclusões e frases (v18.5-claim-verification, design §1 e §3): extração determinística, sem LLM.

Conclusões do relatório: cada parágrafo, item de lista ou célula de texto livre das seções de ``CLAIM_VERIFY_SECTIONS``.
As seções do orquestrador (``<!-- nome:begin -->``…``end``) e blocos de código nunca são conclusões.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from src.claims.model import ORIGEM_DESCOBERTA, ORIGEM_RELATORIO, Conclusao

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_NUMBERING_RE = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?|[IVXLC]+[.)])\s+")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_BEGIN_RE = re.compile(r"^\s*<!--\s*([\w.\-]+):begin\s*-->\s*$")
_END_RE = re.compile(r"^\s*<!--\s*([\w.\-]+):end\s*-->\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_CODE_MARK_RE = re.compile(r"\[(?:R|C|S)\d+\]|\[não verificado\]|\[literal no código\]|\[A\d+ · [^\]]+\]")
_ANCHOR_RE = re.compile(r'<a id="[^"]*"></a>')
_SOURCE_REF_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)

_ABBREVIATIONS = (
    "fig", "figs", "tab", "eq", "eqs", "cap", "sec", "pág", "pag", "p", "pp", "vol", "ed", "n", "no", "nº", "sr", "sra",
    "dr", "dra", "prof", "profa", "ex", "cf", "vs", "al", "aprox", "ca", "obs", "i.e", "e.g", "ref", "refs",
)
_BOUNDARY_RE = re.compile(r"([.!?;…])(\s+)(?=[\"“(\[]?[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9{])")
_MIN_WORDS_TABLE_CELL = 4


def normalize_heading(text: str) -> str:
    """Título sem numeração, acentos, marcação e caixa, para casar com ``CLAIM_VERIFY_SECTIONS``."""
    text = re.sub(r"[*_`]", "", text).strip()
    text = _NUMBERING_RE.sub("", text)
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", folded).strip().lower()


@dataclass(frozen=True)
class Sentence:
    """Frase de uma conclusão, com o trecho (``span``) relativo ao texto da conclusão."""

    indice: int
    texto: str
    span: tuple[int, int]


def split_sentences(text: str) -> list[Sentence]:
    """Segmentação em frases pt-BR, determinística: quebra em ``. ! ? ;`` seguidos de espaço e maiúscula ou número.

    Não quebra em abreviações comuns (``Fig.``, ``etc.``), em decimais (``0,81``), nem dentro de códigos de origem.
    """
    sentences: list[Sentence] = []
    start = 0
    cuts: list[int] = []
    for match in _BOUNDARY_RE.finditer(text):
        if match.group(1) == "." and _ends_with_abbreviation(text[: match.start()]):
            continue
        cuts.append(match.end(1))
    cuts.append(len(text))
    for cut in cuts:
        chunk = text[start:cut]
        stripped = chunk.strip()
        if stripped:
            lead = len(chunk) - len(chunk.lstrip())
            span = (start + lead, start + lead + len(stripped))
            sentences.append(Sentence(len(sentences), stripped, span))
        start = cut
    return sentences


def _ends_with_abbreviation(prefix: str) -> bool:
    match = re.search(r"([\wºª.]+)$", prefix)
    if not match:
        return False
    word = match.group(1).lower().rstrip(".")
    return word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha())


def has_free_text(text: str) -> bool:
    """True se ``text`` tem palavras além de marcas de origem, âncoras, números e símbolos."""
    cleaned = _ANCHOR_RE.sub("", _CODE_MARK_RE.sub("", _SOURCE_REF_RE.sub("", text)))
    return bool(re.search(r"[^\W\d_]{2,}", cleaned))


def extract_report_conclusions(text: str, sections: Iterable[str]) -> list[Conclusao]:
    """Conclusões do relatório renderizado, nas seções indicadas.

    ``conclusao_id = rel:<seção normalizada>:<n>``, com ``n`` crescente dentro da seção. ``Conclusao.inicio`` é a
    posição do texto no relatório (para inserir as marcas inline).
    """
    wanted = {normalize_heading(s) for s in sections if s.strip()}
    conclusions: list[Conclusao] = []
    counters: dict[str, int] = {}
    section: str | None = None
    skip_block: str | None = None
    in_fence = False
    paragraph: list[tuple[int, str]] = []  # (posição da linha, linha)

    def flush() -> None:
        nonlocal paragraph
        if paragraph and section is not None:
            first = paragraph[0][0]
            body = "\n".join(line for _, line in paragraph)
            lead = len(body) - len(body.lstrip())
            _emit(section, first + lead, body.strip())
        paragraph = []

    def _emit(sec: str, start: int, body: str) -> None:
        if not body or not has_free_text(body):
            return
        counters[sec] = counters.get(sec, 0) + 1
        conclusions.append(
            Conclusao(
                conclusao_id=f"rel:{sec}:{counters[sec]}",
                origem=ORIGEM_RELATORIO,
                texto=body,
                autor="summarizer",
                secao=sec,
                inicio=start,
            )
        )

    pos = 0
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        line_start = pos
        pos += len(raw)
        if skip_block is not None:
            end = _END_RE.match(line)
            if end and end.group(1) == skip_block:
                skip_block = None
            continue
        begin = _BEGIN_RE.match(line)
        if begin:
            flush()
            skip_block = begin.group(1)
            continue
        if _FENCE_RE.match(line):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            name = normalize_heading(heading.group(2))
            section = name if name in wanted else None
            continue
        if section is None:
            continue
        if not line.strip():
            flush()
            continue
        if _TABLE_SEP_RE.match(line):
            continue
        if line.lstrip().startswith("|"):
            flush()
            _table_row(line, line_start, section, _emit)
            continue
        item = _LIST_RE.match(line)
        if item:
            flush()
            paragraph.append((line_start + item.end(), line[item.end():]))
            continue
        paragraph.append((line_start, line))
    flush()
    return conclusions


def _table_row(line: str, line_start: int, section: str, emit) -> None:
    cursor = 0
    cells = line.split("|")
    for cell in cells:
        stripped = cell.strip()
        offset = line_start + cursor + (len(cell) - len(cell.lstrip()))
        cursor += len(cell) + 1
        if len(stripped.split()) >= _MIN_WORDS_TABLE_CELL:
            emit(section, offset, stripped)


def conclusion_from_discovery(node_id: str, enunciado: str, condicoes: str | None) -> Conclusao:
    """Conclusão de uma ``Descoberta`` (enunciado + condições), com o Curator como autor."""
    body = (enunciado or "").strip()
    if condicoes and condicoes.strip():
        glue = "" if body.endswith((".", "!", "?", ";")) else "."
        body = f"{body}{glue} Condições: {condicoes.strip()}"
    return Conclusao(
        conclusao_id=f"desc:{node_id}", origem=ORIGEM_DESCOBERTA, texto=body, autor="curator"
    )
