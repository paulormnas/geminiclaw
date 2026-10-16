"""Resolução única do contexto da sessão para quem registra eventos fora do laço de agente.

Usada por ``emit_connection_retry`` (``src/llm/retry.py``), pelo registro de cota (``src/llm/quota.py``) e por
``_task_env`` (``src/llm/agent_loop.py``). Ordem de resolução do ``execution_id``: ``AgentContext`` corrente
(``execution_id`` ou, na falta dele, ``session_id``), ``bound_execution_id()`` (planejamento e Validator, vinculado pelo
orquestrador), ``EXECUTION_ID``/``SESSION_ID`` do ambiente e, por fim, vazio.
"""

from __future__ import annotations

import os

from src.utils.agent_context import get_agent_context_optional


def resolve_execution_id() -> str:
    """``execution_id`` da sessão corrente, ou ``""`` se nenhuma fonte o informa."""
    ctx = get_agent_context_optional()
    if ctx is not None:
        return ctx.execution_id or ctx.session_id
    from src.llm.metering import bound_execution_id

    return bound_execution_id() or os.environ.get("EXECUTION_ID") or os.environ.get("SESSION_ID") or ""


def resolve_session_id(execution_id: str = "") -> str:
    """``session_id`` do contexto corrente (o ``execution_id`` quando não há outra fonte)."""
    ctx = get_agent_context_optional()
    if ctx is not None:
        return ctx.session_id
    return os.environ.get("SESSION_ID") or execution_id
