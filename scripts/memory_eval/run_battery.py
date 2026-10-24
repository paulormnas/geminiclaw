"""Roda uma bateria pré-registrada: braços alternados, parada por orçamento e corte do corpus (E1/E2).

Cada rodada ``r`` executa todos os braços, em ordem rotacionada (o primeiro braço muda a cada rodada), chamando
:mod:`scripts.benchmark.run_benchmark` com ``--only <braço> --repeat <r>`` (a chave ``(braço, r)`` permite retomar).
Antes de cada execução soma o custo já gasto por provedor em ``--results`` e para quando algum teto é atingido.
Com ``--corte-corpus`` grava uma cópia da matriz com ``RELATED_RECORDS_CUTOFF`` no ``env`` de cada braço (o instante
de início da bateria, em UTC), de modo que as sessões da própria bateria não entram na memória umas das outras.

Uso (no Pi, na raiz do repositório)::

    uv run python -m scripts.memory_eval.run_battery scripts/benchmark/matrix_e2_transferencia.json \\
        --results ~/bench/e2/results.json --n 5 --teto openai=5 --teto anthropic=3 --corte-corpus
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def spent_by_provider(results: list[dict]) -> dict[str, float]:
    """Custo acumulado por provedor dos resultados já gravados."""
    total: dict[str, float] = {}
    for item in results:
        for provider, cost in (item.get("tokens") or {}).get("cost_by_provider", {}).items():
            total[provider] = total.get(provider, 0.0) + float(cost)
    return total


def over_limit(spent: dict[str, float], limits: dict[str, float]) -> str | None:
    """Primeiro provedor cujo teto foi atingido, ou ``None``."""
    return next((p for p, cap in limits.items() if spent.get(p, 0.0) >= cap), None)


def rotated(arms: list[str], round_number: int) -> list[str]:
    """Braços em ordem rotacionada pela rodada (1 = ordem da matriz)."""
    shift = (round_number - 1) % len(arms)
    return arms[shift:] + arms[:shift]


def with_cutoff(matrix: dict, cutoff: str) -> dict:
    """Cópia da matriz com ``RELATED_RECORDS_CUTOFF`` no ``env`` de cada combinação."""
    copy = json.loads(json.dumps(matrix))
    for combo in copy["combinations"]:
        combo["env"] = {**combo.get("env", {}), "RELATED_RECORDS_CUTOFF": cutoff}
    return copy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--n", type=int, required=True, help="rodadas (execuções por braço)")
    parser.add_argument("--from-round", type=int, default=1)
    parser.add_argument("--teto", action="append", default=[], metavar="PROVEDOR=USD")
    parser.add_argument("--corte-corpus", action="store_true")
    args = parser.parse_args()
    limits = {k: float(v) for k, _, v in (item.partition("=") for item in args.teto)}
    matrix_path = args.matrix
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    args.results.parent.mkdir(parents=True, exist_ok=True)
    if args.corte_corpus:
        marker = args.results.with_name(args.results.stem + ".corte.txt")
        if marker.exists():
            cutoff = marker.read_text(encoding="utf-8").strip()
        else:
            cutoff = datetime.now(timezone.utc).isoformat()
            marker.write_text(cutoff + "\n", encoding="utf-8")
        matrix_path = args.results.with_name(args.results.stem + ".matriz.json")
        matrix_path.write_text(json.dumps(with_cutoff(matrix, cutoff), indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[bateria] corte do corpus: {cutoff}", flush=True)
    arms = [c["name"] for c in matrix["combinations"]]
    for round_number in range(args.from_round, args.n + 1):
        for arm in rotated(arms, round_number):
            results = json.loads(args.results.read_text(encoding="utf-8")) if args.results.exists() else []
            hit = over_limit(spent_by_provider(results), limits)
            if hit:
                print(f"[bateria] parada por orçamento ({hit}) antes de {arm} r{round_number}", flush=True)
                return 0
            print(f"[bateria] {arm} r{round_number} {datetime.now(timezone.utc).isoformat()}", flush=True)
            subprocess.run(
                [sys.executable, "-m", "scripts.benchmark.run_benchmark", str(matrix_path), "--results",
                 str(args.results), "--only", arm, "--repeat", str(round_number)],
                check=False,
            )
    print("[bateria] fim", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
