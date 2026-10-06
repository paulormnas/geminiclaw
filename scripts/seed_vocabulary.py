"""Carga inicial idempotente do vocabulário controlado (domínios CNPq e métricas).

Uso::

    uv run python scripts/seed_vocabulary.py [--dir data/vocabulary]

Falha de forma explícita se ``cnpq_areas.csv`` (tabela oficial do CNPq) não existir.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.knowledge.factory import open_graph_store  # noqa: E402
from src.knowledge.vocabulary import VocabularyError, seed_vocabulary  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Executa a carga e imprime os contadores."""
    parser = argparse.ArgumentParser(description="Carrega o vocabulário controlado no grafo.")
    parser.add_argument("--dir", type=Path, default=None, help="Diretório com cnpq_areas.csv e metrics.yaml.")
    args = parser.parse_args(argv)
    try:
        stats = seed_vocabulary(open_graph_store(), vocabulary_dir=args.dir)
    except (VocabularyError, RuntimeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    print(", ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
