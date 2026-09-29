"""Testes de src/agent_runtime/runtime.py (Roadmap V16/ADR 014).

Cobre os Requirements "Falha de agente não derruba a sessão" e "Agentes
executam em processo no host" da spec ``agent-runtime``.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.agent_runtime.context import AgentContext, get_agent_context_optional
from src.agent_runtime.definitions import reset_definitions_cache
from src.agent_runtime.runtime import AgentRuntime


@dataclass
class _FakeAgentTask:
    """Duble mínimo de src.orchestrator.AgentTask (evita import circular no teste)."""

    agent_id: str
    prompt: str
    task_name: str = ""


def _make_context(agent_id: str = "developer", session_id: str = "sess-1") -> AgentContext:
    return AgentContext(
        session_id=session_id,
        agent_session_id=f"{session_id}-agent",
        agent_id=agent_id,
        mode="assisted",
        output_dir=Path("/tmp/geminiclaw-test-outputs") / session_id,
        model="test-model",
    )


@pytest.fixture(autouse=True)
def _reset_defs():
    reset_definitions_cache()
    yield
    reset_definitions_cache()


@pytest.mark.unit
@pytest.mark.asyncio
class TestAgentRuntimeSuccess:
    async def test_run_returns_success_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_run_agent_loop(**kwargs: Any) -> str:
            return "resposta do agente"

        monkeypatch.setattr("src.agent_runtime.runtime.run_agent_loop", fake_run_agent_loop)
        monkeypatch.setattr(
            "src.agent_runtime.runtime.ModelRouter.get_provider", lambda role, model=None: object()
        )

        runtime = AgentRuntime()
        task = _FakeAgentTask(agent_id="developer", prompt="faça algo")
        ctx = _make_context()

        result = await runtime.run(task, ctx)

        assert result.status == "success"
        assert result.response == {"text": "resposta do agente"}
        assert result.agent_id == "developer"
        assert result.session_id == ctx.agent_session_id

    async def test_run_binds_context_isolated_from_caller(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A execução deve rodar isolada em sua própria Task (contextvars)."""
        observed = {}

        async def fake_run_agent_loop(**kwargs: Any) -> str:
            observed["ctx_inside"] = get_agent_context_optional()
            return "ok"

        monkeypatch.setattr("src.agent_runtime.runtime.run_agent_loop", fake_run_agent_loop)
        monkeypatch.setattr(
            "src.agent_runtime.runtime.ModelRouter.get_provider", lambda role, model=None: object()
        )

        runtime = AgentRuntime()
        task = _FakeAgentTask(agent_id="developer", prompt="faça algo")
        ctx = _make_context()

        assert get_agent_context_optional() is None
        await runtime.run(task, ctx)

        assert observed["ctx_inside"] is ctx
        # O contexto não deve vazar de volta para quem chamou runtime.run()
        assert get_agent_context_optional() is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestAgentRuntimeFailureIsolation:
    """Cenário: Exceção — o resultado é AgentResult(status='error')."""

    async def test_unhandled_exception_becomes_error_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def failing_run_agent_loop(**kwargs: Any) -> str:
            raise ValueError("ferramenta explodiu")

        monkeypatch.setattr("src.agent_runtime.runtime.run_agent_loop", failing_run_agent_loop)
        monkeypatch.setattr(
            "src.agent_runtime.runtime.ModelRouter.get_provider", lambda role, model=None: object()
        )

        runtime = AgentRuntime()
        task = _FakeAgentTask(agent_id="developer", prompt="faça algo")
        ctx = _make_context()

        result = await runtime.run(task, ctx)

        assert result.status == "error"
        assert "ferramenta explodiu" in (result.error or "")

    async def test_unknown_role_becomes_error_result(self) -> None:
        """get_agent_definition levanta ValueError dentro da Task — deve virar AgentResult de erro."""
        runtime = AgentRuntime()
        task = _FakeAgentTask(agent_id="papel_desconhecido", prompt="faça algo")
        ctx = _make_context(agent_id="papel_desconhecido")

        result = await runtime.run(task, ctx)

        assert result.status == "error"
        assert "papel_desconhecido" in (result.error or "")


@pytest.mark.unit
@pytest.mark.asyncio
class TestAgentRuntimeTimeout:
    """Cenário: Timeout — o resultado é AgentResult(status='timeout')."""

    async def test_timeout_becomes_timeout_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.agent_runtime.runtime.AGENT_TIMEOUT_SECONDS", 0.05)

        async def slow_run_agent_loop(**kwargs: Any) -> str:
            await asyncio.sleep(1.0)
            return "nunca deveria chegar aqui"

        monkeypatch.setattr("src.agent_runtime.runtime.run_agent_loop", slow_run_agent_loop)
        monkeypatch.setattr(
            "src.agent_runtime.runtime.ModelRouter.get_provider", lambda role, model=None: object()
        )

        runtime = AgentRuntime()
        task = _FakeAgentTask(agent_id="developer", prompt="faça algo devagar")
        ctx = _make_context()

        result = await runtime.run(task, ctx)

        assert result.status == "timeout"

    async def test_no_timeout_when_agent_timeout_seconds_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.agent_runtime.runtime.AGENT_TIMEOUT_SECONDS", None)

        async def fast_run_agent_loop(**kwargs: Any) -> str:
            return "concluído"

        monkeypatch.setattr("src.agent_runtime.runtime.run_agent_loop", fast_run_agent_loop)
        monkeypatch.setattr(
            "src.agent_runtime.runtime.ModelRouter.get_provider", lambda role, model=None: object()
        )

        runtime = AgentRuntime()
        task = _FakeAgentTask(agent_id="developer", prompt="faça algo")
        ctx = _make_context()

        result = await runtime.run(task, ctx)

        assert result.status == "success"


@pytest.mark.unit
@pytest.mark.asyncio
class TestAgentRuntimeCancellation:
    """Cenário: cancelamento explícito da sessão deve propagar, não virar AgentResult."""

    async def test_cancelled_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def cancelled_run_agent_loop(**kwargs: Any) -> str:
            raise asyncio.CancelledError()

        monkeypatch.setattr("src.agent_runtime.runtime.run_agent_loop", cancelled_run_agent_loop)
        monkeypatch.setattr(
            "src.agent_runtime.runtime.ModelRouter.get_provider", lambda role, model=None: object()
        )

        runtime = AgentRuntime()
        task = _FakeAgentTask(agent_id="developer", prompt="faça algo")
        ctx = _make_context()

        with pytest.raises(asyncio.CancelledError):
            await runtime.run(task, ctx)
