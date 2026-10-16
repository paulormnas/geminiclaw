"""Encerramento de uma pesquisa pelo pesquisador (v18.7-background-sessions, design §1.7, item 4).

Grava ``status='closed'``, ``motivo_parada='encerrada_pesquisador'`` e o relatório determinístico
``relatorio_encerramento.md`` (sem chamada a LLM), montado só com o checkpoint e as métricas já gravadas. O Curator não
roda aqui: o encerramento marca ``curator_pendente`` no checkpoint e a consolidação acontece se a pesquisa for
continuada depois (tarefa 5.6; decisão do pesquisador de 2026-10-16).
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from src.knowledge.subtask_states import ST_ABANDONADA, ST_CONCLUIDA
from src.logger import get_logger
from src.session.continuity import (
    CheckpointError,
    read_checkpoint,
    validate_session_id,
    write_checkpoint,
)
from src.session.manager import Session
from src.session.states import UNFINISHED_STATUSES

logger = get_logger(__name__)

REPORT_NAME = "relatorio_encerramento.md"


def _line(text: str) -> str:
    return " ".join(str(text).split())


def render_closing_report(
    session: Session, checkpoint: Any | None, *, when: str, previous: tuple[str, str | None] | None = None
) -> str:
    """Markdown do encerramento: o que foi feito, o que ficou pendente e o consumo. Determinístico e sem LLM.

    Args:
        previous: ``(status, motivo_parada)`` da sessão antes do encerramento (o padrão é o da própria ``session``).
    """
    payload = session.payload or {}
    status_before, reason_before = previous or (session.status, payload.get("motivo_parada"))
    alias = session.alias or session.id
    task = _line(session.resumo or payload.get("prompt") or (checkpoint.prompt_original if checkpoint else ""))[:400]
    lines = [
        f"# Encerramento da pesquisa {alias}",
        "",
        f"- Sessão: `{session.id}`",
        f"- Encerrada pelo pesquisador em: {when}",
        f"- Estado antes do encerramento: `{status_before}` (motivo: `{reason_before or 'n/d'}`)",
        f"- Modo: {payload.get('mode') or (checkpoint.modo if checkpoint else 'n/d')}",
        f"- Tarefa: {task}",
        "",
    ]
    if checkpoint is None:
        lines += ["Sem checkpoint utilizável: nada a resumir além dos dados da sessão.", ""]
        return "\n".join(lines)
    done = [s for s in checkpoint.subtarefas if s.status == ST_CONCLUIDA]
    abandoned = [s for s in checkpoint.subtarefas if s.status == ST_ABANDONADA]
    other = [s for s in checkpoint.subtarefas if s.status not in (ST_CONCLUIDA, ST_ABANDONADA)]
    lines += [f"## Subtarefas ({len(checkpoint.subtarefas)})", ""]
    for title, items in (("Concluídas", done), ("Abandonadas", abandoned), ("Não concluídas", other)):
        lines.append(f"**{title}:** {len(items)}")
        lines += [f"- `{s.task_name}` ({s.agent_id}, {s.status}): {_line(s.resultado_resumo)[:200]}" for s in items]
        lines.append("")
    if checkpoint.hipoteses:
        lines += [f"## Hipóteses ({len(checkpoint.hipoteses)})", ""]
        for h in checkpoint.hipoteses:
            lines.append(f"- `{h.get('id', '')}` — {h.get('status', 'n/d')}")
        lines.append("")
    consumo = checkpoint.consumo or {}
    lines += [
        "## Consumo",
        "",
        f"- Tokens: {consumo.get('tokens', 'n/d')} · minutos: {consumo.get('minutos', 'n/d')} · "
        f"retentativas de conexão: {consumo.get('retentativas_conexao', 'n/d')}",
        "",
        "## Pendências",
        "",
        "- Consolidação do Curator pendente: sim (acontece se a pesquisa for continuada)",
        f"- Sinalizações do Curator pendentes: {checkpoint.sinalizacoes_pendentes}",
        f"- Afirmações pendentes de verificação: {len(checkpoint.afirmacoes_pendentes)}",
        "",
    ]
    metrics = payload.get("operation_metrics")
    if metrics:
        lines += ["## Métricas de operação (já gravadas)", "", f"`{_line(str(metrics))[:600]}`", ""]
    return "\n".join(lines)


def close_by_researcher(
    session_manager: Any, base_dir: Path | str, session: Session, *, now: datetime.datetime | None = None
) -> Path | None:
    """Encerra a pesquisa ``session`` (``suspensa_sem_pesquisador``, ``aguarda_pesquisador``, ``interrompida``...).

    Returns:
        O caminho do relatório, ou ``None`` se a sessão deixou de estar parada (voltou a ``active`` ou fechou).
    """
    when = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    previous = (session.status, (session.payload or {}).get("motivo_parada"))
    session_dir = Path(base_dir) / validate_session_id(session.id)
    checkpoint = None
    try:
        checkpoint, _origin = read_checkpoint(session_dir, expected_session_id=session.id)
    except CheckpointError as exc:
        logger.warning("Encerramento sem checkpoint utilizável", extra={"error": str(exc)[:200]})
    if not session_manager.close_by_researcher(session.id, UNFINISHED_STATUSES):
        return None
    if checkpoint is not None:
        checkpoint.curator_pendente = True  # a consolidação não se perde: a retomada a executa (tarefa 5.6)
        checkpoint.estado = "fechado"
        checkpoint.motivo_parada = "encerrada_pesquisador"
        write_checkpoint(session_dir, checkpoint)
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / REPORT_NAME
    path.write_text(render_closing_report(session, checkpoint, when=when, previous=previous), encoding="utf-8")
    return path
