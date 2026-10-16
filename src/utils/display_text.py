"""Texto seguro para o terminal (movido de ``src/knowledge/graph_views.py`` sem alterar o comportamento).

Fica em ``utils`` para que o gate (camada baixa) e o grafo usem a mesma sanitização de exibição.
"""

from __future__ import annotations

import unicodedata
from typing import Any

_REMOVED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


def sanitize_line(value: Any, limit: int) -> str:
    """Texto seguro para o terminal, em uma linha.

    Remove caracteres de controle (inclui ``ESC``, ``DEL`` e os C1), de formatação (inclui marcas bidi e de largura
    zero), separadores de linha/parágrafo, caracteres privados e não atribuídos; quebras e tabulações viram espaço e
    espaços repetidos colapsam. Com ``limit`` positivo, corta com reticências.
    """
    text = value if isinstance(value, str) else str(value)
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if char in "\n\r\t":
            kept.append(" ")
        elif category in _REMOVED_CATEGORIES:
            continue
        else:
            kept.append(char)
    clean = " ".join("".join(kept).split())
    if limit > 0 and len(clean) > limit:
        clean = clean[: max(limit - 1, 0)] + "…"
    return clean
