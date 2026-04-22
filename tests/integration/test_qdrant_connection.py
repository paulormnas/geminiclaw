import pytest
import httpx
from src.utils.qdrant import get_qdrant_client


def _qdrant_is_running() -> bool:
    """Verifica se o serviço Qdrant está respondendo em localhost:6333."""
    try:
        resp = httpx.get("http://localhost:6333/healthz", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(
    not _qdrant_is_running(),
    reason=(
        "Qdrant não está acessível em localhost:6333. "
        "Execute 'docker compose up -d qdrant' antes de rodar este teste."
    ),
)
@pytest.mark.integration
def test_qdrant_connection():
    """Testa se o utilitário consegue instanciar o QdrantClient e conectar
    no banco de vetores que deve estar rodando no docker compose.
    """
    client = get_qdrant_client()

    # Chama o endpoint healthzinho /collections para garantir a resposta
    collections = client.get_collections()

    # Se passou sem exceptions, sucesso
    assert collections is not None

