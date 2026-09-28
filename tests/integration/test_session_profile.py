"""Testes de propagação do Session Profile entre CLI, orquestrador e agentes
(Roadmap V15.6 / Spec G10).

Cobre:
- Propagação de SessionMode do Orchestrator para o env_vars do container spawnado.
- Estampagem do modo em AgentTask pelo AutonomousLoop (caminho simples).
- Adaptação do system prompt compartilhado (`_get_agent_instruction`) por modo.
- Exibição do modo na listagem `geminiclaw sessions`.
"""

import os
from unittest.mock import MagicMock, AsyncMock

import pytest

from src.orchestrator import Orchestrator, AgentTask
from src.autonomous_loop import AutonomousLoop
from src.session import Session
from src.cli import show_sessions


def _make_session(agent_id: str, session_id: str, payload: dict | None = None) -> Session:
    return Session(
        id=session_id,
        agent_id=agent_id,
        status="active",
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
        payload=payload or {},
    )


def _create_orchestrator():
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

    # Roadmap V16/ADR 014: AGENT_RUNTIME tem padrão "inprocess" — este módulo
    # testa especificamente a propagação de SESSION_MODE para env_vars do
    # container spawnado (caminho legado), então fixa o modo.
    orchestrator = Orchestrator(
        runner=mock_runner,
        ipc=mock_ipc,
        session_manager=mock_session_manager,
        agent_runtime_mode="container",
    )
    return orchestrator, mock_runner, mock_ipc, mock_session_manager


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorModePropagation:
    """O modo informado em handle_request deve chegar ao env_vars do container."""

    async def test_mode_explicito_propagado_para_env_vars(self) -> None:
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_session = _make_session("a0", "s0")
        mock_sm.create.side_effect = [master_session, agent_session]

        from src.ipc import Message
        mock_ipc.receive = AsyncMock(
            return_value=Message(
                type="response", session_id="s0", payload={"idx": 0}, timestamp="2025-01-01T00:00:00+00:00"
            )
        )

        task = AgentTask(agent_id="developer", image="img", prompt="faz algo")

        await orchestrator.handle_request("tarefa", [task], mode="auto")

        _, kwargs = mock_runner.spawn.call_args
        assert kwargs["env_vars"]["SESSION_MODE"] == "auto"

    async def test_mode_default_quando_omitido(self) -> None:
        from src.config import SESSION_DEFAULT_MODE

        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_session = _make_session("a0", "s0")
        mock_sm.create.side_effect = [master_session, agent_session]

        from src.ipc import Message
        mock_ipc.receive = AsyncMock(
            return_value=Message(
                type="response", session_id="s0", payload={"idx": 0}, timestamp="2025-01-01T00:00:00+00:00"
            )
        )

        task = AgentTask(agent_id="developer", image="img", prompt="faz algo")
        await orchestrator.handle_request("tarefa", [task])

        _, kwargs = mock_runner.spawn.call_args
        assert kwargs["env_vars"]["SESSION_MODE"] == SESSION_DEFAULT_MODE

    async def test_mode_persistido_no_payload_da_sessao_mestra(self) -> None:
        orchestrator, mock_runner, mock_ipc, mock_sm = _create_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_session = _make_session("a0", "s0")
        mock_sm.create.side_effect = [master_session, agent_session]

        from src.ipc import Message
        mock_ipc.receive = AsyncMock(
            return_value=Message(
                type="response", session_id="s0", payload={"idx": 0}, timestamp="2025-01-01T00:00:00+00:00"
            )
        )

        task = AgentTask(agent_id="developer", image="img", prompt="faz algo")
        await orchestrator.handle_request("tarefa", [task], mode="semi")

        update_calls = mock_sm.update.call_args_list
        modes_persisted = [
            c.kwargs.get("payload", {}).get("mode")
            for c in update_calls
            if c.args and c.args[0] == "sess_master"
        ]
        assert "semi" in modes_persisted


@pytest.mark.unit
@pytest.mark.asyncio
class TestAutonomousLoopModeStamping:
    """O AutonomousLoop deve estampar o SessionMode ativo em cada AgentTask criada."""

    async def test_run_simple_path_estampa_modo(self) -> None:
        mock_orchestrator = MagicMock()
        agent_result = MagicMock(status="success")
        mock_orchestrator._execute_agent = AsyncMock(return_value=agent_result)
        mock_orchestrator.output_manager.list_artifacts.return_value = []

        loop = AutonomousLoop(mock_orchestrator)
        loop._triage_classifier.classify = MagicMock(return_value=("SIMPLE", 0.99))

        await loop.run("tarefa simples", "master_sess", mode="semi")

        called_task = mock_orchestrator._execute_agent.call_args[0][0]
        assert called_task.mode == "semi"

    async def test_run_usa_default_quando_mode_vazio(self) -> None:
        from src.config import SESSION_DEFAULT_MODE

        mock_orchestrator = MagicMock()
        agent_result = MagicMock(status="success")
        mock_orchestrator._execute_agent = AsyncMock(return_value=agent_result)
        mock_orchestrator.output_manager.list_artifacts.return_value = []

        loop = AutonomousLoop(mock_orchestrator)
        loop._triage_classifier.classify = MagicMock(return_value=("SIMPLE", 0.99))

        await loop.run("tarefa simples", "master_sess")

        called_task = mock_orchestrator._execute_agent.call_args[0][0]
        assert called_task.mode == SESSION_DEFAULT_MODE


@pytest.mark.unit
class TestAgentInstructionByMode:
    """O prompt dinâmico compartilhado deve refletir o SESSION_MODE ativo."""

    def test_instrucao_assisted_menciona_ask_researcher(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_MODE", "assisted")
        from agents.base.agent import _get_agent_instruction
        instruction = _get_agent_instruction("Instrução base.")
        assert "ask_researcher" in instruction

    def test_instrucao_semi_nunca_bloqueia(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_MODE", "semi")
        from agents.base.agent import _get_agent_instruction
        instruction = _get_agent_instruction("Instrução base.")
        assert "NUNCA bloqueie" in instruction

    def test_instrucao_auto_menciona_autonomia_total(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_MODE", "auto")
        from agents.base.agent import _get_agent_instruction
        instruction = _get_agent_instruction("Instrução base.")
        assert "TOTALMENTE AUTÔNOMO" in instruction


@pytest.mark.unit
class TestSessionsListingShowsMode:
    """`geminiclaw sessions` deve exibir o modo de operação de cada container."""

    def test_show_sessions_exibe_coluna_mode(self, capsys: pytest.CaptureFixture) -> None:
        container = MagicMock()
        container.id = "abc123"
        container.short_id = "abc123"
        container.status = "running"
        container.labels = {
            "project": "geminiclaw",
            "session_id": "sess_1",
            "agent_id": "developer",
            "session_mode": "auto",
        }
        img = MagicMock()
        img.tags = ["geminiclaw-developer:latest"]
        container.image = img

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [container]

        info = show_sessions(docker_client=mock_client)
        out = capsys.readouterr().out

        assert info[0]["mode"] == "auto"
        assert "auto" in out
