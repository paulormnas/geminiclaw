from qdrant_client import QdrantClient
from src.config import QDRANT_URL
from src.logger import get_logger

logger = get_logger(__name__)

def get_qdrant_client() -> QdrantClient:
    """Cria e retorna uma instância configurada do QdrantClient.
    
    A URL é definida pela variável de ambiente QDRANT_URL,
    que por padrão aponta para o container do docker-compose:
    http://localhost:6333 (host) ou http://geminiclaw-qdrant:6333 (Docker).

    Returns:
        Instância de QdrantClient pronta para uso.
    """
    logger.debug("Inicializando QdrantClient", extra={"url": QDRANT_URL})
    client = QdrantClient(url=QDRANT_URL)
    return client
