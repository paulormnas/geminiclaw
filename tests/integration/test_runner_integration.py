import pytest
import asyncio
import docker
import os
from unittest.mock import patch
from src.runner import ContainerRunner


def _geminiclaw_image_exists() -> bool:
    """Verifica se a imagem geminiclaw-base está disponível localmente."""
    import subprocess
    try:
        result = subprocess.run(["docker", "images", "-q", "geminiclaw-base:latest"], check=True, capture_output=True, text=True, timeout=2)
        return bool(result.stdout.strip())
    except Exception:
        return False


_SKIP_NO_IMAGE = pytest.mark.skipif(
    not _geminiclaw_image_exists(),
    reason=(
        "Imagem 'geminiclaw-base' não encontrada. "
        "Execute 'docker build -t geminiclaw-base -f containers/Dockerfile .' antes de rodar estes testes."
    ),
)


@pytest.fixture
def docker_client():
    return docker.from_env()

@_SKIP_NO_IMAGE
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

@_SKIP_NO_IMAGE
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

@_SKIP_NO_IMAGE
@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_cleanup_integration(docker_client):
    """Testa se finalizar a sessão garante a remoção do container limpo."""
    runner = ContainerRunner()
    
    # Spawn
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key", "SQLITE_DB_PATH": "store/geminiclaw.db"}):
        container_id = await runner.spawn("cleanup_agent", "geminiclaw-base", "sess_cleanup")
    
    # Valida presença do container rodando associado à sessão
    containers_before = docker_client.containers.list(filters={"label": "session_id=sess_cleanup"})
    assert len(containers_before) == 1
    
    # Força remoção pela lógica do runner (simulando fim da sessão)
    await runner.stop(container_id)
    
    # Aguarda o deamon remover
    await asyncio.sleep(2)
    
    # Valida ausência total de containers com a label da sessão (incluindo parados)
    containers_after = docker_client.containers.list(filters={"label": "session_id=sess_cleanup"}, all=True)
    assert len(containers_after) == 0
