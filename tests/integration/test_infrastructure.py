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
