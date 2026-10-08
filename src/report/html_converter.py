"""Conversor Markdown -> HTML do relatório científico (Roadmap V15.4 / Spec G8).

HTML estático com CSS acadêmico embutido, responsivo e legível para impressão.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.report.base_converter import MARKS_RE, ReportConverter, strip_markup_helpers

_PRINT_CSS = """
:root { color-scheme: light dark; }
body {
    font-family: "Georgia", "Times New Roman", serif;
    max-width: 860px;
    margin: 2rem auto;
    padding: 0 1.5rem;
    line-height: 1.6;
    color: #1a1a1a;
    background: #fdfdfd;
}
h1, h2, h3, h4 { font-family: "Helvetica Neue", Arial, sans-serif; line-height: 1.25; }
h1 { border-bottom: 2px solid #333; padding-bottom: 0.3rem; }
h2 { border-bottom: 1px solid #ccc; padding-bottom: 0.2rem; margin-top: 2rem; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { border: 1px solid #ccc; padding: 0.5rem 0.75rem; text-align: left; }
th { background: #f0f0f0; }
code, pre { font-family: "SFMono-Regular", Consolas, monospace; background: #f5f5f5; }
pre { padding: 1rem; overflow-x: auto; border-radius: 4px; }
code { padding: 0.15rem 0.3rem; border-radius: 3px; }
blockquote { border-left: 4px solid #ccc; margin-left: 0; padding-left: 1rem; color: #555; }
:root { --mark-bg: #fff3b0; --mark-fg: #5c4400; --origin-fg: #1f5f99; }
mark.nao-verificado, mark.literal {
    background: var(--mark-bg); color: var(--mark-fg); font-weight: 600; padding: 0 0.2rem; border-radius: 3px;
}
sup.origem a { color: var(--origin-fg); text-decoration: none; font-family: "Helvetica Neue", Arial, sans-serif; }

@media (prefers-color-scheme: dark) {
    body { background: #1a1a1a; color: #e8e8e8; }
    th { background: #2a2a2a; }
    code, pre { background: #262626; }
    blockquote { color: #aaa; }
    :root { --mark-bg: #5c4a00; --mark-fg: #ffe9a0; --origin-fg: #8fc4f5; }
}

@media print {
    body { max-width: 100%; color: #000; background: #fff; }
    a { color: #000; text-decoration: underline; }
    mark.nao-verificado, mark.literal { background: none; color: #000; border: 1px solid #000; }
}
"""

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


_CODE_BLOCK_RE = re.compile(r"(<pre\b.*?</pre>|<code\b.*?</code>)", re.DOTALL | re.IGNORECASE)


def _decorate_marks(html: str) -> str:
    """Troca as marcas de origem por links para o apêndice e destaca as demais, fora de ``<code>``/``<pre>``."""

    def replace(match: re.Match) -> str:
        if match.group(1):
            code = f"{match.group(1)}{match.group(2)}"
            return f'<sup class="origem"><a href="#origem-{code}">{code}</a></sup>'
        if match.group(0) == "[não verificado]":
            return '<mark class="nao-verificado">não verificado</mark>'
        return '<mark class="literal">literal no código</mark>'

    return "".join(
        chunk if _CODE_BLOCK_RE.fullmatch(chunk) else MARKS_RE.sub(replace, chunk)
        for chunk in _CODE_BLOCK_RE.split(html)
    )


class HTMLConverter(ReportConverter):
    """Converte ``relatorio_final.md`` para um HTML estático autocontido."""

    def convert(self, markdown_path: Path, output_path: Path) -> None:
        import markdown as md

        markdown_text = Path(markdown_path).read_text(encoding="utf-8")
        rendered = md.markdown(strip_markup_helpers(markdown_text), extensions=["tables", "fenced_code"])
        body_html = _decorate_marks(rendered)

        title = "Relatório Científico"
        for line in markdown_text.splitlines():
            if line.strip().startswith("# "):
                title = line.strip().lstrip("#").strip()
                break

        document = _HTML_TEMPLATE.format(title=title, css=_PRINT_CSS, body=body_html)
        Path(output_path).write_text(document, encoding="utf-8")
