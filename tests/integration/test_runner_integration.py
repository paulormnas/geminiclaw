import pytest
import asyncio
import docker
import os
from unittest.mock import patch
from src.runner import ContainerRunner

@pytest.fixture
def docker_client():
    return docker.from_env()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_runner_lifecycle_integration(docker_client):
    """Testa o ciclo de vida real de um container."""
    runner = ContainerRunner()
    
    # Usa a imagem customizada que tem o usuário appuser
    image = "geminiclaw-base"
    agent_id = "int_agent"
    session_id = "sess_int"
    
    # Spawn
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key", "SQLITE_DB_PATH": "store/geminiclaw.db"}):
        container_id = await runner.spawn(agent_id, image, session_id)
    assert container_id is not None
    
    # Verifica se o container está rodando
    container = docker_client.containers.get(container_id)
    assert container.status in ["running", "created"]
    assert container.labels["project"] == "geminiclaw"
    
    # Stop
    await runner.stop(container_id)
    
    # Verifica se o container foi removido (remove=True foi passado para run)
    # Aguarda um pouco para a remoção ocorrer
    await asyncio.sleep(2)
    with pytest.raises(docker.errors.NotFound):
        docker_client.containers.get(container_id)

@pytest.mark.integration
@pytest.mark.asyncio
async def test_runner_cleanup_all_integration(docker_client):
    """Testa a limpeza de múltiplos containers."""
    runner = ContainerRunner()
    image = "geminiclaw-base"
    
    # Spawn de 2 containers
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key", "SQLITE_DB_PATH": "store/geminiclaw.db"}):
        id1 = await runner.spawn("a1", image, "s1")
        id2 = await runner.spawn("a2", image, "s2")
    
    # Cleanup
    runner.cleanup_all()
    
    # Aguarda remoção
    await asyncio.sleep(2)
    with pytest.raises(docker.errors.NotFound):
        docker_client.containers.get(id1)
    with pytest.raises(docker.errors.NotFound):
        docker_client.containers.get(id2)
