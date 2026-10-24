"""Descarta os pares ``relacionado`` pendentes da ``similarity_queue`` (V18.9, ``v18.9-cross-project-context`` §5).

Depois do ADR 026 §6 só duplicatas entram na fila; a relação entre Problemas é calculada sob demanda. Os pares
``relacionado`` ainda ``pendente`` passam a ``descartado`` com ``revisado_por = 'sistema'`` e o motivo
``ADR 026: relação sob demanda``, por ``UPDATE`` (nenhuma linha é apagada). As arestas ``SEMELHANTE_A`` já confirmadas
continuam válidas. Idempotente. Por padrão **só conta** o que faria; ``--aplicar`` grava.

Alteração de dados: rode só com a aprovação explícita do pesquisador.

Uso::

    uv run python scripts/migrate_v18_9_similarity_queue.py            # simulação
    uv run python scripts/migrate_v18_9_similarity_queue.py --aplicar
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.db import get_connection  # noqa: E402

MOTIVO = "ADR 026: relação sob demanda"
REVISOR = "sistema"


def pending_related(conn) -> int:
    """Pares ``relacionado`` ainda pendentes."""
    row = conn.execute(
        "SELECT count(*) AS n FROM similarity_queue WHERE status = 'pendente' AND tipo = 'relacionado'"
    ).fetchone()
    return int(row["n"])


def discard_related(conn) -> int:
    """Marca os pendentes ``relacionado`` como ``descartado``; devolve quantos."""
    return conn.execute(
        """
        UPDATE similarity_queue
        SET status = 'descartado', revisado_em = now(), revisado_por = %s, motivo = %s
        WHERE status = 'pendente' AND tipo = 'relacionado'
        """,
        (REVISOR, MOTIVO),
    ).rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aplicar", action="store_true", help="grava (o padrão só simula)")
    args = parser.parse_args()
    with get_connection() as conn:
        conn.execute("SET LOCAL search_path TO public")
        if args.aplicar:
            changed = discard_related(conn)
            print(f"{changed} pares relacionado pendentes passaram a descartado ({MOTIVO!r}).")
        else:
            print(f"Simulação: {pending_related(conn)} pares relacionado pendentes seriam descartados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
