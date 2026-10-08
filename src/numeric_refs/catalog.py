"""Catálogo de referências entregue ao Summarizer no lugar do bloco de métricas (design §7.1).

Lista, por subtarefa, as referências ``{{res:<exec_id>/<nome>}}`` prontas para copiar (com valor exato, unidade e
status) e as fontes disponíveis (insumos e URLs consultadas). O Summarizer escreve **referências**, não números.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.numeric_refs.sources import read_search_sources
from src.provenance.errors import ProvenanceUnavailable
from src.provenance.ledger import ExecutionLedger
from src.provenance.store import TIPO_TERMINO

MAX_METRICS_PER_TASK = 40
MAX_SOURCES = 40


def main_executions(ledger: ExecutionLedger, session_id: str) -> dict[str, Any]:
    """``{task_name: termino}``: o último término com sucesso e ``metrics.json`` de cada subtarefa da sessão."""
    chosen: dict[str, Any] = {}
    for record in ledger.store.by_session(session_id):
        if record.tipo != TIPO_TERMINO or record.corpo.get("status") != "sucesso":
            continue
        if any(str(s.get("caminho", "")).endswith("/metrics.json") for s in record.corpo.get("saidas") or []):
            chosen[record.task_name] = record
    return chosen


def build_reference_catalog(
    *,
    session_id: str,
    session_dir: Path,
    ledger: ExecutionLedger,
    metrics_by_task: dict[str, dict[str, Any]],
    graph: Any = None,
    project_id: str | None = None,
    session_ids: list[str] | None = None,
) -> str:
    """Texto do catálogo de referências da sessão."""
    lines = [
        "CATÁLOGO DE REFERÊNCIAS (escreva as referências abaixo, não os números; "
        "números sem referência serão marcados como não verificados):"
    ]
    try:
        executions = main_executions(ledger, session_id)
    except ProvenanceUnavailable as exc:
        executions = {}
        lines.append(
            f"(registro de execuções indisponível: {str(exc)[:120]}; nenhuma referência {{{{res}}}} disponível)"
        )
    if not metrics_by_task:
        lines.append("Nenhum metrics.json encontrado nas subtarefas desta sessão.")
    for task_name, data in sorted(metrics_by_task.items()):
        record = executions.get(task_name)
        status = data.get("validation_status") or data.get("status") or ""
        header = f"- Subtarefa `{task_name}`" + (f" (status: {status})" if status else "")
        lines.append(header)
        if record is None:
            lines.append("  (sem execução registrada com sucesso: não há referência {{res}} para esta subtarefa)")
            continue
        units = data.get("unidades") if isinstance(data.get("unidades"), dict) else {}
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        recorded = record.corpo.get("metricas") or {}
        for name in list(metrics)[:MAX_METRICS_PER_TASK]:
            if name not in recorded:
                continue
            unit = units.get(name)
            suffix = f" {unit}" if isinstance(unit, str) and unit else ""
            lines.append(f"  {{{{res:{record.exec_id}/{name}}}}} = {recorded[name]}{suffix}")
        parameters = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
        for name, value in list(parameters.items())[:10]:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                lines.append(f"  {{{{res:{record.exec_id}/param.{name}}}}} = {value}")
        if data.get("divergence_note"):
            lines.append(f"  divergência registrada pelo código: {data['divergence_note']}")
    sources: list[str] = []
    if graph is not None and project_id:
        try:
            for node in graph.find_nodes("Insumo", {"projeto_id": project_id}, limit=MAX_SOURCES):
                sources.append(f"  insumo `{node.id}`: {node.properties.get('titulo', '')}")
        except Exception:  # noqa: BLE001 - o catálogo funciona sem o grafo
            pass
    seen: set[str] = set()
    for entry in read_search_sources(session_dir.parent, session_ids or [session_id]):
        url = str(entry.get("url"))
        if url not in seen and len(sources) < MAX_SOURCES:
            seen.add(url)
            sources.append(f"  url {url}: {entry.get('titulo', '')}")
    if sources:
        lines.append("Fontes disponíveis para {{src:<insumo_ou_url>#<trecho literal com um número>}}:")
        lines.extend(sources)
    return "\n".join(lines)


def report_context_without_numbers(report_data: dict[str, Any]) -> str:
    """JSON do relatório sem a tabela de resultados nem os metadados de execução (o orquestrador os escreve)."""
    trimmed = {k: v for k, v in report_data.items() if k not in ("results", "metadata")}
    return json.dumps(trimmed, ensure_ascii=False, indent=2, default=str)
