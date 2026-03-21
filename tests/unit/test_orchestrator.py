import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
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
    """Cria um Orchestrator com dependências mockadas."""
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
        """handle_request sem agent_tasks deve usar agente base padrão via thinking loop."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        # Mock do loop de planejamento para retornar uma tarefa simples
        default_task = AgentTask(agent_id="base_agent", image="geminiclaw-base", prompt="Teste sem tasks")
        
        # Agora o Orchestrator chama create duas vezes: uma para a master session e outra para o agente
        master_session = _make_session("orchestrator", "sess_master")
        session = _make_session("base_agent", "sess_default")
        mock_sm.create.side_effect = [master_session, session]

        response_msg = _make_response_message("sess_default", {"result": "ok"})
        mock_ipc.receive = AsyncMock(return_value=response_msg)
        
        with patch.object(Orchestrator, "_run_planning_loop", AsyncMock(return_value=[default_task])):
            result = await orchestrator.handle_request("Teste sem tasks")

        assert result.total == 1
        assert result.succeeded == 1
        mock_runner.spawn.assert_called_once()
        # Verifica que usou a imagem padrão definida na tarefa retornada pelo mock
        call_args = mock_runner.spawn.call_args
        assert call_args[0][0] == "base_agent"  # agent_id
        assert call_args[0][1] == "geminiclaw-base"  # image


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
