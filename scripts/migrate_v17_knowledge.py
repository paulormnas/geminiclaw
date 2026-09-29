"""Script de migração do grafo de conhecimento para o Roadmap V17 (ADR 009, ADR 015).

Aplica ``scripts/migrations/v17_001_knowledge_graph.sql`` (extensão Apache AGE,
grafo, tabela ``knowledge_audit``) e, a partir de ``src.knowledge.schema``
(fonte única da verdade), gera e aplica:

    - um rótulo de vértice (``create_vlabel``) para cada nó em ``NODE_SCHEMAS``;
    - um rótulo de aresta (``create_elabel``) para cada relação em ``RELATION_TYPES``;
    - um índice por rótulo de nó na propriedade ``id`` (busca por identidade);
    - o papel de banco somente-leitura ``knowledge_reader`` (senha vinda de
      ``KNOWLEDGE_READER_PASSWORD``), com ``statement_timeout`` de
      ``config.KNOWLEDGE_READ_TIMEOUT_MS``.

Idempotente: toda operação verifica a existência do objeto antes de criá-lo.

Uso::

    uv run python scripts/migrate_v17_knowledge.py

Aviso operacional (ver relatório do PR desta mudança): a sintaxe exata de
alguns comandos específicos do Apache AGE (nomes internos de tabela por
rótulo, sintaxe de índice em propriedade ``agtype``) não foi validada contra
uma instância real neste ambiente de desenvolvimento — apenas contra a
documentação da extensão. Rode este script uma vez em um banco de
teste/isolado e confira os logs antes de aplicá-lo em qualquer ambiente
compartilhado (tarefa 5.1/5.2 de ``openspec/changes/v17-graph-store/tasks.md``).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garante que src/ seja importável quando executado como script solto.
root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src import config  # noqa: E402
from src.db import get_connection, get_pool  # noqa: E402
from src.knowledge import schema  # noqa: E402
from src.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

_MIGRATION_SQL_PATH = Path(__file__).parent / "migrations" / "v17_001_knowledge_graph.sql"


def _graph_exists(conn, graph_name: str) -> bool:
    """Verifica se o grafo já existe em ``ag_catalog.ag_graph``."""
    row = conn.execute(
        "SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s", (graph_name,)
    ).fetchone()
    return row is not None


def _label_exists(conn, graph_name: str, label: str) -> bool:
    """Verifica se um rótulo (vértice ou aresta) já existe no grafo."""
    row = conn.execute(
        """
        SELECT 1
        FROM ag_catalog.ag_label l
        JOIN ag_catalog.ag_graph g ON g.graphid = l.graph
        WHERE g.name = %s AND l.name = %s
        """,
        (graph_name, label),
    ).fetchone()
    return row is not None


def _role_exists(conn, role_name: str) -> bool:
    """Verifica se o papel de banco já existe."""
    row = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,)).fetchone()
    return row is not None


def apply_static_sql(conn, graph_name: str) -> None:
    """Aplica o template SQL estático (extensão, grafo, tabela de auditoria).

    Args:
        conn: Conexão ativa (papel com privilégio de DDL).
        graph_name: Nome do grafo AGE (``config.KNOWLEDGE_GRAPH_NAME``).
    """
    sql_template = _MIGRATION_SQL_PATH.read_text(encoding="utf-8")
    conn.execute(sql_template.format(graph_name=graph_name))
    logger.info("SQL estático da migração v17_001 aplicado.", extra={"extra": {"graph": graph_name}})


def create_node_labels(conn, graph_name: str) -> list[str]:
    """Cria (idempotentemente) um rótulo de vértice e índice de ``id`` por nó do schema.

    Args:
        conn: Conexão ativa.
        graph_name: Nome do grafo AGE.

    Returns:
        Lista dos rótulos criados nesta execução (vazia se todos já existiam).
    """
    created = []
    for label in sorted(schema.NODE_LABELS):
        if _label_exists(conn, graph_name, label):
            continue
        conn.execute("SELECT create_vlabel(%s, %s)", (graph_name, label))
        # Índice GIN sobre as propriedades — cobre buscas por igualdade/contenção
        # em qualquer propriedade, incluindo `id` (usado por get_node/create_edge).
        # A tabela física do rótulo vive no schema do grafo, com o mesmo nome do rótulo.
        conn.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{label.lower()}_properties" '
            f'ON "{graph_name}"."{label}" USING GIN (properties)'
        )
        created.append(label)
        logger.info("Rótulo de nó criado", extra={"extra": {"label": label, "graph": graph_name}})
    return created


def create_relation_labels(conn, graph_name: str) -> list[str]:
    """Cria (idempotentemente) um rótulo de aresta por tipo de relação do schema.

    Args:
        conn: Conexão ativa.
        graph_name: Nome do grafo AGE.

    Returns:
        Lista dos rótulos de relação criados nesta execução.
    """
    created = []
    for rel_type in sorted(schema.RELATION_TYPES):
        if _label_exists(conn, graph_name, rel_type):
            continue
        conn.execute("SELECT create_elabel(%s, %s)", (graph_name, rel_type))
        created.append(rel_type)
        logger.info("Rótulo de relação criado", extra={"extra": {"rel_type": rel_type, "graph": graph_name}})
    return created


def create_reader_role(conn, graph_name: str) -> bool:
    """Cria (idempotentemente) o papel somente-leitura ``knowledge_reader``.

    Args:
        conn: Conexão ativa (papel com privilégio para criar roles/grants).
        graph_name: Nome do grafo AGE (usado para GRANT USAGE/SELECT).

    Returns:
        True se o papel foi criado nesta execução; False se já existia.

    Raises:
        RuntimeError: ``KNOWLEDGE_READER_PASSWORD`` não está definida no ambiente.
    """
    from src.config import get_env

    password = get_env("KNOWLEDGE_READER_PASSWORD", required=True)
    role_name = "knowledge_reader"

    created = False
    if not _role_exists(conn, role_name):
        conn.execute(
            f"CREATE ROLE {role_name} LOGIN PASSWORD %s",
            (password,),
        )
        created = True
        logger.info("Papel knowledge_reader criado.")
    else:
        conn.execute(f"ALTER ROLE {role_name} PASSWORD %s", (password,))
        logger.info("Papel knowledge_reader já existia; senha sincronizada com KNOWLEDGE_READER_PASSWORD.")

    conn.execute(f'GRANT USAGE ON SCHEMA "{graph_name}", ag_catalog TO {role_name}')
    conn.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{graph_name}" TO {role_name}')
    conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA ag_catalog TO {role_name}")
    conn.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{graph_name}" GRANT SELECT ON TABLES TO {role_name}'
    )
    conn.execute(
        f"ALTER ROLE {role_name} SET statement_timeout = '{int(config.KNOWLEDGE_READ_TIMEOUT_MS)}'"
    )
    return created


def run_migration() -> None:
    """Executa a migração v17_001 completa no banco configurado por ``DATABASE_URL``.

    Raises:
        SystemExit: Em caso de falha irrecuperável (a exceção original é logada).
    """
    graph_name = config.KNOWLEDGE_GRAPH_NAME
    pool = get_pool()
    pool.open()

    try:
        with get_connection() as conn:
            apply_static_sql(conn, graph_name)
            conn.commit()

            node_labels_created = create_node_labels(conn, graph_name)
            conn.commit()

            rel_labels_created = create_relation_labels(conn, graph_name)
            conn.commit()

            reader_created = create_reader_role(conn, graph_name)
            conn.commit()
    except Exception as e:
        logger.error("Falha na migração v17_001", extra={"extra": {"error": str(e)}})
        sys.exit(1)
    finally:
        pool.close()

    logger.info(
        "Migração v17_001 concluída.",
        extra={
            "extra": {
                "graph": graph_name,
                "node_labels_created": node_labels_created,
                "relation_labels_created": rel_labels_created,
                "reader_role_created": reader_created,
            }
        },
    )


if __name__ == "__main__":
    run_migration()
