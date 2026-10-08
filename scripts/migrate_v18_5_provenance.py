"""Aplica a migração do registro de execuções (V18.5, openspec/changes/v18.5-execution-provenance, tarefa 1.2).

Cria a tabela ``execution_records`` (somente-acréscimo, com gatilhos) a partir de
``scripts/migrations/v18_5_001_execution_records.sql``. Idempotente e aditiva: não altera nem apaga dados existentes.

Alteração de schema: rode só com a aprovação explícita do pesquisador.

Uso::

    uv run python scripts/migrate_v18_5_provenance.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garante que src/ seja importável quando executado como script solto.
root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.db import get_connection  # noqa: E402
from src.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

_MIGRATION_SQL_PATH = Path(__file__).parent / "migrations" / "v18_5_001_execution_records.sql"


def table_exists(conn) -> bool:
    """Informa se ``execution_records`` já existe no schema corrente."""
    row = conn.execute("SELECT to_regclass('execution_records') AS name").fetchone()
    return bool(row and row["name"])


def apply_migration(conn) -> bool:
    """Aplica o SQL da migração; devolve ``True`` se a tabela foi criada agora."""
    existed = table_exists(conn)
    conn.execute(_MIGRATION_SQL_PATH.read_text(encoding="utf-8"))
    return not existed


def main() -> int:
    with get_connection() as conn:
        created = apply_migration(conn)
    message = "Tabela execution_records criada." if created else "Tabela execution_records já existia (sem alterações)."
    logger.info(message)
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
