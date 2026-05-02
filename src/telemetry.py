"""Coletor central de telemetria e métricas do sistema multi-agente.

Registra agent_events, tool_usage, token_usage e hardware_snapshots
no PostgreSQL de forma assíncrona e não-bloqueante.

Pattern: Singleton com buffer interno e flush periódico para
minimizar I/O de banco no Pi 5.

Uso::

    from src.telemetry import get_telemetry

    tel = get_telemetry()
    tel.record_agent_event(
        execution_id="abc123",
        session_id="sess456",
        agent_id="planner",
        event_type="spawn",
        task_name="search_papers",
    )
    await tel.flush()
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from src.logger import get_logger
from src.db import get_connection

logger = get_logger(__name__)

# Tamanho do buffer antes de um flush automático
_BUFFER_SIZE = 50


def _now() -> str:
    """Retorna timestamp ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _AgentEventRow:
    """Linha a ser inserida na tabela agent_events."""

    id: str
    execution_id: str
    session_id: str
    agent_id: str
    event_type: str
    target_agent_id: Optional[str]
    task_name: Optional[str]
    payload_json: Optional[str]
    timestamp: str
    duration_ms: Optional[int]


@dataclass
class _ToolUsageRow:
    """Linha a ser inserida na tabela tool_usage."""

    id: str
    execution_id: str
    session_id: str
    agent_id: str
    tool_name: str
    arguments_json: Optional[str]
    result_summary: Optional[str]
    success: bool
    error_message: Optional[str]
    started_at: str
    finished_at: str
    duration_ms: int
    task_name: Optional[str]


@dataclass
class _TokenUsageRow:
    """Linha a ser inserida na tabela token_usage."""

    id: str
    execution_id: str
    session_id: str
    agent_id: str
    task_name: Optional[str]
    llm_provider: str
    llm_model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: Optional[float]
    latency_ms: int
    timestamp: str
    context_window_used: Optional[int]
    context_window_max: Optional[int]
    was_compressed: bool


@dataclass
class _HardwareSnapshotRow:
    """Linha a ser inserida na tabela hardware_snapshots."""

    id: str
    execution_id: Optional[str]
    task_name: Optional[str]
    cpu_temp_c: Optional[float]
    cpu_usage_pct: Optional[float]
    mem_total_mb: Optional[float]
    mem_available_mb: Optional[float]
    mem_usage_pct: Optional[float]
    is_throttled: Optional[bool]
    disk_free_gb: Optional[float]
    active_containers: Optional[int]
    timestamp: str


@dataclass
class _SubtaskMetricsRow:
    """Linha a ser inserida na tabela subtask_metrics."""

    id: str
    execution_id: str
    task_name: str
    agent_id: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_total_ms: Optional[int] = None
    duration_active_ms: Optional[int] = None
    waiting_time_ms: Optional[int] = None
    cpu_usage_avg: Optional[float] = None
    mem_usage_peak_mb: Optional[float] = None
    temp_delta_c: Optional[float] = None
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    llm_calls_count: int = 0
    tools_used_count: int = 0
    retry_count: int = 0
    error_type: Optional[str] = None


@dataclass
class _Buffer:
    """Buffer em memória para batch inserts."""

    agent_events: list[_AgentEventRow] = field(default_factory=list)
    tool_usage: list[_ToolUsageRow] = field(default_factory=list)
    token_usage: list[_TokenUsageRow] = field(default_factory=list)
    hardware_snapshots: list[_HardwareSnapshotRow] = field(default_factory=list)
    subtask_metrics: list[_SubtaskMetricsRow] = field(default_factory=list)

    def total(self) -> int:
        return (
            len(self.agent_events)
            + len(self.tool_usage)
            + len(self.token_usage)
            + len(self.hardware_snapshots)
            + len(self.subtask_metrics)
        )


class TelemetryCollector:
    """Coletor central de eventos e métricas do sistema multi-agente.

    Responsável por registrar agent_events, tool_usage, token_usage
    e hardware_snapshots no PostgreSQL de forma assíncrona e não-bloqueante.

    Pattern: Singleton com buffer interno e flush periódico para
    minimizar I/O de banco no Pi 5.
    """

    _buffer_size: int = _BUFFER_SIZE

    def __init__(self) -> None:
        self._buffer = _Buffer()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Métodos de registro
    # ------------------------------------------------------------------

    def record_agent_event(
        self,
        execution_id: str,
        session_id: str,
        agent_id: str,
        event_type: str,
        target_agent_id: Optional[str] = None,
        task_name: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Registra um evento de interação entre agentes.

        Args:
            execution_id: ID da execução (FK → execution_history.id).
            session_id: ID da sessão do agente.
            agent_id: Agente que gerou o evento.
            event_type: Tipo do evento (spawn, ipc_send, tool_call, etc.).
            target_agent_id: Agente destinatário, se aplicável.
            task_name: Nome da subtarefa no DAG.
            payload: Dados opcionais do evento (serializados em JSON).
            duration_ms: Duração da operação em milissegundos.
        """
        row = _AgentEventRow(
            id=uuid.uuid4().hex,
            execution_id=execution_id,
            session_id=session_id,
            agent_id=agent_id,
            event_type=event_type,
            target_agent_id=target_agent_id,
            task_name=task_name,
            payload_json=json.dumps(payload) if payload else None,
            timestamp=_now(),
            duration_ms=duration_ms,
        )
        self._buffer.agent_events.append(row)
        logger.debug(
            "Evento de agente registrado no buffer",
            extra={"extra": {"agent_id": agent_id, "event_type": event_type}},
        )
        self._maybe_flush_sync()

    def record_tool_usage(
        self,
        execution_id: str,
        session_id: str,
        agent_id: str,
        tool_name: str,
        started_at: str,
        finished_at: str,
        duration_ms: int,
        success: bool,
        arguments: Optional[dict[str, Any]] = None,
        result_summary: Optional[str] = None,
        error_message: Optional[str] = None,
        task_name: Optional[str] = None,
    ) -> None:
        """Registra o uso de uma skill/ferramenta.

        Args:
            execution_id: ID da execução.
            session_id: ID da sessão do agente.
            agent_id: Agente que invocou a ferramenta.
            tool_name: Nome da skill (quick_search, python_interpreter, etc.).
            started_at: Timestamp de início (ISO 8601).
            finished_at: Timestamp de término (ISO 8601).
            duration_ms: Duração total em milissegundos.
            success: Se a invocação foi bem-sucedida.
            arguments: Argumentos passados (sanitizados).
            result_summary: Resumo do resultado (truncado em 500 chars).
            error_message: Mensagem de erro, se houver.
            task_name: Subtarefa do DAG.
        """
        result_summary = (result_summary or "")[:500] or None
        row = _ToolUsageRow(
            id=uuid.uuid4().hex,
            execution_id=execution_id,
            session_id=session_id,
            agent_id=agent_id,
            tool_name=tool_name,
            arguments_json=json.dumps(arguments) if arguments else None,
            result_summary=result_summary,
            success=success,
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            task_name=task_name,
        )
        self._buffer.tool_usage.append(row)
        logger.debug(
            "Uso de ferramenta registrado no buffer",
            extra={"extra": {"tool": tool_name, "success": success}},
        )
        self._maybe_flush_sync()

    def record_token_usage(
        self,
        execution_id: str,
        session_id: str,
        agent_id: str,
        llm_provider: str,
        llm_model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        task_name: Optional[str] = None,
        estimated_cost_usd: Optional[float] = None,
        context_window_used: Optional[int] = None,
        context_window_max: Optional[int] = None,
        was_compressed: bool = False,
    ) -> None:
        """Registra o consumo de tokens por chamada LLM.

        Args:
            execution_id: ID da execução.
            session_id: ID da sessão do agente.
            agent_id: Agente que fez a chamada LLM.
            llm_provider: Provedor (google | ollama).
            llm_model: Nome do modelo.
            prompt_tokens: Tokens no prompt.
            completion_tokens: Tokens na resposta.
            latency_ms: Latência da chamada em milissegundos.
            task_name: Subtarefa do DAG.
            estimated_cost_usd: Estimativa de custo (apenas cloud).
            context_window_used: Tokens usados do contexto.
            context_window_max: Contexto máximo configurado.
            was_compressed: Se o histórico foi comprimido antes da chamada.
        """
        row = _TokenUsageRow(
            id=uuid.uuid4().hex,
            execution_id=execution_id,
            session_id=session_id,
            agent_id=agent_id,
            task_name=task_name,
            llm_provider=llm_provider,
            llm_model=llm_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
            latency_ms=latency_ms,
            timestamp=_now(),
            context_window_used=context_window_used,
            context_window_max=context_window_max,
            was_compressed=was_compressed,
        )
        self._buffer.token_usage.append(row)
        logger.debug(
            "Token usage registrado no buffer",
            extra={
                "extra": {
                    "provider": llm_provider,
                    "model": llm_model,
                    "total_tokens": row.total_tokens,
                }
            },
        )
        self._maybe_flush_sync()

    def record_hardware_snapshot(
        self,
        timestamp: Optional[str] = None,
        execution_id: Optional[str] = None,
        task_name: Optional[str] = None,
        cpu_temp_c: Optional[float] = None,
        cpu_usage_pct: Optional[float] = None,
        mem_total_mb: Optional[float] = None,
        mem_available_mb: Optional[float] = None,
        mem_usage_pct: Optional[float] = None,
        is_throttled: Optional[bool] = None,
        disk_free_gb: Optional[float] = None,
        active_containers: Optional[int] = None,
    ) -> None:
        """Registra um snapshot do estado do hardware.

        Args:
            timestamp: Timestamp da coleta (padrão: agora).
            execution_id: ID da execução associada (ou None para coleta periódica).
            task_name: Subtarefa associada.
            cpu_temp_c: Temperatura da CPU em °C.
            cpu_usage_pct: Percentual de uso da CPU.
            mem_total_mb: Memória total em MB.
            mem_available_mb: Memória disponível em MB.
            mem_usage_pct: Percentual de uso de memória.
            is_throttled: Se há thermal throttling ativo.
            disk_free_gb: Espaço livre em disco em GB.
            active_containers: Número de containers Docker ativos.
        """
        row = _HardwareSnapshotRow(
            id=uuid.uuid4().hex,
            execution_id=execution_id,
            task_name=task_name,
            cpu_temp_c=cpu_temp_c,
            cpu_usage_pct=cpu_usage_pct,
            mem_total_mb=mem_total_mb,
            mem_available_mb=mem_available_mb,
            mem_usage_pct=mem_usage_pct,
            is_throttled=is_throttled,
            disk_free_gb=disk_free_gb,
            active_containers=active_containers,
            timestamp=timestamp or _now(),
        )
        self._buffer.hardware_snapshots.append(row)
        logger.debug(
            "Hardware snapshot registrado no buffer",
            extra={"extra": {"cpu_temp_c": cpu_temp_c, "mem_usage_pct": mem_usage_pct}},
        )
        self._maybe_flush_sync()

    def record_subtask_metrics(
        self,
        subtask_id: str,
        execution_id: str,
        task_name: str,
        agent_id: str,
        status: str,
        created_at: str,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        duration_total_ms: Optional[int] = None,
        duration_active_ms: Optional[int] = None,
        waiting_time_ms: Optional[int] = None,
        cpu_usage_avg: Optional[float] = None,
        mem_usage_peak_mb: Optional[float] = None,
        temp_delta_c: Optional[float] = None,
        total_tokens: int = 0,
        total_cost_usd: float = 0.0,
        llm_calls_count: int = 0,
        tools_used_count: int = 0,
        retry_count: int = 0,
        error_type: Optional[str] = None,
    ) -> None:
        """Registra métricas agregadas de uma subtarefa.

        Args:
            subtask_id: ID único da subtarefa.
            execution_id: ID da execução pai.
            task_name: Nome da subtarefa no DAG.
            agent_id: Agente responsável.
            status: Status final (success|failure|cancelled).
            created_at: Timestamp de criação (ISO).
            started_at: Timestamp de início real.
            finished_at: Timestamp de término.
            duration_total_ms: Duração total no sistema.
            duration_active_ms: Duração em processamento.
            waiting_time_ms: Tempo em fila.
            cpu_usage_avg: Média de uso de CPU.
            mem_usage_peak_mb: Pico de memória em MB.
            temp_delta_c: Variação de temperatura em °C.
            total_tokens: Total de tokens consumidos.
            total_cost_usd: Custo estimado em USD.
            llm_calls_count: Número de chamadas ao LLM.
            tools_used_count: Número de ferramentas invocadas.
            retry_count: Número de retentativas.
            error_type: Tipo de erro, se houver.
        """
        row = _SubtaskMetricsRow(
            id=subtask_id,
            execution_id=execution_id,
            task_name=task_name,
            agent_id=agent_id,
            status=status,
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
            duration_total_ms=duration_total_ms,
            duration_active_ms=duration_active_ms,
            waiting_time_ms=waiting_time_ms,
            cpu_usage_avg=cpu_usage_avg,
            mem_usage_peak_mb=mem_usage_peak_mb,
            temp_delta_c=temp_delta_c,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
            llm_calls_count=llm_calls_count,
            tools_used_count=tools_used_count,
            retry_count=retry_count,
            error_type=error_type,
        )
        self._buffer.subtask_metrics.append(row)
        logger.debug(
            "Métricas de subtarefa registradas no buffer",
            extra={"extra": {"subtask_id": subtask_id, "status": status}},
        )
        self._maybe_flush_sync()

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    def _maybe_flush_sync(self) -> None:
        """Verifica se o buffer atingiu o limite e dispara flush não-bloqueante."""
        if self._buffer.total() >= self._buffer_size:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.flush())
            except RuntimeError:
                # Sem event loop rodando — flush síncrono
                self._flush_sync()

    def _flush_sync(self) -> None:
        """Versão síncrona do flush (para uso fora de event loop)."""
        try:
            asyncio.run(self.flush())
        except Exception as e:
            logger.error("Erro no flush síncrono de telemetria", extra={"error": str(e)})

    async def flush(self) -> None:
        """Força a gravação de todos os eventos do buffer no PostgreSQL.

        É seguro chamar mesmo com buffer vazio. Falhas individuais são
        logadas mas não propagadas para não bloquear o fluxo principal.
        """
        async with self._lock:
            if self._buffer.total() == 0:
                return

            # Faz uma cópia e limpa o buffer atomicamente
            snapshot = self._buffer
            self._buffer = _Buffer()

        await asyncio.to_thread(self._write_snapshot, snapshot)

    def _write_snapshot(self, snapshot: _Buffer) -> None:
        """Grava um snapshot do buffer no banco (executado em thread separada)."""
        try:
            with get_connection() as conn:
                # agent_events
                for row in snapshot.agent_events:
                    conn.execute(
                        """
                        INSERT INTO agent_events
                            (id, execution_id, session_id, agent_id, event_type,
                             target_agent_id, task_name, payload_json, timestamp, duration_ms)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            row.id, row.execution_id, row.session_id, row.agent_id,
                            row.event_type, row.target_agent_id, row.task_name,
                            row.payload_json, row.timestamp, row.duration_ms,
                        ),
                    )

                # tool_usage
                for row in snapshot.tool_usage:
                    conn.execute(
                        """
                        INSERT INTO tool_usage
                            (id, execution_id, session_id, agent_id, tool_name,
                             arguments_json, result_summary, success, error_message,
                             started_at, finished_at, duration_ms, task_name)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            row.id, row.execution_id, row.session_id, row.agent_id,
                            row.tool_name, row.arguments_json, row.result_summary,
                            row.success, row.error_message, row.started_at,
                            row.finished_at, row.duration_ms, row.task_name,
                        ),
                    )

                # token_usage
                for row in snapshot.token_usage:
                    conn.execute(
                        """
                        INSERT INTO token_usage
                            (id, execution_id, session_id, agent_id, task_name,
                             llm_provider, llm_model, prompt_tokens, completion_tokens,
                             total_tokens, estimated_cost_usd, latency_ms, timestamp,
                             context_window_used, context_window_max, was_compressed)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            row.id, row.execution_id, row.session_id, row.agent_id,
                            row.task_name, row.llm_provider, row.llm_model,
                            row.prompt_tokens, row.completion_tokens, row.total_tokens,
                            row.estimated_cost_usd, row.latency_ms, row.timestamp,
                            row.context_window_used, row.context_window_max, row.was_compressed,
                        ),
                    )

                # hardware_snapshots
                for row in snapshot.hardware_snapshots:
                    conn.execute(
                        """
                        INSERT INTO hardware_snapshots
                            (id, execution_id, task_name, cpu_temp_c, cpu_usage_pct,
                             mem_total_mb, mem_available_mb, mem_usage_pct, is_throttled,
                             disk_free_gb, active_containers, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            row.id, row.execution_id, row.task_name, row.cpu_temp_c,
                            row.cpu_usage_pct, row.mem_total_mb, row.mem_available_mb,
                            row.mem_usage_pct, row.is_throttled, row.disk_free_gb,
                            row.active_containers, row.timestamp,
                        ),
                    )

                # subtask_metrics
                for row in snapshot.subtask_metrics:
                    conn.execute(
                        """
                        INSERT INTO subtask_metrics
                            (id, execution_id, task_name, agent_id, status,
                             created_at, started_at, finished_at, duration_total_ms,
                             duration_active_ms, waiting_time_ms, cpu_usage_avg,
                             mem_usage_peak_mb, temp_delta_c, total_tokens,
                             total_cost_usd, llm_calls_count, tools_used_count,
                             retry_count, error_type)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            status = EXCLUDED.status,
                            started_at = COALESCE(subtask_metrics.started_at, EXCLUDED.started_at),
                            finished_at = EXCLUDED.finished_at,
                            duration_total_ms = EXCLUDED.duration_total_ms,
                            duration_active_ms = EXCLUDED.duration_active_ms,
                            waiting_time_ms = EXCLUDED.waiting_time_ms,
                            cpu_usage_avg = EXCLUDED.cpu_usage_avg,
                            mem_usage_peak_mb = EXCLUDED.mem_usage_peak_mb,
                            temp_delta_c = EXCLUDED.temp_delta_c,
                            total_tokens = EXCLUDED.total_tokens,
                            total_cost_usd = EXCLUDED.total_cost_usd,
                            llm_calls_count = EXCLUDED.llm_calls_count,
                            tools_used_count = EXCLUDED.tools_used_count,
                            retry_count = EXCLUDED.retry_count,
                            error_type = EXCLUDED.error_type
                        """,
                        (
                            row.id, row.execution_id, row.task_name, row.agent_id,
                            row.status, row.created_at, row.started_at, row.finished_at,
                            row.duration_total_ms, row.duration_active_ms,
                            row.waiting_time_ms, row.cpu_usage_avg, row.mem_usage_peak_mb,
                            row.temp_delta_c, row.total_tokens, row.total_cost_usd,
                            row.llm_calls_count, row.tools_used_count, row.retry_count,
                            row.error_type,
                        ),
                    )

            total = (
                len(snapshot.agent_events) + len(snapshot.tool_usage)
                + len(snapshot.token_usage) + len(snapshot.hardware_snapshots)
                + len(snapshot.subtask_metrics)
            )
            logger.info(
                "Telemetria gravada no PostgreSQL",
                extra={
                    "extra": {
                        "agent_events": len(snapshot.agent_events),
                        "tool_usage": len(snapshot.tool_usage),
                        "token_usage": len(snapshot.token_usage),
                        "hardware_snapshots": len(snapshot.hardware_snapshots),
                        "subtask_metrics": len(snapshot.subtask_metrics),
                        "total": total,
                    }
                },
            )
        except Exception as e:
            logger.error(
                "Erro ao gravar telemetria no banco",
                extra={"extra": {"error": str(e)}},
            )

    # ------------------------------------------------------------------
    # Queries de análise
    # ------------------------------------------------------------------

    def get_execution_timeline(self, execution_id: str) -> list[dict[str, Any]]:
        """Retorna a timeline completa de eventos de uma execução.

        Args:
            execution_id: ID da execução a consultar.

        Returns:
            Lista de eventos ordenados por timestamp.
        """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT agent_id, event_type, task_name, timestamp, duration_ms, payload_json
                    FROM agent_events
                    WHERE execution_id = %s
                    ORDER BY timestamp ASC
                    """,
                    (execution_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Erro ao consultar timeline", extra={"error": str(e)})
            return []

    def get_token_summary(self, execution_id: str) -> dict[str, Any]:
        """Retorna um resumo do consumo de tokens para uma execução.

        Args:
            execution_id: ID da execução a consultar.

        Returns:
            Dicionário com totais por provedor e modelo.
        """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        llm_provider,
                        llm_model,
                        SUM(prompt_tokens)     AS total_prompt_tokens,
                        SUM(completion_tokens) AS total_completion_tokens,
                        SUM(total_tokens)      AS total_tokens,
                        SUM(estimated_cost_usd) AS total_cost_usd,
                        AVG(latency_ms)        AS avg_latency_ms,
                        COUNT(*)               AS calls
                    FROM token_usage
                    WHERE execution_id = %s
                    GROUP BY llm_provider, llm_model
                    ORDER BY total_tokens DESC
                    """,
                    (execution_id,),
                ).fetchall()
            return {"by_provider_model": [dict(r) for r in rows]}
        except Exception as e:
            logger.error("Erro ao consultar token summary", extra={"error": str(e)})
            return {}

    def get_tool_summary(self, execution_id: str) -> dict[str, Any]:
        """Retorna um resumo do uso de ferramentas para uma execução.

        Args:
            execution_id: ID da execução a consultar.

        Returns:
            Dicionário com contagem, taxa de sucesso e duração média por ferramenta.
        """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        tool_name,
                        COUNT(*)                                AS total_calls,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successful,
                        AVG(duration_ms)                        AS avg_duration_ms,
                        MAX(duration_ms)                        AS max_duration_ms
                    FROM tool_usage
                    WHERE execution_id = %s
                    GROUP BY tool_name
                    ORDER BY total_calls DESC
                    """,
                    (execution_id,),
                ).fetchall()
            return {"by_tool": [dict(r) for r in rows]}
        except Exception as e:
            logger.error("Erro ao consultar tool summary", extra={"error": str(e)})
            return {}

    def get_hardware_peaks(self, execution_id: str) -> dict[str, Any]:
        """Retorna os picos de hardware durante uma execução.

        Args:
            execution_id: ID da execução a consultar.

        Returns:
            Dicionário com picos de temperatura, CPU e memória.
        """
        try:
            with get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT
                        MAX(cpu_temp_c)     AS max_temp_c,
                        MAX(cpu_usage_pct)  AS max_cpu_pct,
                        MAX(mem_usage_pct)  AS max_mem_pct,
                        MIN(mem_available_mb) AS min_mem_available_mb,
                        SUM(CASE WHEN is_throttled THEN 1 ELSE 0 END) AS throttle_incidents,
                        COUNT(*)            AS snapshot_count
                    FROM hardware_snapshots
                    WHERE execution_id = %s
                    """,
                    (execution_id,),
                ).fetchone()
            return dict(row) if row else {}
        except Exception as e:
            logger.error("Erro ao consultar picos de hardware", extra={"error": str(e)})
            return {}

    def get_derived_metrics(self, execution_id: str) -> dict[str, Any]:
        """Calcula métricas derivadas de eficiência e confiabilidade.

        Métricas calculadas:
        1. Taxa de sucesso global (agent_events)
        2. Retry Rate
        3. Latência de inferência média
        4. Taxa de utilização de contexto
        5. Memory Pressure Score

        Args:
            execution_id: ID da execução.

        Returns:
            Dicionário com métricas derivadas.
        """
        metrics: dict[str, Any] = {}

        try:
            with get_connection() as conn:
                # 1. Taxa de sucesso de subtarefas
                counts = conn.execute(
                    """
                    SELECT
                        SUM(CASE WHEN event_type = 'subtask_end' THEN 1 ELSE 0 END)    AS total_subtasks,
                        SUM(CASE WHEN event_type = 'replan_triggered' THEN 1 ELSE 0 END) AS replans
                    FROM agent_events
                    WHERE execution_id = %s
                    """,
                    (execution_id,),
                ).fetchone()
                if counts:
                    metrics["total_subtasks"] = counts["total_subtasks"] or 0
                    metrics["replans"] = counts["replans"] or 0

                # 2. Latência média de inferência
                lat = conn.execute(
                    """
                    SELECT AVG(latency_ms) AS avg_latency_ms, MAX(latency_ms) AS max_latency_ms
                    FROM token_usage
                    WHERE execution_id = %s
                    """,
                    (execution_id,),
                ).fetchone()
                if lat:
                    metrics["avg_inference_latency_ms"] = lat["avg_latency_ms"]
                    metrics["max_inference_latency_ms"] = lat["max_latency_ms"]

                # 3. Taxa de utilização de contexto
                ctx = conn.execute(
                    """
                    SELECT
                        AVG(CASE
                            WHEN context_window_max > 0
                            THEN CAST(context_window_used AS FLOAT) / context_window_max
                            ELSE NULL
                        END) AS avg_context_utilization
                    FROM token_usage
                    WHERE execution_id = %s AND context_window_max IS NOT NULL
                    """,
                    (execution_id,),
                ).fetchone()
                if ctx:
                    metrics["avg_context_utilization"] = ctx["avg_context_utilization"]

                # 4. Memory Pressure Score (pico)
                mem = conn.execute(
                    """
                    SELECT MAX(mem_usage_pct) AS peak_mem_pressure_pct
                    FROM hardware_snapshots
                    WHERE execution_id = %s
                    """,
                    (execution_id,),
                ).fetchone()
                if mem:
                    metrics["peak_mem_pressure_pct"] = mem["peak_mem_pressure_pct"]

                # 5. Throttling incidents
                hw = conn.execute(
                    """
                    SELECT
                        MAX(cpu_temp_c) AS max_temp_c,
                        SUM(CASE WHEN is_throttled THEN 1 ELSE 0 END) AS throttle_incidents
                    FROM hardware_snapshots
                    WHERE execution_id = %s
                    """,
                    (execution_id,),
                ).fetchone()
                if hw:
                    metrics["max_cpu_temp_c"] = hw["max_temp_c"]
                    metrics["throttle_incidents"] = hw["throttle_incidents"] or 0

        except Exception as e:
            logger.error("Erro ao calcular métricas derivadas", extra={"error": str(e)})

        return metrics

    def get_subtask_metrics(self, execution_id: str) -> list[dict[str, Any]]:
        """Retorna as métricas detalhadas de cada subtarefa de uma execução.

        Args:
            execution_id: ID da execução a consultar.

        Returns:
            Lista de métricas por subtarefa.
        """
        try:
            with get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT 
                        task_name, agent_id, status, duration_total_ms,
                        duration_active_ms, waiting_time_ms, total_tokens,
                        total_cost_usd, retry_count, error_type, started_at
                    FROM subtask_metrics
                    WHERE execution_id = %s
                    ORDER BY created_at ASC
                    """,
                    (execution_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Erro ao consultar subtask metrics", extra={"error": str(e)})
            return []


# ------------------------------------------------------------------
# Singleton global
# ------------------------------------------------------------------

_collector: TelemetryCollector | None = None


def get_telemetry() -> TelemetryCollector:
    """Retorna o singleton do TelemetryCollector.

    Returns:
        Instância global do TelemetryCollector.
    """
    global _collector
    if _collector is None:
        _collector = TelemetryCollector()
    return _collector
