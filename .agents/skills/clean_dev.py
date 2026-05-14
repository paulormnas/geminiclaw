#!/usr/bin/env python3
"""Limpeza do ambiente de desenvolvimento GeminiClaw.

Remove logs, artefatos de output e registros nos bancos PostgreSQL e Qdrant,
preparando um estado limpo para iniciar novas avaliações.

Uso::

    # Limpeza completa (logs + outputs + postgres + qdrant)
    uv run python .agents/skills/clean_dev.py

    # Apenas logs e outputs (sem tocar nos bancos)
    uv run python .agents/skills/clean_dev.py --skip-postgres --skip-qdrant

    # Apenas bancos de dados
    uv run python .agents/skills/clean_dev.py --skip-logs --skip-outputs

    # Dry-run: mostra o que seria removido sem executar
    uv run python .agents/skills/clean_dev.py --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

# Garante que src/ está no path ao executar o script diretamente
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.logger import get_logger
from src.db import get_connection

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

#: Tabelas PostgreSQL a serem truncadas (ordem respeita FK constraints).
POSTGRES_TABLES: list[str] = [
    "subtask_metrics",
    "agent_events",
    "tool_usage",
    "token_usage",
    "hardware_snapshots",
    "document_chunks",
    "documents",
    "deep_search_cache",
    "long_term_memory",
    "llm_cache",
    "agent_sessions",
    "execution_history",
]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _make_qdrant_client() -> Any:
    """Cria e retorna um cliente Qdrant configurado via variáveis de ambiente.

    Returns:
        Instância de ``QdrantClient`` conectada ao servidor configurado.

    Raises:
        ImportError: Se o pacote ``qdrant-client`` não estiver instalado.
        Exception: Se a conexão falhar.
    """
    import os

    from qdrant_client import QdrantClient  # type: ignore[import-untyped]

    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    logger.info("Conectando ao Qdrant", extra={"url": url})
    return QdrantClient(url=url)


# ---------------------------------------------------------------------------
# Funções de limpeza
# ---------------------------------------------------------------------------


def clean_logs(logs_dir: Path) -> dict[str, int]:
    """Remove todos os arquivos de log do diretório especificado.

    Preserva arquivos que não terminam em ``.log`` (ex: ``.gitkeep``).
    Erros de I/O são registrados e contados, mas não interrompem a execução.

    Args:
        logs_dir: Caminho para o diretório de logs.

    Returns:
        Dicionário com chaves ``removed`` (arquivos removidos) e
        ``errors`` (falhas de I/O).
    """
    result: dict[str, int] = {"removed": 0, "errors": 0}

    if not logs_dir.exists():
        logger.info(
            "Diretório de logs não encontrado — ignorando",
            extra={"path": str(logs_dir)},
        )
        return result

    for log_file in logs_dir.rglob("*.log"):
        logger.info("Removendo log", extra={"file": str(log_file)})
        try:
            log_file.unlink()
            result["removed"] += 1
        except OSError as exc:
            logger.error(
                "Falha ao remover log",
                extra={"file": str(log_file), "error": str(exc)},
            )
            result["errors"] += 1

    logger.info(
        "Limpeza de logs concluída",
        extra={"removed": result["removed"], "errors": result["errors"]},
    )
    return result


def clean_outputs(outputs_dir: Path) -> dict[str, int]:
    """Remove todos os subdiretórios de sessão dentro de ``outputs_dir``.

    Cada execução do pipeline gera um subdiretório com timestamp. Esta
    função os remove recursivamente, preservando o próprio ``outputs_dir``.

    Args:
        outputs_dir: Caminho para o diretório de outputs.

    Returns:
        Dicionário com chaves ``removed`` (diretórios removidos) e
        ``errors`` (falhas de I/O).
    """
    result: dict[str, int] = {"removed": 0, "errors": 0}

    if not outputs_dir.exists():
        logger.info(
            "Diretório de outputs não encontrado — ignorando",
            extra={"path": str(outputs_dir)},
        )
        return result

    session_dirs = [p for p in outputs_dir.iterdir() if p.is_dir()]

    for session_dir in session_dirs:
        logger.info(
            "Removendo diretório de sessão",
            extra={"dir": str(session_dir)},
        )
        try:
            shutil.rmtree(session_dir)
            result["removed"] += 1
        except OSError as exc:
            logger.error(
                "Falha ao remover diretório de sessão",
                extra={"dir": str(session_dir), "error": str(exc)},
            )
            result["errors"] += 1

    logger.info(
        "Limpeza de outputs concluída",
        extra={"removed": result["removed"], "errors": result["errors"]},
    )
    return result


def clean_postgres() -> dict[str, int]:
    """Trunca todas as tabelas de telemetria e histórico no PostgreSQL.

    Usa ``TRUNCATE … CASCADE`` para respeitar foreign keys. Reinicia os
    contadores de ``llm_cache_stats``. A conexão é obtida via
    ``src.db.get_connection`` que lê ``DATABASE_URL`` do ambiente.

    Returns:
        Dicionário com chaves ``tables_truncated`` e ``errors``.
    """
    result: dict[str, int] = {"tables_truncated": 0, "errors": 0}

    logger.info(
        "Iniciando truncagem das tabelas PostgreSQL",
        extra={"tables": POSTGRES_TABLES},
    )

    try:
        with get_connection() as conn:

            for table in POSTGRES_TABLES:
                try:
                    logger.info("Truncando tabela", extra={"table": table})
                    conn.execute(f"TRUNCATE TABLE {table} CASCADE")  # noqa: S608
                    result["tables_truncated"] += 1
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Falha ao truncar tabela",
                        extra={"table": table, "error": str(exc)},
                    )
                    result["errors"] += 1

            # Reinicia contadores do cache de LLM
            try:
                conn.execute(
                    "UPDATE llm_cache_stats SET hits = 0, misses = 0 WHERE id = 1"
                )
                logger.info("Contadores de llm_cache_stats resetados")
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Falha ao resetar llm_cache_stats",
                    extra={"error": str(exc)},
                )
                result["errors"] += 1

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Falha na conexão com PostgreSQL",
            extra={"error": str(exc)},
        )
        result["errors"] += 1

    logger.info(
        "Limpeza PostgreSQL concluída",
        extra={
            "tables_truncated": result["tables_truncated"],
            "errors": result["errors"],
        },
    )
    return result


def clean_qdrant() -> dict[str, int]:
    """Remove todas as coleções do Qdrant.

    Conecta via ``QDRANT_URL`` (padrão: ``http://localhost:6333``).
    Falhas em coleções individuais não interrompem a limpeza das demais.

    Returns:
        Dicionário com chaves ``collections_deleted`` e ``errors``.
    """
    result: dict[str, int] = {"collections_deleted": 0, "errors": 0}

    try:
        client = _make_qdrant_client()
        collections = client.get_collections().collections
        logger.info(
            "Coleções Qdrant encontradas",
            extra={"count": len(collections)},
        )

        for col in collections:
            logger.info(
                "Deletando coleção Qdrant",
                extra={"collection": col.name},
            )
            try:
                client.delete_collection(col.name)
                result["collections_deleted"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Falha ao deletar coleção Qdrant",
                    extra={"collection": col.name, "error": str(exc)},
                )
                result["errors"] += 1

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Falha ao conectar no Qdrant",
            extra={"error": str(exc)},
        )
        result["errors"] += 1

    logger.info(
        "Limpeza Qdrant concluída",
        extra={
            "collections_deleted": result["collections_deleted"],
            "errors": result["errors"],
        },
    )
    return result


# ---------------------------------------------------------------------------
# Orquestrador principal
# ---------------------------------------------------------------------------


def clean_all(
    logs_dir: Path,
    outputs_dir: Path,
    skip_postgres: bool = False,
    skip_qdrant: bool = False,
    skip_logs: bool = False,
    skip_outputs: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Orquestra a limpeza completa do ambiente de desenvolvimento.

    Args:
        logs_dir: Caminho para o diretório de logs.
        outputs_dir: Caminho para o diretório de outputs.
        skip_postgres: Se ``True``, pula a limpeza do PostgreSQL.
        skip_qdrant: Se ``True``, pula a limpeza do Qdrant.
        skip_logs: Se ``True``, pula a limpeza de logs.
        skip_outputs: Se ``True``, pula a limpeza de outputs.
        dry_run: Se ``True``, apenas loga o que seria feito sem executar.

    Returns:
        Dicionário com resultados de cada subsistema e ``total_errors``.
    """
    summary: dict[str, Any] = {
        "logs": {"removed": 0, "errors": 0},
        "outputs": {"removed": 0, "errors": 0},
        "postgres": {"tables_truncated": 0, "errors": 0},
        "qdrant": {"collections_deleted": 0, "errors": 0},
        "total_errors": 0,
    }

    if dry_run:
        logger.info(
            "DRY-RUN ativado — nenhuma ação destrutiva será executada",
            extra={
                "logs_dir": str(logs_dir),
                "outputs_dir": str(outputs_dir),
                "skip_postgres": skip_postgres,
                "skip_qdrant": skip_qdrant,
            },
        )
        return summary

    if not skip_logs:
        summary["logs"] = clean_logs(logs_dir)

    if not skip_outputs:
        summary["outputs"] = clean_outputs(outputs_dir)

    if not skip_postgres:
        summary["postgres"] = clean_postgres()

    if not skip_qdrant:
        summary["qdrant"] = clean_qdrant()

    summary["total_errors"] = sum(
        v.get("errors", 0)
        for v in summary.values()
        if isinstance(v, dict)
    )

    return summary


# ---------------------------------------------------------------------------
# Entrypoint CLI
# ---------------------------------------------------------------------------


def _print_summary(summary: dict[str, Any]) -> None:
    """Imprime o resumo da limpeza no stdout."""
    logs = summary["logs"]
    outputs = summary["outputs"]
    pg = summary["postgres"]
    qd = summary["qdrant"]
    total = summary["total_errors"]

    print("\n✅ Limpeza concluída")
    print("─" * 50)
    print(f"   Logs removidos:          {logs['removed']:>5}")
    print(f"   Sessões de output:        {outputs['removed']:>5}")
    print(f"   Tabelas PG truncadas:     {pg['tables_truncated']:>5}")
    print(f"   Coleções Qdrant deletadas:{qd['collections_deleted']:>5}")
    print("─" * 50)
    if total:
        print(f"   ⚠️  Total de erros:        {total:>5}")
    else:
        print("   Sem erros registrados.")
    print()


def main() -> None:
    """Ponto de entrada do script de limpeza."""
    repo_root = Path(__file__).parent.parent.parent

    parser = argparse.ArgumentParser(
        description="Limpa logs, artefatos e registros de banco para novas avaliações.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--logs-dir",
        default=str(repo_root / "logs"),
        help="Diretório de logs (padrão: ./logs).",
    )
    parser.add_argument(
        "--outputs-dir",
        default=str(repo_root / "outputs"),
        help="Diretório de outputs (padrão: ./outputs).",
    )
    parser.add_argument(
        "--skip-postgres",
        action="store_true",
        help="Pula a limpeza das tabelas PostgreSQL.",
    )
    parser.add_argument(
        "--skip-qdrant",
        action="store_true",
        help="Pula a limpeza das coleções Qdrant.",
    )
    parser.add_argument(
        "--skip-logs",
        action="store_true",
        help="Pula a limpeza dos arquivos de log.",
    )
    parser.add_argument(
        "--skip-outputs",
        action="store_true",
        help="Pula a limpeza dos artefatos de output.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Exibe o que seria removido sem executar nenhuma ação.",
    )
    args = parser.parse_args()

    logger.info(
        "Iniciando limpeza do ambiente de desenvolvimento",
        extra={
            "logs_dir": args.logs_dir,
            "outputs_dir": args.outputs_dir,
            "skip_postgres": args.skip_postgres,
            "skip_qdrant": args.skip_qdrant,
            "dry_run": args.dry_run,
        },
    )

    summary = clean_all(
        logs_dir=Path(args.logs_dir),
        outputs_dir=Path(args.outputs_dir),
        skip_postgres=args.skip_postgres,
        skip_qdrant=args.skip_qdrant,
        skip_logs=args.skip_logs,
        skip_outputs=args.skip_outputs,
        dry_run=args.dry_run,
    )

    _print_summary(summary)

    if summary["total_errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
