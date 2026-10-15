"""Contabilidade de tokens, custo e latência de toda chamada LLM.

Antes, só o laço ReAct (``agent_loop``) gravava ``token_usage``; triagem, sumarização de contexto,
recuperação e as chamadas do Validator ficavam de fora, subestimando tokens e custo no
benchmark. ``record_llm_call`` é o ponto único de registro: estas chamadas o usam.

A execução corrente vem do ``AgentContext`` (dentro do runtime em processo) ou, fora dele
(orquestrador, Validator), de ``bind_execution``, chamado pelo orquestrador no início da execução.
"""

from __future__ import annotations

import contextvars
from typing import Optional

from src.llm.allocation import record_call_version
from src.llm.base import LLMProvider, LLMResponse
from src.llm.pricing import estimate_cost
from src.llm.versions import normalize_version
from src.logger import get_logger
from src.observability.telemetry import get_telemetry
from src.utils.agent_context import get_agent_context_optional

logger = get_logger(__name__)

_bound: contextvars.ContextVar[Optional[tuple[str, str]]] = contextvars.ContextVar("bound_execution", default=None)


def bind_execution(execution_id: str, session_id: str) -> None:
    """Associa a execução e a sessão mestra ao contexto asyncio corrente (e às tarefas filhas)."""
    _bound.set((execution_id, session_id))


def bound_execution_id() -> str:
    bound = _bound.get()
    return bound[0] if bound else ""


def provider_name(provider: LLMProvider) -> str:
    from src.egress.gate import GatedProvider

    # GatedProvider (v18.5-egress-gate) envolve o provedor real: o nome é o do provedor interno.
    inner = provider.inner if isinstance(provider, GatedProvider) else provider
    return type(inner).__name__.removesuffix("Provider").lower() or "unknown"


def record_llm_call(
    provider: LLMProvider,
    response: LLMResponse,
    latency_ms: int,
    agent_id: str,
    task_name: Optional[str] = None,
    funcao: Optional[str] = None,
) -> None:
    """Grava tokens, custo estimado e latência de uma chamada LLM em ``token_usage``.

    ``funcao`` (ex.: ``revisao_subtarefa``) distingue o que o papel fazia na chamada. ``token_usage`` não tem coluna
    para isso (sem mudança de schema, ADR 020): a função vai no log estruturado da chamada.
    """
    ctx = get_agent_context_optional()
    bound = _bound.get()
    if ctx is not None:
        execution_id, session_id = ctx.execution_id or ctx.session_id, ctx.session_id
        task_name = task_name or ctx.task_name
    elif bound:
        execution_id, session_id = bound
    else:
        execution_id = session_id = "unknown"

    usage = response.usage or {}
    prompt_tokens = usage.get("prompt_tokens", 0) or 0
    completion_tokens = usage.get("completion_tokens", 0) or 0
    name, model = provider_name(provider), provider.model_name or "unknown"
    # v18.5-model-catalog-locality — versão efetiva servida (rastreia troca de versão na sessão).
    versao = record_call_version(name, model, normalize_version(getattr(response, "versao_efetiva", None)))
    if funcao:
        logger.debug("Chamada LLM", extra={"agent_id": agent_id, "funcao": funcao, "task_name": task_name})
    get_telemetry().record_token_usage(
        execution_id=execution_id,
        session_id=session_id,
        agent_id=agent_id,
        llm_provider=name,
        llm_model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        task_name=task_name,
        estimated_cost_usd=estimate_cost(
            name, model, prompt_tokens, completion_tokens, usage.get("cached_tokens", 0) or 0
        ),
        versao_efetiva=versao,
    )
