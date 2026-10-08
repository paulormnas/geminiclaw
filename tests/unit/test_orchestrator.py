"""Testes unitários do Orquestrador com o runtime de agentes em processo (ADR 014).

O ``AgentRuntime`` é simulado: nenhum LLM, ferramenta ou container real é acionado. O runtime
real nunca levanta exceção (traduz falhas e timeouts em ``AgentResult``), então os cenários de
falha usam resultados com ``status`` ``error``/``timeout``.
"""

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from src.orchestrator import (
    AgentResult,
    AgentTask,
    Orchestrator,
    OrchestratorResult,
)
from src.session import Session


def _make_session(agent_id: str, session_id: str = "sess_123") -> Session:
    """Helper para criar uma Session mock."""
    return Session(
        id=session_id,
        agent_id=agent_id,
        status="active",
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
        payload={},
    )


def _make_agent_result(
    agent_id: str,
    session_id: str,
    status: str = "success",
    response: dict | None = None,
    error: str | None = None,
) -> AgentResult:
    """Helper para criar um AgentResult devolvido pelo runtime simulado."""
    return AgentResult(
        agent_id=agent_id, session_id=session_id, status=status, response=response or {}, error=error
    )


def _create_orchestrator() -> tuple[Orchestrator, MagicMock, MagicMock]:
    """Cria um Orchestrator com o ``AgentRuntime`` e o gerenciador de sessões simulados."""
    mock_session_manager = MagicMock()
    mock_agent_runtime = MagicMock()
    mock_agent_runtime.run = AsyncMock()

    orchestrator = Orchestrator(session_manager=mock_session_manager, agent_runtime=mock_agent_runtime)
    return orchestrator, mock_agent_runtime, mock_session_manager


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorSingleAgent:
    """Testes do fluxo com um único agente."""

    async def test_handle_request_single_agent_success(self) -> None:
        """Fluxo completo com 1 agente retornando sucesso."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.side_effect = [_make_session("orchestrator", "sess_master"), _make_session("agent_1", "sess_1")]
        runtime.run.return_value = _make_agent_result("agent_1", "sess_1", response={"answer": "42"})

        result = await orchestrator.handle_request("Olá", [AgentTask(agent_id="agent_1", prompt="Olá")])

        assert result.total == 1
        assert result.succeeded == 1
        assert result.failed == 0
        assert result.results[0].status == "success"
        assert result.results[0].response == {"answer": "42"}
        assert result.results[0].agent_id == "agent_1"
        assert result.results[0].session_id == "sess_1"

    async def test_handle_request_default_agent(self) -> None:
        """handle_request sem agent_tasks deve usar loop autônomo."""
        orchestrator, _runtime, mock_sm = _create_orchestrator()

        agent_res = AgentResult(agent_id="base", session_id="sess_1", status="success", response={"text": "ok"})
        loop_result = OrchestratorResult(results=[agent_res], total=1, succeeded=1, failed=0)
        mock_sm.create.return_value = _make_session("orchestrator", "sess_master")

        with patch("src.orchestrator.AutonomousLoop") as MockLoop:
            MockLoop.return_value.run = AsyncMock(return_value=loop_result)
            result = await orchestrator.handle_request("Teste sem tasks")

        assert result.total == 1
        assert result.succeeded == 1
        assert result.results[0].agent_id == "base"
        mock_sm.create.assert_called_with("orchestrator", session_id=ANY)
        mock_sm.close.assert_called_with("sess_master")


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorMultipleAgents:
    """Testes com múltiplos agentes."""

    async def test_handle_request_multiple_agents(self) -> None:
        """Execução de 3 agentes, todos com sucesso."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.side_effect = [_make_session("orchestrator", "sess_master")] + [
            _make_session(f"a{i}", f"s{i}") for i in range(3)
        ]
        runtime.run.side_effect = [
            _make_agent_result(f"a{i}", f"s{i}", response={"idx": i}) for i in range(3)
        ]

        tasks = [AgentTask(agent_id=f"a{i}", prompt=f"prompt_{i}") for i in range(3)]
        result = await orchestrator.handle_request("multi", tasks)

        assert result.total == 3
        assert result.succeeded == 3
        assert result.failed == 0
        assert len(result.results) == 3


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorPartialFailure:
    """Testes de falha parcial."""

    async def test_partial_failure_one_agent_fails(self) -> None:
        """1 agente estoura o tempo, os demais retornam sucesso."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.side_effect = [_make_session("orchestrator", "sess_master")] + [
            _make_session(f"a{i}", f"s{i}") for i in range(3)
        ]
        runtime.run.side_effect = [
            _make_agent_result("a0", "s0", response={"ok": True}),
            _make_agent_result("a1", "s1", status="timeout", error="Timeout simulado"),
            _make_agent_result("a2", "s2", response={"ok": True}),
        ]

        tasks = [AgentTask(agent_id=f"a{i}", prompt=f"p{i}") for i in range(3)]
        result = await orchestrator.handle_request("partial", tasks)

        assert result.total == 3
        assert result.succeeded == 2
        assert result.failed == 1
        assert {r.agent_id: r.status for r in result.results}["a1"] == "timeout"

    async def test_partial_failure_error_status(self) -> None:
        """Agente que falha retorna status error com a mensagem preservada."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.side_effect = [_make_session("orchestrator", "sess_master"), _make_session("a1", "s1")]
        runtime.run.return_value = _make_agent_result("a1", "s1", status="error", error="Provider unavailable")

        result = await orchestrator.handle_request("fail", [AgentTask(agent_id="a1", prompt="test")])

        assert result.total == 1
        assert result.failed == 1
        assert result.results[0].status == "error"
        assert "Provider unavailable" in (result.results[0].error or "")


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorResultCounts:
    """Testes dos contadores do resultado."""

    async def test_all_failed(self) -> None:
        """Quando todos os agentes falham."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.side_effect = [_make_session("orchestrator", "sess_master")] + [
            _make_session(f"a{i}", f"s{i}") for i in range(2)
        ]
        runtime.run.side_effect = [
            _make_agent_result(f"a{i}", f"s{i}", status="error", error="falha") for i in range(2)
        ]

        result = await orchestrator.handle_request(
            "all_fail", [AgentTask(agent_id=f"a{i}", prompt="p") for i in range(2)]
        )

        assert result.total == 2
        assert result.succeeded == 0
        assert result.failed == 2

    async def test_agent_timeout_status(self) -> None:
        """Agente que excede o timeout retorna status 'timeout'."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.side_effect = [_make_session("orchestrator", "sess_master"), _make_session("a1", "s1")]
        runtime.run.return_value = _make_agent_result("a1", "s1", status="timeout", error="Timeout!")

        result = await orchestrator.handle_request("timeout", [AgentTask(agent_id="a1", prompt="test")])

        assert result.results[0].status == "timeout"
        assert result.results[0].error is not None


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorCleanup:
    """Testes de cleanup após execução."""

    async def test_sessions_closed_after_execution(self) -> None:
        """Todas as sessões devem ser fechadas ao final, mesmo com sucesso."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.return_value = _make_session("a1", "sess_cleanup")
        runtime.run.return_value = _make_agent_result("a1", "sess_cleanup", response={"ok": True})

        await orchestrator.handle_request("cleanup", [AgentTask(agent_id="a1", prompt="test")])

        # close() é chamado duas vezes: uma para o agente e outra para a master session
        assert mock_sm.close.call_count == 2
        mock_sm.close.assert_any_call("sess_cleanup")

    async def test_cleanup_on_error(self) -> None:
        """A sessão do agente é fechada mesmo quando o agente falha."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.return_value = _make_session("a1", "sess_err")
        runtime.run.return_value = _make_agent_result("a1", "sess_err", status="error", error="falha")

        await orchestrator.handle_request("error_cleanup", [AgentTask(agent_id="a1", prompt="test")])

        assert mock_sm.close.call_count == 2
        mock_sm.close.assert_any_call("sess_err")


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorInProcessRuntime:
    """Testes do runtime de agentes em processo (Roadmap V16/ADR 014).

    Cobre o Requirement "Agentes executam em processo no host" da spec
    ``agent-runtime`` (openspec/changes/v16-in-process-agents/).
    """

    async def test_available_agents_are_role_ids(self) -> None:
        """Os papéis disponíveis são identificadores, não imagens de container."""
        agents = Orchestrator.get_available_agents()
        assert "researcher" in agents and "developer" in agents
        assert all(isinstance(agent, str) and not agent.startswith("geminiclaw-") for agent in agents)

    async def test_orchestrator_has_no_container_dependencies(self) -> None:
        """Cenário: subtarefa sem container de agente — o orquestrador só recebe sessões e runtime."""
        orchestrator = Orchestrator(session_manager=MagicMock())
        assert not hasattr(orchestrator, "runner")
        assert not hasattr(orchestrator, "ipc")
        assert not hasattr(orchestrator, "session_runner")

    async def test_execute_agent_runs_through_the_runtime(self) -> None:
        """Cenário: a subtarefa é executada pelo AgentRuntime com o contexto da tarefa."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.side_effect = [_make_session("orchestrator", "sess_master"), _make_session("a1", "s1")]
        runtime.run.return_value = _make_agent_result("a1", "s1", response={"text": "ok"})

        task = AgentTask(agent_id="a1", prompt="hello")
        result = await orchestrator.handle_request("inprocess test", [task])

        assert result.succeeded == 1
        assert result.results[0].response == {"text": "ok"}
        runtime.run.assert_called_once()

        called_task, called_ctx = runtime.run.call_args[0]
        assert called_task is task
        assert called_ctx.agent_id == "a1"
        assert called_ctx.session_id == "sess_master"
        assert called_ctx.agent_session_id == "s1"

    async def test_execute_agent_error_status(self) -> None:
        """Cenário: Exceção — o orquestrador segue mesmo quando o agente falha."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.side_effect = [_make_session("orchestrator", "sess_master"), _make_session("a1", "s1")]
        runtime.run.return_value = _make_agent_result("a1", "s1", status="error", error="falha simulada")

        result = await orchestrator.handle_request("inprocess fail", [AgentTask(agent_id="a1", prompt="hello")])

        assert result.failed == 1
        assert result.results[0].status == "error"
        assert result.results[0].error == "falha simulada"

    async def test_circuit_breaker_max_agent_runs_per_session(self) -> None:
        """Cenário: Limite de execuções de agentes interrompe novas execuções."""
        from src.config import MAX_AGENT_RUNS_PER_SESSION

        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.return_value = _make_session("a1", "s1")
        orchestrator._session_agent_run_counts["sess_master"] = MAX_AGENT_RUNS_PER_SESSION

        with pytest.raises(RuntimeError, match="Limite de execuções de agente"):
            await orchestrator._execute_agent(AgentTask(agent_id="a1", prompt="hello"), master_session_id="sess_master")

        runtime.run.assert_not_called()

    async def test_ask_researcher_callback_delegates_to_core(self) -> None:
        """Cenário: o callback ask_researcher do AgentContext reutiliza dedup/registro (Spec G5)."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.side_effect = [_make_session("orchestrator", "sess_master"), _make_session("a1", "s1")]

        captured_ctx = {}

        async def fake_run(task, ctx):
            captured_ctx["ctx"] = ctx
            return _make_agent_result("a1", "s1", response={"text": "ok"})

        runtime.run.side_effect = fake_run

        await orchestrator.handle_request("ask_researcher wiring", [AgentTask(agent_id="a1", prompt="hello")])

        ctx = captured_ctx["ctx"]
        assert ctx.ask_researcher is not None

        with patch.object(orchestrator, "_ask_researcher_core", new=AsyncMock(return_value="42")) as mock_core:
            answer = await ctx.ask_researcher("pergunta?", "contexto", "motivo", ["a", "b"])

        assert answer == "42"
        mock_core.assert_called_once()
