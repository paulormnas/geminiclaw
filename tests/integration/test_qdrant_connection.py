import pytest
from src.utils.qdrant import get_qdrant_client

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
