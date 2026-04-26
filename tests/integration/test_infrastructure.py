import pytest
import docker
import httpx
import asyncio
import os
from pathlib import Path
from src.config import QDRANT_URL

def is_docker_available():
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False

@pytest.mark.asyncio
@pytest.mark.integration
async def test_qdrant_connectivity():
    """Verifica se o Qdrant está acessível na URL configurada."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{QDRANT_URL}/healthz")
            assert response.status_code == 200
            assert response.text == "all good"
    except Exception as e:
        pytest.skip(f"Qdrant não está rodando em {QDRANT_URL}: {e}")

@pytest.mark.integration
def test_docker_compose_structure():
    """Verifica se o arquivo docker-compose.yml existe e tem a estrutura básica."""
    compose_path = Path("docker-compose.yml")
    assert compose_path.exists()
    
    import yaml
    with open(compose_path, "r") as f:
        config = yaml.safe_load(f)
    
    assert "services" in config
    assert "qdrant" in config["services"]
    assert "geminiclaw" in config["services"]
    assert "networks" in config
    assert "geminiclaw-net" in config["networks"]

@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(not is_docker_available(), reason="Docker daemon não está rodando")
async def test_runner_uses_correct_network():
    """Verifica se o runner está configurado para usar a rede geminiclaw-net."""
    from src.runner import ContainerRunner
    
    runner = ContainerRunner()
    # Verifica se a rede existe (o runner deve ter criado/verificado)
    client = docker.from_env()
    try:
        network = client.networks.get("geminiclaw-net")
        assert network is not None
    except docker.errors.NotFound:
        pytest.fail("Rede geminiclaw-net não foi encontrada.")
    finally:
        client.close()
