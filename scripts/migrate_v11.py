"""Script de migração do schema do banco de dados para o Roadmap V11.

Ações:
  1. Remove as colunas permanentemente nulas da tabela ``subtask_metrics``:
     cpu_usage_avg, mem_usage_peak_mb, temp_delta_c, waiting_time_ms,
     total_tokens, tools_used_count.
  2. Cria (ou recria) a VIEW ``vw_subtask_performance`` que fornece as
     mesmas métricas agregadas via JOIN em ``token_usage`` e ``tool_usage``.

Uso::

    uv run python scripts/migrate_v11.py

O script é idempotente: verifica a existência das colunas antes de
tentar removê-las e usa CREATE OR REPLACE VIEW.
"""

import sys
from pathlib import Path

# Garante que src/ seja importável
root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.db import get_pool, get_connection
from src.logger import get_logger

logger = get_logger(__name__)

# Colunas da V10 que devem ser removidas (estavam sempre NULL)
_COLUMNS_TO_DROP = [
    "cpu_usage_avg",
    "mem_usage_peak_mb",
    "temp_delta_c",
    "waiting_time_ms",
    "total_tokens",
    "tools_used_count",
]

_VIEW_SQL = """
CREATE OR REPLACE VIEW vw_subtask_performance AS
SELECT
    sm.id,
    sm.execution_id,
    sm.task_name,
    sm.agent_id,
    sm.status,
    sm.created_at,
    sm.started_at,
    sm.finished_at,
    sm.duration_total_ms,
    sm.duration_active_ms,
    sm.total_cost_usd,
    sm.llm_calls_count,
    sm.retry_count,
    sm.error_type,
    -- Tokens agregados a partir de token_usage (fonte da verdade)
    COALESCE(tu.total_tokens, 0)       AS total_tokens,
    COALESCE(tu.total_prompt_tokens, 0) AS total_prompt_tokens,
    COALESCE(tu.total_completion_tokens, 0) AS total_completion_tokens,
    -- Contagem de ferramentas a partir de tool_usage (fonte da verdade)
    COALESCE(tl.tools_used_count, 0)   AS tools_used_count,
    COALESCE(tl.tools_ok_count, 0)     AS tools_ok_count
FROM subtask_metrics sm
LEFT JOIN (
    SELECT
        task_name,
        execution_id,
        SUM(total_tokens)      AS total_tokens,
        SUM(prompt_tokens)     AS total_prompt_tokens,
        SUM(completion_tokens) AS total_completion_tokens
    FROM token_usage
    GROUP BY task_name, execution_id
) tu ON tu.task_name = sm.task_name AND tu.execution_id = sm.execution_id
LEFT JOIN (
    SELECT
        task_name,
        execution_id,
        COUNT(*)                                AS tools_used_count,
        SUM(CASE WHEN success THEN 1 ELSE 0 END) AS tools_ok_count
    FROM tool_usage
    GROUP BY task_name, execution_id
) tl ON tl.task_name = sm.task_name AND tl.execution_id = sm.execution_id;
"""


def _column_exists(conn, table: str, column: str) -> bool:
    """Verifica se uma coluna existe em uma tabela PostgreSQL.

    Args:
        conn: Conexão ativa.
        table: Nome da tabela.
        column: Nome da coluna.

    Returns:
        True se a coluna existir, False caso contrário.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    ).fetchone()
    return bool(row and (row["cnt"] if isinstance(row, dict) else row[0]) > 0)


def run_migration() -> None:
    """Executa a migração V11 no banco de dados.

    Raises:
        SystemExit: Em caso de falha irrecuperável.
    """
    pool = get_pool()
    pool.open()

    try:
        with get_connection() as conn:
            # --- V11.3.1: Remover colunas nulas ---
            dropped = []
            skipped = []
            for col in _COLUMNS_TO_DROP:
                if _column_exists(conn, "subtask_metrics", col):
                    logger.info(
                        "Removendo coluna de subtask_metrics",
                        extra={"column": col},
                    )
                    conn.execute(f"ALTER TABLE subtask_metrics DROP COLUMN {col}")
                    dropped.append(col)
                else:
                    skipped.append(col)

            if dropped:
                logger.info(
                    "Colunas removidas com sucesso",
                    extra={"dropped": dropped},
                )
            if skipped:
                logger.info(
                    "Colunas já inexistentes (skip idempotente)",
                    extra={"skipped": skipped},
                )

            # --- V11.3.3: Criar/Recriar VIEW ---
            logger.info("Criando/atualizando vw_subtask_performance")
            conn.execute(_VIEW_SQL)
            logger.info("VIEW vw_subtask_performance criada com sucesso.")

    except Exception as e:
        logger.error("Falha na migração V11", extra={"error": str(e)})
        sys.exit(1)
    finally:
        pool.close()

    print("✅ Migração V11 concluída com sucesso.")
    print(f"   Colunas removidas: {_COLUMNS_TO_DROP}")
    print("   VIEW criada: vw_subtask_performance")


if __name__ == "__main__":
    run_migration()
