"""Propriedades medidas por variante (design §6 de ``v18.8-verdict-lab``).

São relatadas como contagem de violações com um exemplo, sem reprovar a variante.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from scripts.verdict_lab.scenarios import Scenario
from scripts.verdict_lab.variants import Variant, lab_verdict
from src.knowledge.verdict import Attempt, Criterion

_TOL = 1e-9


def _later(attempts: tuple[Attempt, ...], **changes: Any) -> Attempt:
    """Tentativa de resultado posterior a todas, em nó, sessão e configuração novos."""
    n = len(attempts)
    base = dict(
        attempt_id=f"extra{n + 1}",
        timestamp=f"2026-01-02T{n // 60:02d}:{n % 60:02d}:00+00:00",
        node_id="n-novo",
        session_id="s-novo",
        seed=10_000 + n,
        dataset_ids=("d1",),
        config_hash="c-novo",
        outcome_kind="resultado",
        validation="validado",
        contract_complete=True,
        baseline=_baseline(attempts),
    )
    base.update(changes)
    return Attempt(**base)


def _baseline(attempts: tuple[Attempt, ...]) -> float | None:
    return next((a.baseline for a in attempts if a.baseline is not None), None)


def _sign(criterion: Criterion) -> int:
    return 1 if criterion.sentido == "maior_melhor" else -1


def _positive_value(s: Scenario) -> float:
    values = [a.value for a in s.attempts if a.value is not None]
    alvo = s.criterion.alvo or 0.0
    best = (max if _sign(s.criterion) == 1 else min)(values) if values else alvo
    candidate = alvo + _sign(s.criterion) * 2 * (s.criterion.delta_min or 0.01)
    return max(best, candidate) if _sign(s.criterion) == 1 else min(best, candidate)


def _negative_value(s: Scenario) -> float:
    baseline = _baseline(s.attempts)
    if baseline is not None:
        return baseline
    return (s.criterion.alvo or 0.0) - _sign(s.criterion) * 0.05


def _mirror(s: Scenario) -> tuple[Attempt, ...] | None:
    """Positivas viram negativas de mesmo peso (reflexo no alvo); ``None`` se o cenário não admite reflexo."""
    if not s.sem_baseline or s.criterion.alvo is None:
        return None
    if any(a.outcome_kind == "falha" and a.failure_cause == "abordagem" for a in s.attempts):
        return None
    alvo = s.criterion.alvo
    out = []
    for a in s.attempts:
        if a.value is not None and a.value != alvo:
            out.append(dataclasses.replace(a, value=2 * alvo - a.value))
        elif a.value is not None:
            return None
        else:
            out.append(a)
    return tuple(out)


def measure_properties(variants: list[Variant], scenarios: list[Scenario]) -> list[dict[str, Any]]:
    """Uma linha por (variante, propriedade): ``violacoes``, ``verificados`` e ``exemplo``."""
    by_name = {s.nome: s for s in scenarios}
    rows: list[dict[str, Any]] = []
    for variant in variants:
        found: dict[str, list[str]] = {
            k: [] for k in ("limites", "determinismo", "ordem_de_entrada", "monotonicidade", "simetria")
        }
        checked = dict.fromkeys(found, 0)
        for s in scenarios:
            attempts = list(s.attempts)
            r1 = lab_verdict(attempts, s.criterion, variant)
            v = r1.veredito

            checked["limites"] += 1
            if not (-1 - _TOL <= v <= 1 + _TOL and -_TOL <= r1.certeza < 1):
                found["limites"].append(f"{s.nome}: veredito {v:.4f}, certeza {r1.certeza:.4f}")

            checked["determinismo"] += 1
            if lab_verdict(attempts, s.criterion, variant) != r1:
                found["determinismo"].append(s.nome)

            checked["ordem_de_entrada"] += 1
            rv = lab_verdict(list(reversed(attempts)), s.criterion, variant).veredito
            if abs(rv - v) > _TOL:
                found["ordem_de_entrada"].append(f"{s.nome}: {v:.4f} -> {rv:.4f}")

            checked["monotonicidade"] += 2
            pos = lab_verdict(attempts + [_later(s.attempts, value=_positive_value(s))], s.criterion, variant).veredito
            if pos < v - _TOL:
                found["monotonicidade"].append(f"{s.nome} + positiva de nó novo: {v:.4f} -> {pos:.4f}")
            neg = lab_verdict(attempts + [_later(s.attempts, value=_negative_value(s))], s.criterion, variant).veredito
            if neg > v + _TOL:
                found["monotonicidade"].append(f"{s.nome} + negativa de nó novo: {v:.4f} -> {neg:.4f}")

            mirrored = _mirror(s)
            if mirrored is not None:
                checked["simetria"] += 1
                mv = lab_verdict(list(mirrored), s.criterion, variant).veredito
                if abs(mv + v) > _TOL:
                    found["simetria"].append(f"{s.nome}: {v:+.4f} e espelhado {mv:+.4f}")

        for prop, examples in found.items():
            rows.append(
                {
                    "variante": variant.nome,
                    "propriedade": prop,
                    "verificados": checked[prop],
                    "violacoes": len(examples),
                    "exemplo": examples[0] if examples else "",
                }
            )
        volume = ""
        if "V3" in by_name and "V20" in by_name:
            v3 = lab_verdict(list(by_name["V3"].attempts), by_name["V3"].criterion, variant).veredito
            v20 = lab_verdict(list(by_name["V20"].attempts), by_name["V20"].criterion, variant).veredito
            volume = f"V3 {v3:+.4f}, V20 {v20:+.4f}, razão {v20 / v3:.2f}" if v3 else f"V3 0, V20 {v20:+.4f}"
        rows.append(
            {
                "variante": variant.nome,
                "propriedade": "volume_sem_ganho",
                "verificados": 1,
                "violacoes": "",
                "exemplo": volume,
            }
        )
    return rows
