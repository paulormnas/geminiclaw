import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, ANY
from dataclasses import dataclass

from src.orchestrator import (
    Orchestrator,
    AgentTask,
    AgentResult,
    OrchestratorResult,
)
from src.session import Session
from src.ipc import Message


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


def _make_response_message(session_id: str, payload: dict) -> Message:
    """Helper para criar uma Message de resposta."""
    return Message(
        type="response",
        session_id=session_id,
        payload=payload,
        timestamp="2025-01-01T00:00:00+00:00",
    )


def _create_orchestrator() -> tuple[Orchestrator, MagicMock, MagicMock, MagicMock]:
    """Cria um Orchestrator com dependências mockadas, fixado no modo container.

    Roadmap V16/ADR 014: ``AGENT_RUNTIME`` agora tem padrão ``inprocess``. Este
    helper testa especificamente o caminho legado de container/IPC
    (``_execute_agent_container``), então fixa ``agent_runtime_mode="container"``
    explicitamente — os testes do runtime em processo ficam em
    ``TestOrchestratorInProcessRuntime`` mais abaixo.
    """
    mock_runner = MagicMock()
    mock_runner.spawn = AsyncMock(return_value="container_id_123")
    mock_runner.stop = AsyncMock()
    mock_runner.is_running = AsyncMock(return_value=True)
    mock_runner.get_logs = AsyncMock(return_value="logs")

    mock_ipc = MagicMock()
    mock_ipc._connections = {}

    async def create_socket_side_effect(ipc_id: str) -> None:
        mock_ipc._connections[ipc_id] = MagicMock()

    mock_ipc.create_socket = AsyncMock(side_effect=create_socket_side_effect)
    mock_ipc.wait_for_connection = AsyncMock()
    mock_ipc.send = AsyncMock()
    mock_ipc.close = AsyncMock()

    mock_session_manager = MagicMock()

    orchestrator = Orchestrator(
        runner=mock_runner,
        ipc=mock_ipc,
        session_manager=mock_session_manager,
        agent_runtime_mode="container",
    )

    return orchestrator, mock_runner, mock_ipc, mock_session_manager


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorSingleAgent:
    """Testes do fluxo com um único agente."""

    async def test_handle_request_single_agent_success(self) -> None:
        """Fluxo completo com 1 agente retornando sucesso."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        session = _make_session("agent_1", "sess_1")
        mock_sm.create.return_value = session

        response_msg = _make_response_message("sess_1", {"answer": "42"})
        mock_ipc.receive = AsyncMock(return_value=response_msg)

        task = AgentTask(agent_id="agent_1", image="img:latest", prompt="Olá")
        result = await orchestrator.handle_request("Olá", [task])

        assert result.total == 1
        assert result.succeeded == 1
        assert result.failed == 0
        assert result.results[0].status == "success"
        assert result.results[0].response == {"answer": "42"}
        assert result.results[0].agent_id == "agent_1"
        assert result.results[0].session_id == "sess_1"

    async def test_handle_request_default_agent(self) -> None:
        """handle_request sem agent_tasks deve usar loop autônomo."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        # Mock do resultado do loop autônomo
        agent_res = AgentResult(agent_id="base", session_id="sess_1", status="success", response={"text": "ok"})
        loop_result = OrchestratorResult(results=[agent_res], total=1, succeeded=1, failed=0)
        
        master_session = _make_session("orchestrator", "sess_master")
        mock_sm.create.return_value = master_session

        with patch("src.orchestrator.AutonomousLoop") as MockLoop:
            mock_loop_instance = MockLoop.return_value
            mock_loop_instance.run = AsyncMock(return_value=loop_result)
            
            result = await orchestrator.handle_request("Teste sem tasks")

        assert result.total == 1
        assert result.succeeded == 1
        assert result.results[0].agent_id == "base"
        mock_sm.create.assert_called_with("orchestrator", session_id=ANY)
        mock_sm.close.assert_called_with("sess_master")

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
        """Execução paralela com 3 agentes, todos com sucesso."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        # Cada chamada a create retorna uma session diferente
        # Agora a primeira chamada é para a master session
        master_session = _make_session("orchestrator", "sess_master")
        agent_sessions = [_make_session(f"a{i}", f"s{i}") for i in range(3)]
        mock_sm.create.side_effect = [master_session] + agent_sessions

        responses = [
            _make_response_message(f"s{i}", {"idx": i}) for i in range(3)
        ]
        mock_ipc.receive = AsyncMock(side_effect=responses)

        tasks = [
            AgentTask(agent_id=f"a{i}", image="img", prompt=f"prompt_{i}")
            for i in range(3)
        ]

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
        """1 agente falha, os demais retornam sucesso."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_sessions = [_make_session(f"a{i}", f"s{i}") for i in range(3)]
        mock_sm.create.side_effect = [master_session] + agent_sessions

        # Segundo agente falha no receive (timeout)
        ok_msg_0 = _make_response_message("s0", {"ok": True})
        ok_msg_2 = _make_response_message("s2", {"ok": True})

        call_count = 0

        async def receive_side_effect(ipc_id: str, timeout: float = 30.0) -> Message:
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 1:
                raise TimeoutError("Timeout simulado")
            elif idx == 0:
                return ok_msg_0
            else:
                return ok_msg_2

        mock_ipc.receive = AsyncMock(side_effect=receive_side_effect)

        tasks = [
            AgentTask(agent_id=f"a{i}", image="img", prompt=f"p{i}")
            for i in range(3)
        ]

        result = await orchestrator.handle_request("partial", tasks)

        assert result.total == 3
        assert result.succeeded == 2
        assert result.failed == 1

        # Verifica que o agente falho tem status correto
        statuses = {r.agent_id: r.status for r in result.results}
        assert "timeout" in statuses.values() or "error" in statuses.values()

    async def test_partial_failure_spawn_error(self) -> None:
        """Agente que falha no spawn retorna status error."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        session = _make_session("a1", "s1")
        mock_sm.create.side_effect = [master_session, session]
        mock_runner.spawn = AsyncMock(side_effect=RuntimeError("Docker unavailable"))

        task = AgentTask(agent_id="a1", image="img", prompt="test")
        result = await orchestrator.handle_request("fail", [task])

        assert result.total == 1
        assert result.failed == 1
        assert result.results[0].status == "error"
        assert "Docker unavailable" in (result.results[0].error or "")


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorResultCounts:
    """Testes dos contadores do resultado."""

    async def test_all_failed(self) -> None:
        """Quando todos os agentes falham."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_sessions = [_make_session(f"a{i}", f"s{i}") for i in range(2)]
        mock_sm.create.side_effect = [master_session] + agent_sessions
        mock_ipc.receive = AsyncMock(side_effect=ConnectionError("IPC down"))

        tasks = [
            AgentTask(agent_id=f"a{i}", image="img", prompt="p")
            for i in range(2)
        ]

        result = await orchestrator.handle_request("all_fail", tasks)

        assert result.total == 2
        assert result.succeeded == 0
        assert result.failed == 2

    async def test_agent_timeout_status(self) -> None:
        """Agente que excede timeout retorna status 'timeout'."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        session = _make_session("a1", "s1")
        mock_sm.create.side_effect = [master_session, session]
        mock_ipc.receive = AsyncMock(side_effect=TimeoutError("Timeout!"))

        task = AgentTask(agent_id="a1", image="img", prompt="test")
        result = await orchestrator.handle_request("timeout", [task])

        assert result.results[0].status == "timeout"
        assert result.results[0].error is not None


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorCleanup:
    """Testes de cleanup após execução."""

    async def test_sessions_closed_after_execution(self) -> None:
        """Todas as sessões devem ser fechadas ao final, mesmo com sucesso."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        session = _make_session("a1", "sess_cleanup")
        mock_sm.create.return_value = session

        response_msg = _make_response_message("sess_cleanup", {"ok": True})
        mock_ipc.receive = AsyncMock(return_value=response_msg)

        task = AgentTask(agent_id="a1", image="img", prompt="test")
        await orchestrator.handle_request("cleanup", [task])

        # close() é chamado duas vezes: uma para o agente e outra para a master session
        assert mock_sm.close.call_count == 2
        mock_sm.close.assert_any_call("sess_cleanup")

    async def test_ipc_closed_after_execution(self) -> None:
        """Sockets IPC devem ser fechados ao final."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        session = _make_session("a1", "sess_ipc")
        mock_sm.create.return_value = session

        response_msg = _make_response_message("sess_ipc", {"ok": True})
        mock_ipc.receive = AsyncMock(return_value=response_msg)

        task = AgentTask(agent_id="a1", image="img", prompt="test")
        await orchestrator.handle_request("cleanup_ipc", [task])

        mock_ipc.close.assert_called_once()

    async def test_container_stopped_after_execution(self) -> None:
        """Containers devem ser parados ao final."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        session = _make_session("a1", "sess_stop")
        mock_sm.create.return_value = session

        response_msg = _make_response_message("sess_stop", {"ok": True})
        mock_ipc.receive = AsyncMock(return_value=response_msg)

        task = AgentTask(agent_id="a1", image="img", prompt="test")
        await orchestrator.handle_request("stop", [task])

        mock_runner.stop.assert_called_once_with("container_id_123")

    async def test_cleanup_on_error(self) -> None:
        """Cleanup deve acontecer mesmo quando o agente falha."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        session = _make_session("a1", "sess_err")
        mock_sm.create.return_value = session
        mock_ipc.receive = AsyncMock(side_effect=ConnectionError("falha"))

        task = AgentTask(agent_id="a1", image="img", prompt="test")
        await orchestrator.handle_request("error_cleanup", [task])

        # Mesmo com erro, sessão, IPC e container devem ser limpos
        # close() é chamado duas vezes: uma para o agente e outra para a master session
        assert mock_sm.close.call_count == 2
        mock_sm.close.assert_any_call("sess_err")
        mock_ipc.close.assert_called_once()
        mock_runner.stop.assert_called_once()


def _make_agent_result(agent_id: str, session_id: str, status: str = "success",
                        response: dict | None = None, error: str | None = None) -> AgentResult:
    """Helper para criar um AgentResult mockado (usado pelos testes de runtime em processo)."""
    return AgentResult(agent_id=agent_id, session_id=session_id, status=status,
                        response=response or {}, error=error)


def _create_inprocess_orchestrator() -> tuple[Orchestrator, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Cria um Orchestrator fixado no modo em processo (Roadmap V16/ADR 014), com
    ``AgentRuntime`` mockado para não executar LLM/ferramentas reais.
    """
    mock_runner = MagicMock()
    mock_runner.spawn = AsyncMock(return_value="container_id_123")

    mock_ipc = MagicMock()
    mock_ipc._connections = {}
    mock_ipc.create_socket = AsyncMock()

    mock_session_manager = MagicMock()

    mock_agent_runtime = MagicMock()
    mock_agent_runtime.run = AsyncMock()

    orchestrator = Orchestrator(
        runner=mock_runner,
        ipc=mock_ipc,
        session_manager=mock_session_manager,
        agent_runtime=mock_agent_runtime,
        agent_runtime_mode="inprocess",
    )

    return orchestrator, mock_runner, mock_ipc, mock_session_manager, mock_agent_runtime


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorInProcessRuntime:
    """Testes do runtime de agentes em processo (Roadmap V16/ADR 014).

    Cobre o Requirement "Agentes executam em processo no host" da spec
    ``agent-runtime`` (openspec/changes/v16-in-process-agents/).
    """

    async def test_default_mode_is_inprocess(self) -> None:
        """Cenário: AGENT_RUNTIME não configurado explicitamente usa 'inprocess' por padrão."""
        orchestrator = Orchestrator(
            runner=MagicMock(), ipc=MagicMock(), session_manager=MagicMock()
        )
        assert orchestrator.agent_runtime_mode == "inprocess"

    async def test_execute_agent_inprocess_no_container_spawn(self) -> None:
        """Cenário: Subtarefa sem spawn de container de agente."""
        orchestrator, mock_runner, mock_ipc, mock_sm, mock_agent_runtime = _create_inprocess_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_session = _make_session("a1", "s1")
        mock_sm.create.side_effect = [master_session, agent_session]
        mock_agent_runtime.run.return_value = _make_agent_result("a1", "s1", response={"text": "ok"})

        task = AgentTask(agent_id="a1", image="img", prompt="hello")
        result = await orchestrator.handle_request("inprocess test", [task])

        assert result.succeeded == 1
        assert result.results[0].response == {"text": "ok"}
        mock_runner.spawn.assert_not_called()
        mock_ipc.create_socket.assert_not_called()
        mock_agent_runtime.run.assert_called_once()

        called_task, called_ctx = mock_agent_runtime.run.call_args[0]
        assert called_task is task
        assert called_ctx.agent_id == "a1"
        assert called_ctx.session_id == "sess_master"
        assert called_ctx.agent_session_id == "s1"

    async def test_execute_agent_inprocess_error_status(self) -> None:
        """Cenário: Exceção — o orquestrador segue mesmo quando o agente falha."""
        orchestrator, mock_runner, mock_ipc, mock_sm, mock_agent_runtime = _create_inprocess_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_session = _make_session("a1", "s1")
        mock_sm.create.side_effect = [master_session, agent_session]
        mock_agent_runtime.run.return_value = _make_agent_result(
            "a1", "s1", status="error", error="falha simulada"
        )

        task = AgentTask(agent_id="a1", image="img", prompt="hello")
        result = await orchestrator.handle_request("inprocess fail", [task])

        assert result.failed == 1
        assert result.results[0].status == "error"
        assert result.results[0].error == "falha simulada"

    async def test_execute_agent_inprocess_timeout_status(self) -> None:
        """Cenário: Timeout — o AgentResult reflete status='timeout'."""
        orchestrator, mock_runner, mock_ipc, mock_sm, mock_agent_runtime = _create_inprocess_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_session = _make_session("a1", "s1")
        mock_sm.create.side_effect = [master_session, agent_session]
        mock_agent_runtime.run.return_value = _make_agent_result("a1", "s1", status="timeout", error="timeout!")

        task = AgentTask(agent_id="a1", image="img", prompt="hello")
        result = await orchestrator.handle_request("inprocess timeout", [task])

        assert result.results[0].status == "timeout"

    async def test_circuit_breaker_max_agent_runs_per_session(self) -> None:
        """Cenário: Limite de execuções de agentes interrompe novas execuções."""
        from src.config import MAX_AGENT_RUNS_PER_SESSION

        orchestrator, mock_runner, mock_ipc, mock_sm, mock_agent_runtime = _create_inprocess_orchestrator()
        mock_sm.create.return_value = _make_session("a1", "s1")
        orchestrator._session_agent_run_counts["sess_master"] = MAX_AGENT_RUNS_PER_SESSION

        task = AgentTask(agent_id="a1", image="img", prompt="hello")
        with pytest.raises(RuntimeError, match="Limite de execuções de agente"):
            await orchestrator._execute_agent_inprocess(task, master_session_id="sess_master")

        mock_agent_runtime.run.assert_not_called()

    async def test_ask_researcher_callback_delegates_to_core(self) -> None:
        """Cenário: o callback ask_researcher do AgentContext reutiliza dedup/registro (Spec G5)."""
        orchestrator, mock_runner, mock_ipc, mock_sm, mock_agent_runtime = _create_inprocess_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_session = _make_session("a1", "s1")
        mock_sm.create.side_effect = [master_session, agent_session]

        captured_ctx = {}

        async def fake_run(task, ctx):
            captured_ctx["ctx"] = ctx
            return _make_agent_result("a1", "s1", response={"text": "ok"})

        mock_agent_runtime.run.side_effect = fake_run

        task = AgentTask(agent_id="a1", image="img", prompt="hello")
        await orchestrator.handle_request("ask_researcher wiring", [task])

        ctx = captured_ctx["ctx"]
        assert ctx.ask_researcher is not None

        with patch.object(orchestrator, "_ask_researcher_core", new=AsyncMock(return_value="42")) as mock_core:
            answer = await ctx.ask_researcher("pergunta?", "contexto", "motivo", ["a", "b"])

        assert answer == "42"
        mock_core.assert_called_once()
