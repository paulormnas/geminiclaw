import pytest
import asyncio
from unittest.mock import MagicMock, patch
import os
from pathlib import Path
from src.runner import ContainerRunner

@pytest.fixture
def mock_docker_client():
    """Fixture para mockar o cliente Docker."""
    with patch("docker.from_env") as mock, \
         patch("src.runner.PiHealthMonitor") as mock_health:
        client = MagicMock()
        mock.return_value = client
        mock_health_instance = MagicMock()
        mock_health.return_value = mock_health_instance
        # Mock memory usage to return a safe value
        mock_health_instance.get_memory_usage.return_value = {"available_mb": 8192}
        mock_health_instance.get_temperature.return_value = 50.0
        yield client

@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_spawn_parameters(mock_docker_client):
    """Testa se o runner passa os parâmetros corretos para o docker-py."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("src.runner.GEMINI_API_KEY", "test_key"), \
             patch("src.runner.DATABASE_URL", "postgresql://geminiclaw:geminiclaw_secret@localhost:5432/geminiclaw"), \
             patch("src.runner.LLM_MODEL", "gemini-3-flash-preview"), \
             patch("src.runner.LLM_PROVIDER", "google"), \
             patch("src.runner.OLLAMA_BASE_URL", "http://localhost:11434"), \
             patch("src.runner.OLLAMA_NUM_CTX", 4096), \
             patch("src.runner.OLLAMA_ENABLE_THINKING", False), \
             patch("src.runner.OUTPUT_BASE_DIR", "outputs"), \
             patch("src.runner.LOGS_BASE_DIR", "logs"), \
             patch("src.runner.LLM_REQUESTS_PER_MINUTE", 15):
            
            # Mocking side effects to avoid PermissionError on dummy paths
            with patch("pathlib.Path.mkdir"), \
                 patch("pathlib.Path.chmod"), \
                 patch("os.stat") as mock_stat:
                
                mock_stat.return_value.st_gid = 999
                
                with patch("src.runner.ContainerRunner.ensure_infrastructure"):
                    runner = ContainerRunner()
                
                mock_container = MagicMock()
                mock_container.id = "fake_id_123"
                mock_docker_client.containers.run.return_value = mock_container
                
                container_id = await runner.spawn("base", "test_image", "session_123")
                
                assert container_id == "fake_id_123"
                
                # O runner monta o diretório de sockets, o diretório do banco, diretório de outputs e diretório de logs
                from src.runner import IPC_SOCKET_DIR
                output_path = str(Path("outputs").absolute() / "session_123" / "artifacts")
                logs_path = str(Path("outputs").absolute() / "session_123" / "logs")

                expected_volumes = {
                    output_path: {"bind": "/outputs", "mode": "rw"},
                    logs_path: {"bind": "/logs", "mode": "rw"},
                    str(Path(IPC_SOCKET_DIR)): {"bind": "/tmp/geminiclaw-ipc", "mode": "rw"},
                    str(Path(__file__).parent.parent.parent / "src"): {"bind": "/app/src", "mode": "rw"},
                    str(Path(__file__).parent.parent.parent / "agents"): {"bind": "/app/agents", "mode": "rw"},
                }

                # Mock group_add logic and docker.sock volume
                expected_group_add = []
                if os.path.exists("/var/run/docker.sock"):
                    expected_group_add = [999]
                    expected_volumes["/var/run/docker.sock"] = {"bind": "/var/run/docker.sock", "mode": "rw"}

                actual_args = mock_docker_client.containers.run.call_args[1]
                expected_args = {
                    "image": "test_image-slim",
                    "mem_limit": "512m",
                    "nano_cpus": 1_000_000_000,
                    "network": "geminiclaw-net",
                    "user": "appuser",
                    "remove": True,
                    "detach": True,
                    "group_add": expected_group_add,
                    "labels": {"project": "geminiclaw", "agent_id": "base", "session_id": "session_123"},
                    "environment": {
                        "AGENT_ID": "base",
                        "SESSION_ID": "session_123",
                        "LLM_PROVIDER": "google",
                        "LLM_MODEL": "gemini-3-flash-preview",
                        "GEMINI_API_KEY": "test_key",
                        "GOOGLE_API_KEY": "test_key",
                        "OLLAMA_BASE_URL": "http://host.docker.internal:11434",
                        "OLLAMA_NUM_CTX": "4096",
                        "OLLAMA_ENABLE_THINKING": "false",
                        "LLM_REQUESTS_PER_MINUTE": "15",
                        "LLM_RATE_LIMIT_COOLDOWN_SECONDS": "30",
                        "DEPLOYMENT_PROFILE": "default",
                        "DATABASE_URL": "postgresql://geminiclaw:geminiclaw_secret@geminiclaw-postgres:5432/geminiclaw",
                        "AGENT_SOCKET_NAME": "base_session_123.sock",
                        "OUTPUT_BASE_DIR": "/outputs",
                        "LOGS_BASE_DIR": "/logs",
                    },
                    "volumes": expected_volumes,
                    "extra_hosts": {"host.docker.internal": "host-gateway"},
                }
                
                # Comparar um por um para facilitar debug se necessário
                assert actual_args["image"] == expected_args["image"]
                assert actual_args["mem_limit"] == expected_args["mem_limit"]
                assert actual_args["environment"] == expected_args["environment"]
                assert actual_args["volumes"] == expected_args["volumes"]
                assert actual_args == expected_args

@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_concurrency_limit(mock_docker_client):
    """Testa se o semáforo limita a execução paralela."""
    with patch("src.runner.ContainerRunner.ensure_infrastructure"):
        runner = ContainerRunner(semaphore_limit=2)
    
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
async def test_runner_local_llm_concurrency_limit(mock_docker_client):
    """Testa se o semáforo de LLM local limita a execução paralela de Ollama."""
    with patch("src.runner.LLM_PROVIDER", "ollama"), \
         patch("src.config.MAX_LOCAL_LLM_CONCURRENT", 1), \
         patch("src.runner.ContainerRunner.ensure_infrastructure"):
        
        runner = ContainerRunner(semaphore_limit=5)
        
        def sync_run(*args, **kwargs):
            import time
            time.sleep(0.1)
            mock_container = MagicMock()
            mock_container.id = "id"
            return mock_container

        mock_docker_client.containers.run.side_effect = sync_run
        
        # Dispara 2 spawns (mesmo com global_semaphore=5, local_semaphore=1 deve segurar)
        tasks = [
            runner.spawn("a1", "img", "s1"),
            runner.spawn("a2", "img", "s2")
        ]
        
        start_time = asyncio.get_event_loop().time()
        await asyncio.gather(*tasks)
        end_time = asyncio.get_event_loop().time()
        
        # 1 container por vez devido ao local_semaphore (0.1s + 0.1s)
        assert end_time - start_time >= 0.2

@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_stop(mock_docker_client):
    """Testa o encerramento de um container."""
    with patch("src.runner.ContainerRunner.ensure_infrastructure"):
        runner = ContainerRunner()
    mock_container = MagicMock()
    mock_docker_client.containers.get.return_value = mock_container
    
    await runner.stop("fake_id")
    
    mock_docker_client.containers.get.assert_called_with("fake_id")
    mock_container.stop.assert_called_once()
