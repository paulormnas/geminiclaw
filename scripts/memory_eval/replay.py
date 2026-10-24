"""Replay com corte temporal: a ordenação dos candidatos prevê os próximos resultados? (design §3; ADR 026 §7).

Para cada corte ``t`` (o fim de cada projeto/sessão), gera os candidatos com o grafo até ``t`` e mede a AUC contra o
que acontece depois de ``t``. Sem LLM. Lê o instantâneo de :mod:`scripts.memory_eval.snapshot`.

- **Par avaliado:** (Problema ativo depois de ``t``, abordagem vista em algum Problema até ``t``) sem registro do par
  até ``t``.
- **Positivo:** depois de ``t``, uma tentativa do par atinge o alvo ou melhora o melhor valor do Problema até então.
- **Ordenações:** ``padrao`` (design §2), ``semelhanca``, ``grau_abordagem`` e ``aleatoria`` (média de 100 sementes).
- **Intervalo:** bootstrap por projeto, 1000 reamostras, 95%.
- **Mundo fechado:** par nunca tentado conta como negativo; por isso o relatório traz também a AUC restrita aos pares
  tentados depois de ``t``.

Uso::

    uv run python -m scripts.memory_eval.replay --instantaneo snapshot.json --saida replay.json \\
        [--entre-problemas-distintos]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

root_path = str(Path(__file__).parent.parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from scripts.memory_eval.snapshot import sha256_of  # noqa: E402
from src import config  # noqa: E402
from src.knowledge.result_records import Attempt, Criterion, compute_record, improvement, reaches_target  # noqa: E402
from src.knowledge.structural_candidates import (  # noqa: E402
    Derivation,
    GraphView,
    ResultFact,
    default_score,
    generate,
)

RANDOM_SEEDS = 100
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20261024
ORDERINGS = ("padrao", "semelhanca", "grau_abordagem")


class ReplayError(Exception):
    """O replay não tem como calcular a AUC (sem positivos ou sem negativos); mensagem acionável."""


@dataclass(frozen=True)
class Row:
    projeto_id: str
    corte: str
    problema_id: str
    abordagem_key: str
    label: bool
    tentado: bool
    scores: dict[str, float]


def auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """AUC (Mann-Whitney) com empates pela posição média; ``ReplayError`` sem positivos ou sem negativos."""
    pos = int(labels.sum())
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        raise ReplayError(f"AUC indefinida: {pos} positivos e {neg} negativos.")
    _, inverse, counts = np.unique(scores, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    mean_rank = ends - (counts - 1) / 2.0
    ranks = mean_rank[inverse]
    return float((ranks[labels.astype(bool)].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def _criterion(raw: dict[str, Any]) -> Criterion:
    return Criterion(raw["sentido"], raw.get("delta_min"), raw.get("alvo"))


def positive_flags(snapshot: dict[str, Any]) -> dict[str, bool]:
    """``id`` da tentativa -> positiva (atinge o alvo ou melhora o melhor valor do Problema até então)."""
    criteria = {p["id"]: _criterion(p["criterio"]) for p in snapshot["problemas"]}
    best: dict[str, float] = {}
    flags: dict[str, bool] = {}
    for att in snapshot["tentativas"]:  # já ordenadas por (criado_em, id)
        crit = criteria[att["problema_id"]]
        value = att["valor"]
        earlier = best.get(att["problema_id"])
        improved = earlier is not None and improvement(value, earlier, crit.sentido) > 1e-12
        flags[att["id"]] = reaches_target(value, att["baseline"], crit) or improved
        if earlier is None or improvement(value, earlier, crit.sentido) > 0:
            best[att["problema_id"]] = value
    return flags


def _facts_until(snapshot: dict[str, Any], t: str) -> list[ResultFact]:
    criteria = {p["id"]: _criterion(p["criterio"]) for p in snapshot["problemas"]}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for att in snapshot["tentativas"]:
        if att["criado_em"] <= t:
            groups[(att["problema_id"], att["abordagem_key"])].append(att)
    facts = []
    for (problema_id, key), items in sorted(groups.items()):
        attempts = [
            Attempt(
                attempt_id=a["id"], timestamp=a["criado_em"], node_id="", session_id="", seed=a["seed"],
                dataset_ids=tuple(a["dataset_ids"]), config_hash=a["config_hash"], outcome_kind="resultado",
                value=a["valor"], baseline=a["baseline"], validation="validado",
            )
            for a in items
        ]
        record = compute_record(attempts, criteria[problema_id])
        facts.append(
            ResultFact(
                registro_id=f"{problema_id}:{key}", problema_id=problema_id, abordagem_key=key,
                criado_em=max(a["criado_em"] for a in items), delta_base=record.delta_base,
                delta_pai=record.delta_pai, atingiu_alvo=record.atingiu_alvo,
                n_replicas=max(record.n_replicas_independentes, 1),
            )
        )
    return facts


def build_rows(snapshot: dict[str, Any], *, distinct_problems: bool = False) -> list[Row]:
    """Linhas (par, rótulo, escores) de todos os cortes. ``distinct_problems`` zera a semelhança entre Problemas da
    mesma assinatura de dados (o mesmo problema repetido em outro projeto), isolando a transferência entre problemas."""
    problems = {p["id"]: p for p in snapshot["problemas"]}
    projeto_of_att: dict[str, str] = {a["id"]: problems[a["problema_id"]]["projeto_id"] for a in snapshot["tentativas"]}
    flags = positive_flags(snapshot)
    sims = snapshot["similaridade"]

    def similarity(a: str, b: str) -> float:
        if a == b:
            return 1.0
        if distinct_problems and problems[a]["assinatura"] == problems[b]["assinatura"]:
            return 0.0
        return float(sims.get(f"{a}|{b}", sims.get(f"{b}|{a}", 0.0)))

    derivations = tuple(Derivation(d["filha"], d["pai"], d["criado_em"]) for d in snapshot["derivacoes"])
    ends: dict[str, str] = {}
    for a in snapshot["tentativas"]:
        projeto = projeto_of_att[a["id"]]
        ends[projeto] = max(ends.get(projeto, ""), a["criado_em"])
    rows: list[Row] = []
    for t in sorted(set(ends.values())):
        facts = _facts_until(snapshot, t)
        view = GraphView(facts=tuple(facts), similarity=similarity, derivations=derivations)
        seen_keys = sorted({f.abordagem_key for f in facts})
        have = {(f.problema_id, f.abordagem_key) for f in facts}
        future: dict[tuple[str, str], list[bool]] = defaultdict(list)
        for a in snapshot["tentativas"]:
            if a["criado_em"] > t:
                future[(a["problema_id"], a["abordagem_key"])].append(flags[a["id"]])
        active = sorted({p for p, _ in future})
        for problema_id in active:
            cands = {c.abordagem_id: default_score(c.atributos) for c in generate(view, problema_id, t=t)}
            for key in seen_keys:
                if (problema_id, key) in have:
                    continue
                holders = [f.problema_id for f in facts if f.abordagem_key == key]
                after = future.get((problema_id, key), [])
                rows.append(
                    Row(
                        projeto_id=problems[problema_id]["projeto_id"], corte=t, problema_id=problema_id,
                        abordagem_key=key, label=any(after), tentado=bool(after),
                        scores={
                            "padrao": cands.get(key, 0.0),
                            "semelhanca": max((similarity(problema_id, h) for h in holders), default=0.0),
                            "grau_abordagem": float(len(set(holders))),
                        },
                    )
                )
    return rows


def _arrays(rows: list[Row]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    labels = np.array([r.label for r in rows], dtype=bool)
    return labels, {o: np.array([r.scores[o] for r in rows], dtype=float) for o in ORDERINGS}


def _random_auc(labels: np.ndarray, seed: int) -> float:
    return auc(labels, np.random.default_rng(seed).random(len(labels)))


def evaluate(rows: list[Row]) -> dict[str, Any]:
    """AUC das ordenações com intervalo por bootstrap de projetos; erro explícito sem positivos."""
    if not rows or not any(r.label for r in rows):
        raise ReplayError("Nenhum evento positivo depois de nenhum corte: o replay não calcula AUC sem positivos.")
    labels, scores = _arrays(rows)
    out: dict[str, Any] = {"n_pares": len(rows), "n_positivos": int(labels.sum())}
    point = {o: auc(labels, scores[o]) for o in ORDERINGS}
    point["aleatoria"] = float(np.mean([_random_auc(labels, s) for s in range(RANDOM_SEEDS)]))
    by_project: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_project[r.projeto_id].append(i)
    projects = sorted(by_project)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    samples: dict[str, list[float]] = {o: [] for o in (*ORDERINGS, "aleatoria")}
    for b in range(BOOTSTRAP_RESAMPLES):
        picked = rng.choice(len(projects), size=len(projects), replace=True)
        idx = np.concatenate([by_project[projects[j]] for j in picked])
        sub = labels[idx]
        if sub.sum() == 0 or sub.sum() == len(sub):
            continue
        for o in ORDERINGS:
            samples[o].append(auc(sub, scores[o][idx]))
        samples["aleatoria"].append(_random_auc(sub, b))
    for name, value in point.items():
        vals = samples[name]
        interval = [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))] if vals else None
        out[name] = {"auc": value, "ic95": interval, "resamples_validos": len(vals)}
    return out


def run(snapshot_text: str, *, distinct_problems: bool = False) -> dict[str, Any]:
    snapshot = json.loads(snapshot_text)
    rows = build_rows(snapshot, distinct_problems=distinct_problems)
    report = evaluate(rows)
    tried = [r for r in rows if r.tentado]
    try:
        report["somente_tentados"] = evaluate(tried) if tried else None
    except ReplayError as exc:
        report["somente_tentados"] = {"erro": str(exc)}
    report["cortes"] = sorted({r.corte for r in rows})
    report["entre_problemas_distintos"] = distinct_problems
    return report


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=root_path
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "desconhecido"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instantaneo", type=Path, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--entre-problemas-distintos", action="store_true")
    args = parser.parse_args()
    text = args.instantaneo.read_text(encoding="utf-8")
    try:
        report = run(text, distinct_problems=args.entre_problemas_distintos)
    except ReplayError as exc:
        raise SystemExit(f"replay: {exc}") from exc
    report["manifesto"] = {
        "commit": _commit(), "sha256_instantaneo": sha256_of(text), "sementes_aleatoria": RANDOM_SEEDS,
        "semente_bootstrap": BOOTSTRAP_SEED, "resamples": BOOTSTRAP_RESAMPLES,
        "candidate_min_similarity": config.CANDIDATE_MIN_SIMILARITY,
        "candidate_max_descendants": config.CANDIDATE_MAX_DESCENDANTS,
    }
    args.saida.write_text(json.dumps(report, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    for name in (*ORDERINGS, "aleatoria"):
        item = report[name]
        print(f"{name:15s} AUC {item['auc']:.3f}  IC95 {item['ic95']}")
    print(f"pares {report['n_pares']}, positivos {report['n_positivos']}")


if __name__ == "__main__":
    main()
