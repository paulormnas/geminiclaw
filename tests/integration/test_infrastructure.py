import pytest
import httpx
import asyncio
import os
from pathlib import Path
# tests/conftest.py força QDRANT_URL=":memory:"; este teste verifica o servidor real do compose.
QDRANT_HEALTH_URL = "http://localhost:6333/healthz"

@pytest.mark.asyncio
@pytest.mark.integration
async def test_qdrant_connectivity():
    """Verifica se o Qdrant está acessível na URL configurada."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(QDRANT_HEALTH_URL)
    except httpx.HTTPError as e:
        pytest.skip(f"Qdrant não está rodando em {QDRANT_HEALTH_URL}: {e}")

    # O corpo de /healthz varia entre versões ("all good", "healthz check passed"); só o status é contrato.
    assert response.status_code == 200

@pytest.mark.integration
def test_docker_compose_structure():
    """Verifica que o compose só tem serviços de apoio (o orquestrador e os agentes rodam localmente)."""
    compose_path = Path("docker-compose.yml")
    assert compose_path.exists()
    
    import yaml
    with open(compose_path, "r") as f:
        config = yaml.safe_load(f)
    
    assert "services" in config
    assert {"qdrant", "postgres"} <= set(config["services"])
    # O orquestrador em container foi removido (ADR 014): sem serviço próprio, sem rede dos agentes
    # e sem o socket do daemon de containers montado.
    assert "geminiclaw" not in config["services"]
    assert "networks" not in config
    assert "docker.sock" not in compose_path.read_text(encoding="utf-8")

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
