import pytest
from unittest.mock import MagicMock, AsyncMock

from src.orchestrator import (
    AGENT_IDS,
    AgentResult,
    AgentTask,
    Orchestrator,
)
from src.session import Session


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


def _create_orchestrator() -> tuple[Orchestrator, MagicMock, MagicMock]:
    """Cria um Orchestrator com o ``AgentRuntime`` e o gerenciador de sessões simulados."""
    mock_session_manager = MagicMock()
    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock()
    orchestrator = Orchestrator(session_manager=mock_session_manager, agent_runtime=mock_runtime)
    return orchestrator, mock_runtime, mock_session_manager


@pytest.mark.integration
@pytest.mark.asyncio
class TestResearcherInOrchestrator:
    """Testes de integração do researcher como AgentTask no orquestrador."""

    async def test_researcher_agent_task_execution(self) -> None:
        """Researcher como AgentTask deve executar com sucesso."""
        orchestrator, runtime, mock_sm = _create_orchestrator()
        mock_sm.create.return_value = _make_session("researcher_1", "sess_r1")
        runtime.run.return_value = AgentResult(
            agent_id="researcher_1",
            session_id="sess_r1",
            status="success",
            response={"search_result": "Python foi criado por Guido van Rossum."},
        )

        task = AgentTask(agent_id="researcher_1", prompt="Quem criou o Python?")
        result = await orchestrator.handle_request("Quem criou o Python?", [task])

        assert result.total == 1
        assert result.succeeded == 1
        assert result.failed == 0
        assert result.results[0].status == "success"
        assert "Python" in str(result.results[0].response)

    async def test_researcher_type_is_a_known_role(self) -> None:
        """O papel 'researcher' deve estar entre os papéis conhecidos."""
        assert "researcher" in AGENT_IDS

    async def test_get_available_agents_includes_researcher(self) -> None:
        """get_available_agents deve incluir o researcher."""
        assert "researcher" in Orchestrator.get_available_agents()

    async def test_researcher_with_base_agent_run_without_conflict(self) -> None:
        """Researcher e base agent devem executar em sequência sem conflito de sessão."""
        orchestrator, runtime, mock_sm = _create_orchestrator()

        mock_sm.create.side_effect = [
            _make_session("orchestrator", "master_sess"),
            _make_session("base_1", "sess_b1"),
            _make_session("researcher_1", "sess_r1"),
        ]
        runtime.run.side_effect = [
            AgentResult(agent_id="base_1", session_id="sess_b1", status="success", response={"base_result": "ok"}),
            AgentResult(
                agent_id="researcher_1", session_id="sess_r1", status="success", response={"search_result": "info"}
            ),
        ]

        tasks = [
            AgentTask(agent_id="base_1", prompt="tarefa base"),
            AgentTask(agent_id="researcher_1", prompt="pesquisar info"),
        ]

        result = await orchestrator.handle_request("multi-agent", tasks)

        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0
