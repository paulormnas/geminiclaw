#!/usr/bin/env python3
"""Script de exportação de métricas de telemetria para CSV.

Exporta dados das tabelas de telemetria (agent_events, tool_usage,
token_usage, hardware_snapshots) para arquivos CSV compatíveis com
pandas/Excel para análise acadêmica.

Uso::

    # Exporta todas as tabelas para ./metrics/<execution_id>/
    uv run python scripts/export_metrics.py <execution_id>

    # Exporta para um diretório customizado
    uv run python scripts/export_metrics.py <execution_id> --output-dir ./meus_dados

    # Lista execuções recentes
    uv run python scripts/export_metrics.py --list
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Garante que o src/ está no path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logger import get_logger
from src.db import get_connection, get_pool

logger = get_logger(__name__)


def _write_csv(rows: list[dict[str, Any]], path: Path) -> int:
    """Escreve uma lista de dicts em um arquivo CSV.

    Args:
        rows: Lista de dicionários com os dados.
        path: Caminho do arquivo CSV de saída.

    Returns:
        Número de linhas escritas.
    """
    if not rows:
        logger.info(f"Sem dados para {path.name} — arquivo não criado.")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"CSV exportado: {path} ({len(rows)} linhas)")
    return len(rows)


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Converte campos JSON/datetime em strings para o CSV."""
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, (dict, list)):
            result[k] = json.dumps(v, ensure_ascii=False)
        else:
            result[k] = v
    return result


def export_agent_events(execution_id: str, output_dir: Path) -> int:
    """Exporta agent_events para CSV.

    Args:
        execution_id: ID da execução.
        output_dir: Diretório de saída.

    Returns:
        Número de linhas exportadas.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, execution_id, session_id, agent_id, event_type,
                   target_agent_id, task_name, payload_json, timestamp, duration_ms
            FROM agent_events
            WHERE execution_id = %s
            ORDER BY timestamp ASC
            """,
            (execution_id,),
        ).fetchall()
    return _write_csv(
        [_serialize_row(dict(r)) for r in rows],
        output_dir / "agent_events.csv",
    )


def export_tool_usage(execution_id: str, output_dir: Path) -> int:
    """Exporta tool_usage para CSV.

    Args:
        execution_id: ID da execução.
        output_dir: Diretório de saída.

    Returns:
        Número de linhas exportadas.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, execution_id, session_id, agent_id, tool_name,
                   arguments_json, result_summary, success, error_message,
                   started_at, finished_at, duration_ms, task_name
            FROM tool_usage
            WHERE execution_id = %s
            ORDER BY started_at ASC
            """,
            (execution_id,),
        ).fetchall()
    return _write_csv(
        [_serialize_row(dict(r)) for r in rows],
        output_dir / "tool_usage.csv",
    )


def export_token_usage(execution_id: str, output_dir: Path) -> int:
    """Exporta token_usage para CSV.

    Args:
        execution_id: ID da execução.
        output_dir: Diretório de saída.

    Returns:
        Número de linhas exportadas.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, execution_id, session_id, agent_id, task_name,
                   llm_provider, llm_model, prompt_tokens, completion_tokens,
                   total_tokens, estimated_cost_usd, latency_ms, timestamp,
                   context_window_used, context_window_max, was_compressed
            FROM token_usage
            WHERE execution_id = %s
            ORDER BY timestamp ASC
            """,
            (execution_id,),
        ).fetchall()
    return _write_csv(
        [_serialize_row(dict(r)) for r in rows],
        output_dir / "token_usage.csv",
    )


def export_hardware_snapshots(execution_id: str, output_dir: Path) -> int:
    """Exporta hardware_snapshots para CSV.

    Args:
        execution_id: ID da execução.
        output_dir: Diretório de saída.

    Returns:
        Número de linhas exportadas.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, execution_id, task_name, cpu_temp_c, cpu_usage_pct,
                   mem_total_mb, mem_available_mb, mem_usage_pct, is_throttled,
                   disk_free_gb, active_containers, timestamp
            FROM hardware_snapshots
            WHERE execution_id = %s
            ORDER BY timestamp ASC
            """,
            (execution_id,),
        ).fetchall()
    return _write_csv(
        [_serialize_row(dict(r)) for r in rows],
        output_dir / "hardware_snapshots.csv",
    )


def export_subtask_metrics(execution_id: str, output_dir: Path) -> int:
    """Exporta subtask_metrics para CSV.

    Args:
        execution_id: ID da execução.
        output_dir: Diretório de saída.

    Returns:
        Número de linhas exportadas.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, execution_id, task_name, agent_id, status,
                   created_at, started_at, finished_at, duration_total_ms,
                   duration_active_ms, waiting_time_ms, cpu_usage_avg,
                   mem_usage_peak_mb, temp_delta_c, total_tokens,
                   total_cost_usd, llm_calls_count, tools_used_count,
                   retry_count, error_type
            FROM subtask_metrics
            WHERE execution_id = %s
            ORDER BY created_at ASC
            """,
            (execution_id,),
        ).fetchall()
    return _write_csv(
        [_serialize_row(dict(r)) for r in rows],
        output_dir / "subtask_metrics.csv",
    )


def export_derived_metrics(execution_id: str, output_dir: Path) -> None:
    """Exporta métricas derivadas para CSV.

    Args:
        execution_id: ID da execução.
        output_dir: Diretório de saída.
    """
    from src.telemetry import get_telemetry

    tel = get_telemetry()
    metrics = tel.get_derived_metrics(execution_id)
    token_summary = tel.get_token_summary(execution_id)
    tool_summary = tel.get_tool_summary(execution_id)
    hw_peaks = tel.get_hardware_peaks(execution_id)

    # Métricas derivadas — flat CSV
    derived_rows = [{"metric": k, "value": v} for k, v in metrics.items()]
    _write_csv(derived_rows, output_dir / "derived_metrics.csv")

    # Token summary por provedor/modelo
    _write_csv(
        [_serialize_row(r) for r in token_summary.get("by_provider_model", [])],
        output_dir / "token_summary.csv",
    )

    # Tool summary por ferramenta
    _write_csv(
        [_serialize_row(r) for r in tool_summary.get("by_tool", [])],
        output_dir / "tool_summary.csv",
    )

    # Hardware peaks — flat CSV
    hw_rows = [{"metric": k, "value": v} for k, v in hw_peaks.items()]
    _write_csv(hw_rows, output_dir / "hardware_peaks.csv")


def list_recent_executions(limit: int = 20) -> None:
    """Lista as execuções mais recentes com IDs e status."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, LEFT(prompt, 60) AS prompt_preview, status,
                   started_at, duration_seconds, total_subtasks, succeeded, failed
            FROM execution_history
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()

    if not rows:
        print("Nenhuma execução encontrada no banco.")
        return

    print(f"\n{'ID':<34} {'Status':<10} {'Subtarefas':<12} {'Duração(s)':<12} Prompt")
    print("-" * 100)
    for r in rows:
        dur = f"{r['duration_seconds']:.1f}" if r.get("duration_seconds") else "N/A"
        sub = f"{r.get('succeeded', 0)}/{r.get('total_subtasks', 0)}"
        print(f"{r['id']:<34} {r['status']:<10} {sub:<12} {dur:<12} {r.get('prompt_preview', '')!r}")


def export_all(execution_id: str, output_dir: Path) -> None:
    """Exporta todas as tabelas de telemetria para CSV.

    Args:
        execution_id: ID da execução.
        output_dir: Diretório de saída base (será criado se não existir).
    """
    target = output_dir / execution_id
    target.mkdir(parents=True, exist_ok=True)

    print(f"\n📊 Exportando métricas para: {target}")
    print("-" * 60)

    n_events = export_agent_events(execution_id, target)
    n_tools = export_tool_usage(execution_id, target)
    n_tokens = export_token_usage(execution_id, target)
    n_hw = export_hardware_snapshots(execution_id, target)
    n_subtasks = export_subtask_metrics(execution_id, target)
    export_derived_metrics(execution_id, target)

    print("\n✅ Exportação concluída:")
    print(f"   agent_events:       {n_events:>5} linhas")
    print(f"   tool_usage:         {n_tools:>5} linhas")
    print(f"   token_usage:        {n_tokens:>5} linhas")
    print(f"   hardware_snapshots: {n_hw:>5} linhas")
    print(f"   subtask_metrics:    {n_subtasks:>5} linhas")
    print(f"   derived_metrics:    exportadas")
    print(f"\n   Diretório: {target.resolve()}")


def main() -> None:
    """Ponto de entrada principal do script."""
    parser = argparse.ArgumentParser(
        description="Exporta métricas de telemetria do GeminiClaw para CSV."
    )
    parser.add_argument(
        "execution_id",
        nargs="?",
        help="ID da execução a exportar.",
    )
    parser.add_argument(
        "--output-dir",
        default="./metrics",
        help="Diretório de saída para os CSVs (padrão: ./metrics).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Lista execuções recentes.",
    )
    args = parser.parse_args()

    # Inicializa o pool PostgreSQL
    pool = get_pool()
    pool.open()

    try:
        if args.list:
            list_recent_executions()
        elif args.execution_id:
            export_all(args.execution_id, Path(args.output_dir))
        else:
            parser.print_help()
            print("\nDica: use --list para ver execuções disponíveis.")
    finally:
        pool.close()


if __name__ == "__main__":
    main()
