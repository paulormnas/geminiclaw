"""Conversor Markdown -> LaTeX do relatório científico (Roadmap V15.4 / Spec G8).

Implementação leve e sem dependências externas (sem exigir o binário `pandoc`,
que não está garantido no ambiente do Raspberry Pi 5): um transformador linha a
linha suficiente para a estrutura previsível do `relatorio_final.md` (títulos,
parágrafos, listas, tabelas e blocos de código).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.report.base_converter import MARKS_RE, ORIGIN_ANCHOR_RE, ReportConverter, strip_markup_helpers

_LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$")

_SECTION_COMMANDS = {1: "section", 2: "subsection", 3: "subsubsection", 4: "paragraph"}


def _escape_latex(text: str) -> str:
    """Escapa caracteres especiais do LaTeX em texto puro (fora de código/tabelas)."""
    result = []
    for char in text:
        result.append(_LATEX_SPECIAL_CHARS.get(char, char))
    return "".join(result)


def _convert_emphasis(text: str) -> str:
    """Converte **negrito**, *itálico* e `código` para LaTeX, escapando o restante."""
    tokens: list[str] = []
    pos = 0
    pattern = re.compile(
        r"\*\*(.+?)\*\*|`([^`]+)`|\*(.+?)\*|" + ORIGIN_ANCHOR_RE.pattern + "|" + MARKS_RE.pattern
    )
    for match in pattern.finditer(text):
        tokens.append(_escape_latex(text[pos:match.start()]))
        if match.group(1) is not None:
            tokens.append(r"\textbf{" + _escape_latex(match.group(1)) + "}")
        elif match.group(2) is not None:
            tokens.append(r"\texttt{" + _escape_latex(match.group(2)) + "}")
        elif match.group(3) is not None:
            tokens.append(r"\textit{" + _escape_latex(match.group(3)) + "}")
        elif match.group(4) is not None:
            tokens.append(r"\hypertarget{origem-" + match.group(4) + "}{}")
        elif match.group(5) is not None:
            code = f"{match.group(5)}{match.group(6)}"
            tokens.append(r"\textsuperscript{\hyperlink{origem-" + code + "}{" + code + "}}")
        elif match.group(0) == "[não verificado]":
            tokens.append(r"\colorbox{yellow}{\textbf{não verificado}}")
        else:
            tokens.append(r"\colorbox{yellow}{\textbf{literal no código}}")
        pos = match.end()
    tokens.append(_escape_latex(text[pos:]))
    return "".join(tokens)


def _convert_table(lines: list[str]) -> str:
    """Converte um bloco de tabela Markdown (incluindo a linha separadora) para
    ``tabular`` com ``booktabs``.
    """
    rows = [
        [cell.strip() for cell in row.strip().strip("|").split("|")]
        for row in lines
        if not _TABLE_SEPARATOR_RE.match(row)
    ]
    if not rows:
        return ""
    num_cols = len(rows[0])
    col_spec = "l" * num_cols
    out = [r"\begin{table}[h]", r"\centering", r"\begin{tabular}{" + col_spec + "}", r"\toprule"]
    header, *body = rows
    out.append(" & ".join(_convert_emphasis(c) for c in header) + r" \\")
    out.append(r"\midrule")
    for row in body:
        cells = row + [""] * (num_cols - len(row))
        out.append(" & ".join(_convert_emphasis(c) for c in cells[:num_cols]) + r" \\")
    out.append(r"\bottomrule")
    out.append(r"\end{tabular}")
    out.append(r"\end{table}")
    return "\n".join(out)


def markdown_to_latex_body(markdown_text: str) -> str:
    """Converte o corpo de um documento Markdown para LaTeX (sem preâmbulo)."""
    lines = strip_markup_helpers(markdown_text).splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Bloco de código cercado por ```
        if line.strip().startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # pula a cerca de fechamento
            out.append(r"\begin{lstlisting}")
            out.extend(code_lines)
            out.append(r"\end{lstlisting}")
            continue

        # Tabela Markdown: linha com '|' seguida por linha separadora '---'
        if _TABLE_ROW_RE.match(line) and i + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(lines[i + 1]):
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
                table_lines.append(lines[i])
                i += 1
            out.append(_convert_table(table_lines))
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            command = _SECTION_COMMANDS.get(level, "paragraph")
            out.append(f"\\{command}{{{_convert_emphasis(heading_match.group(2))}}}")
            i += 1
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            items = []
            while i < len(lines) and _BULLET_RE.match(lines[i]):
                items.append(_BULLET_RE.match(lines[i]).group(1))
                i += 1
            out.append(r"\begin{itemize}")
            out.extend(r"\item " + _convert_emphasis(item) for item in items)
            out.append(r"\end{itemize}")
            continue

        numbered_match = _NUMBERED_RE.match(line)
        if numbered_match:
            items = []
            while i < len(lines) and _NUMBERED_RE.match(lines[i]):
                items.append(_NUMBERED_RE.match(lines[i]).group(1))
                i += 1
            out.append(r"\begin{enumerate}")
            out.extend(r"\item " + _convert_emphasis(item) for item in items)
            out.append(r"\end{enumerate}")
            continue

        if not line.strip():
            out.append("")
            i += 1
            continue

        out.append(_convert_emphasis(line))
        i += 1

    return "\n".join(out)


_LATEX_PREAMBLE = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{booktabs}
\usepackage{listings}
\usepackage{xcolor}
\usepackage{hyperref}
\title{%s}
\date{}
\begin{document}
\maketitle
"""


class LaTeXConverter(ReportConverter):
    """Converte ``relatorio_final.md`` para um documento LaTeX (classe ``article``)."""

    def convert(self, markdown_path: Path, output_path: Path) -> None:
        markdown_text = Path(markdown_path).read_text(encoding="utf-8")
        lines = markdown_text.splitlines()

        title = "Relatório Científico"
        first_line = lines[0] if lines else ""
        heading_match = _HEADING_RE.match(first_line)
        if heading_match and len(heading_match.group(1)) == 1:
            # O H1 vira \title{}/\maketitle — removido do corpo para não duplicar
            # como \section{} também.
            title = heading_match.group(2)
            lines = lines[1:]

        body = markdown_to_latex_body("\n".join(lines))
        document = (_LATEX_PREAMBLE % _escape_latex(title)) + body + "\n\\end{document}\n"

        Path(output_path).write_text(document, encoding="utf-8")
