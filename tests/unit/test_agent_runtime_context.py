"""Testes de src/agent_runtime/context.py (Roadmap V16/ADR 014).

Cobre os Requirements "Contexto isolado por tarefa" da spec ``agent-runtime``
(openspec/changes/v16-in-process-agents/specs/agent-runtime/spec.md).
"""

import asyncio
from pathlib import Path

import pytest

from src.agent_runtime.context import (
    AgentContext,
    bind_agent_context,
    get_agent_context,
    get_agent_context_optional,
)


def _make_context(agent_id: str, session_id: str) -> AgentContext:
    return AgentContext(
        session_id=session_id,
        agent_session_id=f"{session_id}-agent",
        agent_id=agent_id,
        mode="assisted",
        output_dir=Path("/tmp/outputs") / session_id,
        model="test-model",
    )


@pytest.mark.unit
class TestGetAgentContextOutsideTask:
    """Cenário: Uso fora de uma tarefa."""

    def test_get_agent_context_raises_when_unset(self) -> None:
        with pytest.raises(RuntimeError, match="fora de uma execução de agente"):
            get_agent_context()

    def test_get_agent_context_optional_returns_none_when_unset(self) -> None:
        assert get_agent_context_optional() is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestConcurrentTaskIsolation:
    """Cenário: Tarefas concorrentes — cada Task asyncio vê apenas o seu próprio contexto."""

    async def test_two_concurrent_tasks_see_their_own_context(self) -> None:
        results: dict[str, str] = {}

        async def _run(agent_id: str, session_id: str) -> None:
            bind_agent_context(_make_context(agent_id, session_id))
            # Cede o controle do event loop para forçar interleaving real entre as tasks
            await asyncio.sleep(0)
            ctx = get_agent_context()
            results[agent_id] = ctx.session_id

        await asyncio.gather(
            asyncio.create_task(_run("developer", "session-a")),
            asyncio.create_task(_run("researcher", "session-b")),
        )

        assert results["developer"] == "session-a"
        assert results["researcher"] == "session-b"

    async def test_context_not_visible_outside_its_task(self) -> None:
        """O contexto vinculado dentro de uma Task não deve vazar para o chamador."""

        async def _bind_only() -> None:
            bind_agent_context(_make_context("developer", "session-x"))

        await asyncio.create_task(_bind_only())

        # A Task terminou; o contextvar do chamador (fora de qualquer Task dedicada
        # a um agente) nunca foi definido.
        assert get_agent_context_optional() is None


@pytest.mark.unit
class TestAgentContextFields:
    """Verifica os campos obrigatórios de AgentContext (Design §1)."""

    def test_context_is_frozen(self) -> None:
        ctx = _make_context("developer", "session-a")
        with pytest.raises(Exception):
            ctx.agent_id = "other"  # type: ignore[misc]

    def test_ask_researcher_defaults_to_none(self) -> None:
        ctx = _make_context("developer", "session-a")
        assert ctx.ask_researcher is None
