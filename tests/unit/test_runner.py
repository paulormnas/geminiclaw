import pytest
import asyncio
from unittest.mock import MagicMock, patch
import os
from pathlib import Path
from src.runner import ContainerRunner

@pytest.fixture
def mock_docker_client():
    """Fixture para mockar o cliente Docker."""
    with patch("docker.from_env") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client

@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_spawn_parameters(mock_docker_client):
    """Testa se o runner passa os parâmetros corretos para o docker-py."""
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test_key", "SQLITE_DB_PATH": "/path/to/db"}):
        runner = ContainerRunner()
        
        mock_container = MagicMock()
        mock_container.id = "fake_id_123"
        mock_docker_client.containers.run.return_value = mock_container
        
        container_id = await runner.spawn("test_agent", "test_image", "session_123")
        
        assert container_id == "fake_id_123"
        
        # O runner monta o diretório de sockets, o diretório do banco e o diretório de outputs
        from src.runner import IPC_SOCKET_DIR
        output_path = str(Path("outputs").absolute() / "session_123")
        
        mock_docker_client.containers.run.assert_called_once_with(
            image="test_image",
            mem_limit="512m",
            nano_cpus=1_000_000_000,
            network="geminiclaw-net",
            user="appuser",
            remove=True,
            detach=True,
            labels={"project": "geminiclaw", "agent_id": "test_agent", "session_id": "session_123"},
            environment={
                "SESSION_ID": "session_123",
                "AGENT_ID": "test_agent",
                "GEMINI_API_KEY": "test_key",
                "GOOGLE_API_KEY": "test_key",
                "DEFAULT_MODEL": "gemini-3.1-flash-lite-preview",
                "SQLITE_DB_PATH": "/data/geminiclaw.db",
                "AGENT_SOCKET_NAME": "test_agent_session_123.sock",
            },
            volumes={
                "/path/to": {"bind": "/data", "mode": "rw"},
                output_path: {"bind": "/outputs", "mode": "rw"},
                str(Path(IPC_SOCKET_DIR)): {"bind": "/tmp/geminiclaw-ipc", "mode": "rw"},
            },
            extra_hosts={},
        )

@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_concurrency_limit(mock_docker_client):
    """Testa se o semáforo limita a execução paralela."""
    runner = ContainerRunner(semaphore_limit=2)
    
    # Mock para atrasar a execução de run
    async def delayed_run(*args, **kwargs):
        await asyncio.sleep(0.1)
        mock_container = MagicMock()
        mock_container.id = "id"
        return mock_container

    # Precisamos de um wrapper síncrono para o run_in_executor
    def sync_run(*args, **kwargs):
        import time
        time.sleep(0.1)
        mock_container = MagicMock()
        mock_container.id = "id"
        return mock_container

    mock_docker_client.containers.run.side_effect = sync_run
    
    # Dispara 3 spawns
    tasks = [
        runner.spawn("a1", "img", "s1"),
        runner.spawn("a2", "img", "s2"),
        runner.spawn("a3", "img", "s3")
    ]
    
    # Executa e verifica se o semáforo agiu (tempo total aproximado)
    start_time = asyncio.get_event_loop().time()
    await asyncio.gather(*tasks)
    end_time = asyncio.get_event_loop().time()
    
    # 2 containers rodam em paralelo (0.1s), o 3º espera (mais 0.1s)
    # Total deve ser >= 0.2s
    assert end_time - start_time >= 0.2

@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_stop(mock_docker_client):
    """Testa o encerramento de um container."""
    runner = ContainerRunner()
    mock_container = MagicMock()
    mock_docker_client.containers.get.return_value = mock_container
    
    await runner.stop("fake_id")
    
    mock_docker_client.containers.get.assert_called_with("fake_id")
    mock_container.stop.assert_called_once()
