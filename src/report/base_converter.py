"""Interface base e factory dos conversores de formato do relatório científico
(Roadmap V15.4 / Spec G8).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, NamedTuple

# v18.5-numeric-references (design §9): marcas do relatório reconhecidas por todos os conversores. As marcas continuam
# legíveis no Markdown puro; cada formato as destaca à sua maneira. Outras mudanças podem acrescentar regras.
ORIGIN_CODE_RE = re.compile(r"\[(R|C|S)(\d+)\]")
UNVERIFIED_RE = re.compile(r"\[não verificado\]")
LITERAL_RE = re.compile(r"\[literal no código\]")
MARKS_RE = re.compile(f"{ORIGIN_CODE_RE.pattern}|{UNVERIFIED_RE.pattern}|{LITERAL_RE.pattern}")
ORIGIN_ANCHOR_RE = re.compile(r'<a id="origem-([RCS]\d+)"></a>')
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class Mark(NamedTuple):
    """Trecho de texto: puro (``text``), código de origem, ``[não verificado]`` ou ``[literal no código]``."""

    kind: Literal["text", "origin", "unverified", "literal"]
    value: str  # texto puro, ou o código (``R1``) para ``origin``


def strip_markup_helpers(markdown: str) -> str:
    """Remove os comentários HTML dos delimitadores de seção; os âncoras ``<a id="origem-..">`` ficam."""
    return HTML_COMMENT_RE.sub("", markdown)


def split_marks(text: str) -> list[Mark]:
    """Divide ``text`` em trechos puros e marcas (na ordem)."""
    parts: list[Mark] = []
    pos = 0
    for match in MARKS_RE.finditer(text):
        if match.start() > pos:
            parts.append(Mark("text", text[pos : match.start()]))
        if match.group(1):
            parts.append(Mark("origin", f"{match.group(1)}{match.group(2)}"))
        elif match.group(0) == "[não verificado]":
            parts.append(Mark("unverified", "não verificado"))
        else:
            parts.append(Mark("literal", "literal no código"))
        pos = match.end()
    if pos < len(text):
        parts.append(Mark("text", text[pos:]))
    return parts


class ReportConverter(ABC):
    """Interface para conversores de ``relatorio_final.md`` para outros formatos."""

    @abstractmethod
    def convert(self, markdown_path: Path, output_path: Path) -> None:
        """Converte o Markdown de entrada e salva o resultado em ``output_path``.

        Args:
            markdown_path: Caminho do ``relatorio_final.md`` de origem.
            output_path: Caminho onde salvar o arquivo convertido.
        """
        raise NotImplementedError


class ReportConverterFactory:
    """Fábrica de conversores por formato (``latex`` | ``html`` | ``docx``)."""

    @staticmethod
    def create(format: str) -> ReportConverter:
        """Cria o conversor apropriado para o formato solicitado.

        Args:
            format: Um de ``"latex"``, ``"html"`` ou ``"docx"``.

        Returns:
            Instância do conversor correspondente.

        Raises:
            ValueError: Se o formato não for suportado.
        """
        normalized = format.lower().strip()
        if normalized == "latex":
            from src.report.latex_converter import LaTeXConverter
            return LaTeXConverter()
        if normalized == "html":
            from src.report.html_converter import HTMLConverter
            return HTMLConverter()
        if normalized == "docx":
            from src.report.docx_converter import DOCXConverter
            return DOCXConverter()
        raise ValueError(
            f"Formato não suportado: '{format}'. Formatos disponíveis: latex, html, docx."
        )
