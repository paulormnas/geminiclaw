"""Ingestão dos fatos de uma subtarefa concluída pelo laço autônomo (v17-structural-fact-ingestion).

Movida de ``autonomous_loop.py`` sem alterar o comportamento (v18.7-hypothesis-linking, tarefa 0.9; ADR 024 §5):
o laço só decide quando ingerir; aqui se monta o ``SubtaskInput`` e se sinaliza ao Curator o parecer do Validator.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Optional

from src.logger import get_logger

if TYPE_CHECKING:
    from src.agent_runtime.types import AgentResult, AgentTask
    from src.orchestration.orchestrator import Orchestrator

logger = get_logger(__name__)


async def ingest_subtask(
    orchestrator: "Orchestrator",
    task: "AgentTask",
    result: Optional["AgentResult"],
    review: Optional[dict[str, Any]],
    master_session_id: str,
) -> None:
    """Ingere os fatos estruturais de uma subtarefa concluída (v17-structural-fact-ingestion).

    Nunca interrompe a sessão: sem projeto/grafo a ingestão é omitida; falhas do grafo viram
    eventos em ``knowledge_pending.jsonl`` (tratados pelo ``FactIngestor``).
    """
    from src.knowledge.ingestion import FactIngestor, SubtaskInput

    ingestor = orchestrator.get_ingestor(master_session_id)
    if not isinstance(ingestor, FactIngestor) or result is None or not task.task_name:
        return
    flag_from_review(orchestrator, task, review, master_session_id)
    try:
        sub = SubtaskInput(
            task_name=task.task_name,
            subtask_id=task.subtask_id,
            agent_id=task.agent_id,
            task_type=task.task_type,
            hypothesis=task.hypothesis or "",
            scientific_rationale=task.scientific_rationale or "",
            approach=task.approach if isinstance(task.approach, dict) else None,
            agent_status=result.status,
            agent_error_category=getattr(result, "error_category", None),
            review_status=(review or {}).get("status"),
            review_verified=bool((review or {}).get("verified", False)),
            review_outcome=(review or {}).get("outcome"),
            validation_criteria=[c for c in (task.validation_criteria or []) if isinstance(c, str)],
            hypothesis_id=task.hypothesis_id or None,
            papel=task.papel_decidido or None,
            prepara_ids=task.prepara_ids if task.papel_decidido == "preparacao" else None,
        )
        if await asyncio.to_thread(ingestor.subtask, sub):
            # v17-curator-agent: recálculo determinístico do veredito após cada subtarefa ingerida.
            subtarefa_id = sub.subtask_id or f"{master_session_id}:{sub.task_name}"
            await asyncio.to_thread(orchestrator.knowledge_after_subtask, master_session_id, subtarefa_id)
    except Exception as exc:  # noqa: BLE001 - a ingestão nunca derruba a subtarefa
        logger.warning("Falha ao ingerir fatos da subtarefa", extra={"error": type(exc).__name__})


def flag_from_review(
    orchestrator: "Orchestrator", task: "AgentTask", review: Optional[dict[str, Any]], master_session_id: str
) -> None:
    """Sinalização do Validator ao Curator (ADR 012 §2; task 4.1), gravada pelo orquestrador.

    O Validator não tem laço de ferramentas, então a sinalização sai do **parecer estruturado** dele: divergência
    documentada vira ``caminho_relevante`` e reprovação ``falha_relevante``. O texto é um modelo fixo (nenhum
    texto de LLM ou de documento entra na sinalização).
    """
    status = (review or {}).get("status")
    tipo = {"divergent_but_documented": "caminho_relevante", "fail": "falha_relevante"}.get(status or "")
    if tipo is None or not task.task_name:
        return
    try:
        from src.knowledge.curator_flags import record_flag

        record_flag(
            orchestrator.output_manager.base_dir / master_session_id,
            agente="validator",
            subtarefa=task.task_name,
            tipo=tipo,
            texto=f"Parecer do Validator sobre a subtarefa '{task.task_name}': {status}.",
            refs=[task.task_name],
        )
    except Exception as exc:  # noqa: BLE001 - sinalizar nunca derruba a subtarefa
        logger.warning("Sinalização do Validator não gravada", extra={"error": type(exc).__name__})


async def link_preparations(
    orchestrator: "Orchestrator",
    links: dict[str, list[str]],
    executed: dict[str, "AgentTask"],
    master_session_id: str,
) -> None:
    """Liga preparações já concluídas às hipóteses de testes novos (``PREPARA`` incremental, pela fila do ingestor).

    ``executed`` guarda as subtarefas já executadas (``subtask_id`` do ``Experimento``); sem ele vale o identificador
    padrão da sessão. Nunca interrompe a sessão.
    """
    from src.knowledge.ingestion import FactIngestor

    if not links:
        return
    ingestor = orchestrator.get_ingestor(master_session_id)
    if not isinstance(ingestor, FactIngestor):
        return
    for name, hypothesis_ids in links.items():
        before = executed.get(name)
        subtarefa_id = (before.subtask_id if before is not None else None) or f"{master_session_id}:{name}"
        try:
            await asyncio.to_thread(ingestor.link_preparation, subtarefa_id, hypothesis_ids)
        except Exception as exc:  # noqa: BLE001 - a ligação incremental nunca derruba a sessão
            logger.warning("Falha ao ligar a preparação às hipóteses", extra={"error": type(exc).__name__})
