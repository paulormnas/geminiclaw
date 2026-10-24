"""Métricas do núcleo por braço, a partir de explorações arquivadas (design §4; ADR 026 §7).

| Métrica | Definição | Origem |
|---|---|---|
| ``taxa_sucesso`` | fração das explorações com ``objetivo_atingido`` no Problema | MLE-bench, MLEvolve |
| ``taxa_validas`` | fração com ao menos um ``Resultado`` de teste ou cv | MLE-bench, Wasted Compute |
| ``ganho_base`` | melhor ``delta_base`` da exploração (média no braço) | AgentX |
| ``falhas_repetidas`` | falhas cuja assinatura e escopo já ocorreram antes na exploração | Wasted Compute |

Cada métrica sai por braço com intervalo de 95% por bootstrap sobre as explorações e o n. As explorações vêm de
``grafo_projeto.json`` (arquivado por ``scripts/benchmark/archive.py``); o orçamento fixo por exploração é do
orquestrador de exploração e fica no pré-registro, não aqui.

Uso::

    uv run python -m scripts.memory_eval.metrics --braco sem_memoria=a/grafo_projeto.json,b/grafo_projeto.json \\
        --braco com_memoria=c/grafo_projeto.json --saida metricas.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

root_path = str(Path(__file__).parent.parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.knowledge.failure_cause import SIG_INSTALACAO_PACOTES, SIG_OOM, SIG_SEM_METRICAS, SIG_TIMEOUT  # noqa: E402

ESCOPO_AMBIENTE = "ambiente"
_AMBIENTE = frozenset({SIG_INSTALACAO_PACOTES, SIG_OOM, SIG_TIMEOUT, SIG_SEM_METRICAS})
_QUALIFICADORES = frozenset({"teste", "cv"})
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20261024
METRICS = ("taxa_sucesso", "taxa_validas", "ganho_base", "falhas_repetidas")


@dataclass(frozen=True)
class Failure:
    """Uma falha da exploração, na ordem em que ocorreu."""

    assinatura: str
    escopo: str


@dataclass(frozen=True)
class Exploration:
    """Uma exploração arquivada.

    Attributes:
        objetivo_atingido: O Problema tem marco de objetivo atingido.
        valida: Ao menos um ``Resultado`` de teste ou cv.
        ganho_base: Melhor ``delta_base`` dos registros (``None`` sem referência).
        falhas: Falhas em ordem cronológica.
    """

    objetivo_atingido: bool
    valida: bool
    ganho_base: float | None
    falhas: tuple[Failure, ...]


def repeated_failure_counts(falhas: tuple[Failure, ...]) -> tuple[int, int]:
    """``(repetidas, total)``: falhas cuja (assinatura, escopo) já tinha ocorrido antes."""
    seen: set[tuple[str, str]] = set()
    repeated = 0
    for f in falhas:
        key = (f.assinatura, f.escopo)
        repeated += key in seen
        seen.add(key)
    return repeated, len(falhas)


def exploration_from_graph(graph: dict[str, Any]) -> Exploration:
    """Exploração a partir do ``grafo_projeto.json`` arquivado (nós e arestas do projeto)."""
    nodes = {n["id"]: n for n in graph["nos"]}
    edges = graph["arestas"]
    props = lambda n: n["propriedades"]  # noqa: E731
    problems = [n for n in nodes.values() if n["label"] == "Problema"]
    reached = any(props(p).get("objetivo_atingido") for p in problems)
    produced: dict[str, list[str]] = {}
    applied: dict[str, str] = {}
    for e in edges:
        if e["tipo"] == "PRODUZIU":
            produced.setdefault(e["origem"], []).append(e["destino"])
        elif e["tipo"] == "APLICOU" and e["destino"] in nodes:
            applied[e["origem"]] = str(props(nodes[e["destino"]]).get("nome") or "")
    valid = any(
        nodes[r]["label"] == "Resultado" and props(nodes[r]).get("qualificador") in _QUALIFICADORES
        for results in produced.values()
        for r in results
        if r in nodes
    )
    deltas = [
        float(props(n)["delta_base"])
        for n in nodes.values()
        if n["label"] == "RegistroResultado" and props(n).get("delta_base") is not None
    ]
    falhas = []
    for n in sorted(
        (n for n in nodes.values() if n["label"] == "Experimento" and props(n).get("status") == "falha"),
        key=lambda n: (str(props(n).get("criado_em")), n["id"]),
    ):
        signature = props(n).get("assinatura_falha")
        if not signature:
            continue
        scope = ESCOPO_AMBIENTE if signature in _AMBIENTE else (applied.get(n["id"]) or "sem_abordagem")
        falhas.append(Failure(str(signature), scope))
    return Exploration(reached, valid, max(deltas) if deltas else None, tuple(falhas))


def _stat(explorations: list[Exploration], metric: str) -> float | None:
    if metric == "taxa_sucesso":
        return float(np.mean([e.objetivo_atingido for e in explorations]))
    if metric == "taxa_validas":
        return float(np.mean([e.valida for e in explorations]))
    if metric == "ganho_base":
        gains = [e.ganho_base for e in explorations if e.ganho_base is not None]
        return float(np.mean(gains)) if gains else None
    counts = [repeated_failure_counts(e.falhas) for e in explorations]
    total = sum(t for _, t in counts)
    return sum(r for r, _ in counts) / total if total else None


def compute_metrics(arms: dict[str, list[Exploration]]) -> dict[str, Any]:
    """Métricas por braço com IC 95% (bootstrap das explorações, semente fixa) e n."""
    report: dict[str, Any] = {}
    for arm, explorations in sorted(arms.items()):
        if not explorations:
            raise ValueError(f"Braço '{arm}' sem explorações: as métricas não podem ser calculadas.")
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        item: dict[str, Any] = {"n_exploracoes": len(explorations)}
        for metric in METRICS:
            samples = []
            for _ in range(BOOTSTRAP_RESAMPLES):
                pick = rng.integers(0, len(explorations), size=len(explorations))
                value = _stat([explorations[i] for i in pick], metric)
                if value is not None:
                    samples.append(value)
            item[metric] = {
                "valor": _stat(explorations, metric),
                "ic95": [float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))] if samples else None,
            }
        report[arm] = item
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--braco", action="append", required=True, help="nome=grafo1.json,grafo2.json")
    parser.add_argument("--saida", type=Path, required=True)
    args = parser.parse_args()
    arms: dict[str, list[Exploration]] = {}
    for spec in args.braco:
        name, _, files = spec.partition("=")
        arms[name] = [
            exploration_from_graph(json.loads(Path(f).read_text(encoding="utf-8"))) for f in files.split(",") if f
        ]
    report = compute_metrics(arms)
    args.saida.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for arm, item in report.items():
        values = {m: round(item[m]["valor"], 3) for m in METRICS if item[m]["valor"] is not None}
        print(arm, item["n_exploracoes"], values)


if __name__ == "__main__":
    main()
