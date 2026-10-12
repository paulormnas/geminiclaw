"""Leitura tolerante do ``metrics.json`` de uma subtarefa (contrato: ``{"metrics": {...}}``).

O contrato pede o objeto ``metrics``, mas modelos (observado com o Gemini 3.8 flash no benchmark de 2026-10-12)
gravam as métricas na raiz (``{"accuracy": 0.95, ...}``). Todos os consumidores (revisor, ingestão no grafo,
proveniência, referências numéricas e relatório) leem por aqui, para que o mesmo arquivo valha igual em todo o
pipeline em vez de passar no revisor e sumir do grafo.
"""

from __future__ import annotations

from typing import Any

# Chaves de metadado do contrato: não são métricas, mesmo quando numéricas (ex.: ``seed``).
NON_METRIC_KEYS = frozenset({
    "task_name", "session_id", "timestamp", "seed", "parameters", "divergence_note", "datasets", "baselines",
    "unidades", "metrics", "expected", "expected_metrics",
})


def metrics_of(data: Any) -> dict[str, Any]:
    """Métricas de um ``metrics.json``: o objeto ``metrics`` do contrato ou, sem ele, os números da raiz.

    No formato plano contam só valores numéricos (não booleanos) fora das chaves de metadado. Se o objeto
    ``metrics`` existe, ele vence sempre (nunca mistura com a raiz).
    """
    if not isinstance(data, dict):
        return {}
    nested = data.get("metrics")
    if isinstance(nested, dict):
        return nested
    return {
        key: value for key, value in data.items()
        if key not in NON_METRIC_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool)
    }
