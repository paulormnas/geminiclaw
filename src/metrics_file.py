"""Leitura tolerante do ``metrics.json`` de uma subtarefa (contrato: ``{"metrics": {...}}``).

O contrato pede o objeto ``metrics``, mas modelos (observado com o Gemini 3.8 flash no benchmark de 2026-10-12)
gravam as métricas na raiz (``{"accuracy": 0.95, ...}``). Todos os consumidores (revisor, ingestão no grafo,
proveniência, referências numéricas e relatório) leem por aqui, para que o mesmo arquivo valha igual em todo o
pipeline em vez de passar no revisor e sumir do grafo.
"""

from __future__ import annotations

from typing import Any, Mapping

# Chaves de metadado do contrato: não são métricas, mesmo quando numéricas (ex.: ``seed``).
NON_METRIC_KEYS = frozenset({
    "task_name", "session_id", "timestamp", "seed", "parameters", "divergence_note", "datasets", "baselines",
    "unidades", "metrics", "expected", "expected_metrics",
})


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_float(value: Any) -> float | None:
    """Número de um valor de métrica (aceita texto numérico, como o ``float()`` do revisor sempre aceitou)."""
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def metrics_of(data: Any, ignored_paths: list[str] | None = None) -> dict[str, Any]:
    """Métricas de um ``metrics.json``: o objeto ``metrics`` (ou ``metricas``) do contrato ou os números da raiz.

    No formato plano contam só valores numéricos (não booleanos) fora das chaves de metadado. Se o objeto
    ``metrics`` existe, ele vence sempre (nunca mistura com a raiz, nem com ``metricas``). Um nível de grupo
    numérico é achatado em ``grupo.metrica`` (``{"random_forest": {"accuracy": 0.9}}``); níveis mais profundos
    são ignorados e seus caminhos vão para ``ignored_paths`` (quando informado), para o log.
    """
    if not isinstance(data, dict):
        return {}
    container: dict[str, Any] | None = None
    for envelope in ("metrics", "metricas"):
        if isinstance(data.get(envelope), dict):
            container = data[envelope]
            break
    if container is None:
        container = {
            key: value for key, value in data.items()
            if key not in NON_METRIC_KEYS and _is_number(value)
        }
    return _flatten(container, ignored_paths)


def _flatten(container: dict[str, Any], ignored_paths: list[str] | None) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in container.items():
        if not isinstance(value, dict):
            flat[key] = value
            continue
        if key in NON_METRIC_KEYS:
            continue
        for sub_key, sub_value in value.items():
            if sub_key in NON_METRIC_KEYS:
                continue
            if _is_number(sub_value):
                flat[f"{key}.{sub_key}"] = sub_value
            elif isinstance(sub_value, dict) and ignored_paths is not None:
                ignored_paths.append(f"{key}.{sub_key}")
    return flat


def metric_candidates(
    metrics: dict[str, Any], base: str, qualifiers: set[str], aliases: Mapping[str, str] | None = None
) -> list[tuple[str, float]]:
    """(chave achatada, valor) de toda métrica cujo nome base é ``base`` e o qualificador está em ``qualifiers``.

    A comparação é pela forma normalizada do nome da métrica, sem o grupo (o que fica antes do último ``.``).
    ``aliases`` mapeia sinônimos para a forma canônica (``acuracia`` -> ``accuracy``) dos dois lados.
    """
    from src.knowledge.normalization import normalize_metric_name, split_metric_name

    canon = aliases or {}
    wanted = normalize_metric_name(base)
    wanted = canon.get(wanted, wanted)
    found: list[tuple[str, float]] = []
    for key, value in (metrics or {}).items():
        number = _as_float(value)
        if number is None:
            continue
        metric_part = str(key).rsplit(".", 1)[-1]
        parts = split_metric_name(metric_part)
        if canon.get(parts.base, parts.base) == wanted and parts.qualifier in qualifiers:
            found.append((str(key), number))
    return found
