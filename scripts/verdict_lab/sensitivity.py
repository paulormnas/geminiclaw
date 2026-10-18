"""Sensibilidade do veredito aos parâmetros (design §6 de ``v18.8-verdict-lab``).

Varia cada parâmetro isoladamente (fatores sobre o valor da variante) e, para os de maior efeito, em pares,
medindo a variação média e máxima de ``|Δ veredito|`` sobre os cenários.
"""

from __future__ import annotations

import dataclasses
import itertools
from typing import Any

from scripts.verdict_lab.scenarios import Scenario
from scripts.verdict_lab.variants import Variant, lab_verdict

FACTORS = (0.5, 0.75, 1.25, 1.5)
_PARAMS = (
    "q_validated_complete",
    "q_validated_incomplete",
    "q_divergent",
    "d_new_node_or_dataset",
    "d_new_session",
    "d_new_seed",
    "gamma",
    "lambda_ambiguous",
    "approach_failure_q",
    "prior",
)
_STRUCT_WEIGHTS = ("d_variacao", "d_replica_no", "d_dataset", "d_sessao", "d_semente")


def tunable(variant: Variant) -> list[str]:
    """Parâmetros que podem mudar o veredito desta variante."""
    names = list(_PARAMS)
    if variant.estrutura.independencia == "por_tipo":
        names = [n for n in names if n not in ("d_new_node_or_dataset", "d_new_session", "d_new_seed")]
        names += list(_STRUCT_WEIGHTS)
    if variant.estrutura.variacao_util == "melhora_o_melhor":
        names.append("variacao_util_epsilon")
    return names


def _get(variant: Variant, name: str) -> float:
    if hasattr(variant.params, name):
        return getattr(variant.params, name)
    return getattr(variant.estrutura, name)


def _with(variant: Variant, values: dict[str, float]) -> Variant:
    params = {k: v for k, v in values.items() if hasattr(variant.params, k)}
    struct = {k: v for k, v in values.items() if k not in params}
    return dataclasses.replace(
        variant,
        params=dataclasses.replace(variant.params, **params),
        estrutura=dataclasses.replace(variant.estrutura, **struct),
    )


def _values(base: float, factors: tuple[float, ...]) -> list[float]:
    if base == 0:
        return [0.005, 0.01]
    return [base * f for f in factors]


def _effect(variant: Variant, changed: Variant, scenarios: list[Scenario], base: list[float]) -> tuple[float, float]:
    deltas = [abs(lab_verdict(list(s.attempts), s.criterion, changed).veredito - b) for s, b in zip(scenarios, base)]
    return sum(deltas) / len(deltas), max(deltas)


def run_sensitivity(
    variant: Variant, scenarios: list[Scenario], *, factors: tuple[float, ...] = FACTORS, top_pairs: int = 4
) -> list[dict[str, Any]]:
    """Linhas ``isolado`` (parâmetro, valor, efeito médio e máximo, posição) e ``par`` (dois parâmetros a ±25 %)."""
    base = [lab_verdict(list(s.attempts), s.criterion, variant).veredito for s in scenarios]
    isolated: list[dict[str, Any]] = []
    best: dict[str, float] = {}
    for name in tunable(variant):
        for value in _values(_get(variant, name), factors):
            mean, worst = _effect(variant, _with(variant, {name: value}), scenarios, base)
            isolated.append(
                {
                    "tabela": "isolado",
                    "variante": variant.nome,
                    "parametro": name,
                    "valor_base": _get(variant, name),
                    "valor": value,
                    "efeito_medio": mean,
                    "efeito_max": worst,
                }
            )
            best[name] = max(best.get(name, 0.0), mean)
    order = sorted(best, key=lambda n: -best[n])
    for row in isolated:
        row["posicao"] = order.index(row["parametro"]) + 1
    pairs: list[dict[str, Any]] = []
    for a, b in itertools.combinations(order[:top_pairs], 2):
        for f in (0.75, 1.25):
            va, vb = _get(variant, a) * f or 0.01, _get(variant, b) * f or 0.01
            mean, worst = _effect(variant, _with(variant, {a: va, b: vb}), scenarios, base)
            single = (
                _effect(variant, _with(variant, {a: va}), scenarios, base)[0]
                + _effect(variant, _with(variant, {b: vb}), scenarios, base)[0]
            )
            pairs.append(
                {
                    "tabela": "par",
                    "variante": variant.nome,
                    "parametro": f"{a}+{b}",
                    "valor": f,
                    "efeito_medio": mean,
                    "efeito_max": worst,
                    "interacao": mean - single,
                }
            )
    isolated.sort(key=lambda r: (r["posicao"], r["valor"]))
    return isolated + pairs
