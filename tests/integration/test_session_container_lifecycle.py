"""Testes de integração para o ciclo de vida de container por sessão (Roadmap V14.5)."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.runner import SessionContainerRunner, ContainerRunner
from src.ipc import Message


@pytest.fixture
def mock_container_runner():
    """Mock do ContainerRunner com cliente Docker simulado."""
    runner = MagicMock(spec=ContainerRunner)
    runner.client = MagicMock()
    runner.spawn = AsyncMock(return_value="container_dev_123")
    return runner


@pytest.fixture
def mock_ipc():
    """Mock do IPCChannel."""
    ipc = MagicMock()
    ipc.send = AsyncMock()
    return ipc


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.integration
async def test_session_container_persists_across_multiple_subtasks(mock_container_runner, mock_ipc):
    """Cenário 1: Container ID permanece idêntico em 3 subtarefas consecutivas."""
    session_runner = SessionContainerRunner(runner=mock_container_runner, ipc=mock_ipc)

    # Simula container ativo no Docker
    mock_docker_container = MagicMock()
    mock_docker_container.status = "running"
    mock_container_runner.client.containers.get.return_value = mock_docker_container

    # Resposta IPC padrão
    mock_ipc.send.return_value = Message(
        type="response",
        session_id="session_abc",
        payload={"text": "Sucesso", "status": "ok"},
        timestamp="2026-09-23T10:00:00Z"
    )

    # 1. Primeira subtarefa: spawna container
    cid_1 = await session_runner.start("session_abc", "developer")
    res_1 = await session_runner.send("session_abc", "developer", {"prompt": "Step 1"}, task_name="step_1")
    assert cid_1 == "container_dev_123"
    assert res_1["text"] == "Sucesso"

    # 2. Segunda subtarefa: reusa mesmo container
    cid_2 = await session_runner.start("session_abc", "developer")
    res_2 = await session_runner.send("session_abc", "developer", {"prompt": "Step 2"}, task_name="step_2")
    assert cid_2 == cid_1

    # 3. Terceira subtarefa: reusa mesmo container
    cid_3 = await session_runner.start("session_abc", "developer")
    res_3 = await session_runner.send("session_abc", "developer", {"prompt": "Step 3"}, task_name="step_3")
    assert cid_3 == cid_1

    # Confirma que spawn foi invocado APENAS UMA VEZ
    assert mock_container_runner.spawn.call_count == 1


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.integration
async def test_session_container_auto_recovery_on_dead_container(mock_container_runner, mock_ipc):
    """Cenário 2: Container morto é detectado e recuperado na execução da subtarefa."""
    session_runner = SessionContainerRunner(runner=mock_container_runner, ipc=mock_ipc)

    mock_docker_container = MagicMock()
    mock_docker_container.status = "running"
    mock_container_runner.client.containers.get.return_value = mock_docker_container

    mock_ipc.send.return_value = Message(
        type="response",
        session_id="session_rec",
        payload={"text": "Recuperado com sucesso"},
        timestamp="2026-09-23T10:00:00Z"
    )

    # Inicia primeira vez
    await session_runner.start("session_rec", "developer")
    assert mock_container_runner.spawn.call_count == 1

    # Simula container morrendo (status != 'running')
    mock_docker_container.status = "exited"
    mock_container_runner.spawn.return_value = "container_dev_recovered_456"

    # send() deve detectar container morto e auto-recuperar
    res = await session_runner.send("session_rec", "developer", {"prompt": "Step"}, task_name="step_recover")
    assert res["text"] == "Recuperado com sucesso"
    assert mock_container_runner.spawn.call_count == 2
    assert session_runner._active_containers[("session_rec", "developer")]["container_id"] == "container_dev_recovered_456"


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.integration
async def test_session_container_circuit_breaker_after_two_recoveries(mock_container_runner, mock_ipc):
    """Cenário 3: Máximo de 2 recuperações por subtarefa; 3ª falha aciona circuit breaker."""
    session_runner = SessionContainerRunner(runner=mock_container_runner, ipc=mock_ipc)

    mock_docker_container = MagicMock()
    mock_docker_container.status = "exited"  # Sempre morto
    mock_container_runner.client.containers.get.return_value = mock_docker_container

    mock_ipc.send.return_value = Message(
        type="response",
        session_id="session_cb",
        payload={"text": "ok"},
        timestamp="2026-09-23T10:00:00Z"
    )

    # Registra estado inicial
    session_runner._active_containers[("session_cb", "developer")] = {
        "container_id": "c_orig",
        "session_id": "session_cb",
        "agent_id": "developer",
        "image": "geminiclaw-developer",
        "subtask_recoveries": {"subtask_fragil": 2},  # Já consumiu as 2 tentativas
    }

    # Próxima tentativa na mesma subtarefa DEVE levantar RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        await session_runner.send(
            "session_cb",
            "developer",
            {"prompt": "Tentar novamente"},
            task_name="subtask_fragil"
        )

    assert "Circuit breaker ativado" in str(exc_info.value)
    assert "limite de 2 recuperações excedido" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.integration
async def test_session_container_graceful_shutdown(mock_container_runner, mock_ipc):
    """Cenário 4: Shutdown graceful via IPC envia 'shutdown' e confirma 'shutdown_ack'."""
    session_runner = SessionContainerRunner(runner=mock_container_runner, ipc=mock_ipc)

    mock_docker_container = MagicMock()
    mock_docker_container.status = "running"
    mock_container_runner.client.containers.get.return_value = mock_docker_container

    session_runner._active_containers[("session_shut", "developer")] = {
        "container_id": "c_to_shut",
        "session_id": "session_shut",
        "agent_id": "developer",
        "image": "geminiclaw-developer",
    }

    # Resposta de shutdown_ack pelo container
    mock_ipc.send.return_value = Message(
        type="shutdown_ack",
        session_id="session_shut",
        payload={"status": "ok"},
        timestamp="2026-09-23T10:00:00Z"
    )

    await session_runner.stop("session_shut", "developer")

    # Verifica se mensagem de shutdown foi enviada
    assert mock_ipc.send.call_count == 1
    sent_msg = mock_ipc.send.call_args[0][0]
    assert sent_msg.type == "shutdown"

    # Verifica se o container Docker foi encerrado
    mock_docker_container.stop.assert_called_once_with(timeout=15)
    assert ("session_shut", "developer") not in session_runner._active_containers
