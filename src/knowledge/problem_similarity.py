"""Semelhança de Problemas: texto e ``caracteristicas_dados`` (ADR 026 §6; ``v18.9-cross-project-context`` design §3).

Módulo puro, sem dependências do projeto além da configuração.
"""

from __future__ import annotations

import math
import re
from typing import Any

from src import config

_COUNT_KEYS = ("classes", "tamanho", "atributos", "linhas")
_CATEGORY_KEYS = ("modalidade", "tipo_tarefa")
_NUMBER = re.compile(r"\d[\d.,]*")


def _count(value: Any) -> float | None:
    """Primeiro número de um valor como ``"150 amostras"`` ou ``4`` (``None`` se não houver ou for <= 0)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        found = _NUMBER.search(str(value))
        if not found:
            return None
        try:
            number = float(found.group().replace(".", "").replace(",", "."))
        except ValueError:
            return None
    return number if number > 0 else None


def data_similarity(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float | None:
    """Média, sobre as características presentes nos dois Problemas, de ``1 - |log(a/b)| / log(10)`` (contagens,
    limitada a [0, 1]) e da igualdade (categorias). ``None`` quando não há característica em comum."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    scores: list[float] = []
    for key in _COUNT_KEYS:
        ca, cb = _count(a.get(key)), _count(b.get(key))
        if ca is not None and cb is not None:
            scores.append(min(1.0, max(0.0, 1.0 - abs(math.log(ca / cb)) / math.log(10))))
    for key in _CATEGORY_KEYS:
        if a.get(key) is not None and b.get(key) is not None:
            scores.append(1.0 if str(a[key]).strip().lower() == str(b[key]).strip().lower() else 0.0)
    return sum(scores) / len(scores) if scores else None


def problem_similarity(
    text_cosine: float, a: dict[str, Any] | None, b: dict[str, Any] | None, *, text_weight: float | None = None
) -> float:
    """``RELATED_TEXT_WEIGHT · cos(texto) + (1 − RELATED_TEXT_WEIGHT) · sim_dados``; sem dados, só o cosseno."""
    weight = config.RELATED_TEXT_WEIGHT if text_weight is None else text_weight
    sim_data = data_similarity(a, b)
    if sim_data is None:
        return text_cosine
    return weight * text_cosine + (1.0 - weight) * sim_data
