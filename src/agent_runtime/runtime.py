"""``AgentRuntime`` — execução supervisionada de agentes em processo (Roadmap V16).

Executa cada agente com uma chamada direta a ``run_agent_loop`` dentro do processo do
orquestrador, isolada em uma ``asyncio.Task`` dedicada (contexto por tarefa via
``contextvars`` — ver ``src/agent_runtime/context.py``), supervisionada por
timeout (``AGENT_TIMEOUT_SECONDS``) e regulada por ``ResourceGuard`` (limite de agentes
simultâneos e espera por saúde do sistema).

Uma falha de agente (exceção não tratada ou timeout) nunca deve derrubar o
orquestrador: é sempre traduzida em um ``AgentResult`` com status
``"error"``/``"timeout"``, exceto ``asyncio.CancelledError`` (cancelamento
explícito da sessão), que é propagada.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.agent_runtime.context import AgentContext, bind_agent_context
from src.agent_runtime.definitions import get_agent_definition
from src.agent_runtime.resources import ResourceGuard
from src.config import AGENT_TIMEOUT_SECONDS, LLM_PROVIDER
from src.llm.agent_loop import run_agent_loop
from src.logger import get_logger
from src.model_config import get_role_model_config
from src.model_router import ModelRouter

if TYPE_CHECKING:  # evita import circular em tempo de carregamento do módulo
    from src.orchestrator import AgentResult, AgentTask

logger = get_logger(__name__)


class AgentRuntime:
    """Executa uma ``AgentTask`` em processo, com supervisão e isolamento de falhas."""

    def __init__(self, guard: ResourceGuard | None = None) -> None:
        """Cria o runtime.

        Args:
            guard: Regulador de recursos; se omitido, cria um com os limites da configuração.
        """
        self._guard = guard or ResourceGuard()

    @staticmethod
    def _provider_name(agent_id: str) -> str:
        """Provedor configurado para o papel (cai no provedor global para papéis sem configuração)."""
        try:
            return get_role_model_config(agent_id).provider
        except ValueError:
            return LLM_PROVIDER

    async def run(self, task: "AgentTask", ctx: AgentContext) -> "AgentResult":
        """Executa a tarefa do agente descrito por ``task`` no contexto ``ctx``.

        Args:
            task: Definição da subtarefa a executar (``src.orchestrator.AgentTask``).
            ctx: Contexto por tarefa (sessão, papel, diretório de output, modelo).

        Returns:
            ``AgentResult`` com ``status`` em ``{"success", "error", "timeout"}``.
            Nunca levanta exceção, exceto ``asyncio.CancelledError``.
        """
        # Import tardio: src.orchestrator importa este módulo, então um import
        # no topo do arquivo criaria um ciclo de import.
        from src.orchestrator import AgentResult

        try:
            # A vaga é reservada antes do timeout começar a contar: esperar a vez não
            # consome o orçamento de tempo do agente.
            async with self._guard.slot(self._provider_name(ctx.agent_id)):
                agent_task: asyncio.Task[str] = asyncio.create_task(
                    self._execute(task, ctx), name=f"agent-run:{ctx.agent_id}:{ctx.agent_session_id}"
                )
                if AGENT_TIMEOUT_SECONDS is not None:
                    text = await asyncio.wait_for(agent_task, timeout=AGENT_TIMEOUT_SECONDS)
                else:
                    text = await agent_task
        except TimeoutError as exc:  # asyncio.TimeoutError é alias de TimeoutError desde 3.11
            logger.warning(
                "Agente em processo excedeu timeout",
                extra={
                    "agent_id": ctx.agent_id,
                    "session_id": ctx.agent_session_id,
                    "timeout": AGENT_TIMEOUT_SECONDS,
                },
            )
            return AgentResult(
                agent_id=ctx.agent_id,
                session_id=ctx.agent_session_id,
                status="timeout",
                response={},
                error=str(exc) or f"Agente excedeu timeout de {AGENT_TIMEOUT_SECONDS}s.",
            )
        except asyncio.CancelledError:
            # Cancelamento explícito da sessão (não é falha do agente) — propaga.
            raise
        except Exception as exc:  # noqa: BLE001 — isolamento de falha é intencional (design §2)
            logger.error(
                "Erro ao executar agente em processo",
                extra={
                    "agent_id": ctx.agent_id,
                    "session_id": ctx.agent_session_id,
                    "error": str(exc),
                },
            )
            return AgentResult(
                agent_id=ctx.agent_id,
                session_id=ctx.agent_session_id,
                status="error",
                response={},
                error=str(exc),
            )

        return AgentResult(
            agent_id=ctx.agent_id,
            session_id=ctx.agent_session_id,
            status="success",
            response={"text": text},
        )

    async def _execute(self, task: "AgentTask", ctx: AgentContext) -> str:
        """Corrotina isolada (roda em sua própria ``Task``) que executa o agente.

        Vincula ``ctx`` ao ``contextvars`` desta ``Task`` (isolando-a de outras
        tarefas concorrentes), resolve a definição do papel e o provedor via
        ``ModelRouter``, e delega a ``run_agent_loop``.

        Args:
            task: Definição da subtarefa.
            ctx: Contexto por tarefa a vincular.

        Returns:
            Texto de resposta final do agente.
        """
        bind_agent_context(ctx)

        definition = get_agent_definition(task.agent_id)
        # ctx.model já resolve task.preferred_model (Planner) com fallback ao padrão
        # do papel — equivalente ao LLM_MODEL propagado por env var no modo container.
        provider = ModelRouter.get_provider(definition.role, model=ctx.model)

        return await run_agent_loop(
            prompt=task.prompt,
            instruction=definition.instruction(),
            tools=definition.tools,
            before_callback=definition.before_callback,
            after_callback=definition.after_callback,
            provider=provider,
        )
