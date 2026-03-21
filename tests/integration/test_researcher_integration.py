import pytest
from unittest.mock import MagicMock, AsyncMock

from src.orchestrator import (
    Orchestrator,
    AgentTask,
    AGENT_REGISTRY,
)
from src.session import Session
from src.ipc import Message


def _make_session(agent_id: str, session_id: str = "sess_r1") -> Session:
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
    mock_runner.spawn = AsyncMock(return_value="container_researcher_123")
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


@pytest.mark.integration
@pytest.mark.asyncio
class TestResearcherInOrchestrator:
    """Testes de integração do researcher como AgentTask no orquestrador."""

    async def test_researcher_agent_task_execution(self) -> None:
        """Researcher como AgentTask deve executar com sucesso."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        session = _make_session("researcher_1", "sess_r1")
        mock_sm.create.return_value = session

        response_msg = _make_response_message(
            "sess_r1",
            {"search_result": "Python foi criado por Guido van Rossum."},
        )
        mock_ipc.receive = AsyncMock(return_value=response_msg)

        task = AgentTask(
            agent_id="researcher_1",
            image="geminiclaw-researcher",
            prompt="Quem criou o Python?",
        )
        result = await orchestrator.handle_request("Quem criou o Python?", [task])

        assert result.total == 1
        assert result.succeeded == 1
        assert result.failed == 0
        assert result.results[0].status == "success"
        assert "Python" in str(result.results[0].response)

    async def test_researcher_type_in_registry(self) -> None:
        """O tipo 'researcher' deve estar registrado no AGENT_REGISTRY."""
        assert "researcher" in AGENT_REGISTRY
        assert AGENT_REGISTRY["researcher"] == "geminiclaw-researcher"

    async def test_get_available_agents_includes_researcher(self) -> None:
        """get_available_agents deve incluir o researcher."""
        agents = Orchestrator.get_available_agents()
        assert "researcher" in agents
        assert agents["researcher"] == "geminiclaw-researcher"

    async def test_researcher_with_base_agent_parallel(self) -> None:
        """Researcher e base agent devem executar em paralelo sem conflito."""
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        sessions = [
            _make_session("orchestrator", "master_sess"),
            _make_session("base_1", "sess_b1"),
            _make_session("researcher_1", "sess_r1"),
        ]
        mock_sm.create.side_effect = sessions

        responses = [
            _make_response_message("sess_b1", {"base_result": "ok"}),
            _make_response_message("sess_r1", {"search_result": "info"}),
        ]
        mock_ipc.receive = AsyncMock(side_effect=responses)

        tasks = [
            AgentTask(agent_id="base_1", image="geminiclaw-base", prompt="tarefa base"),
            AgentTask(agent_id="researcher_1", image="geminiclaw-researcher", prompt="pesquisar info"),
        ]

        result = await orchestrator.handle_request("multi-agent", tasks)

        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0
