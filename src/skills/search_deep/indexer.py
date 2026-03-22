import os
import uuid
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from src.config import QDRANT_URL
from src.logger import get_logger
from .crawler import CrawledPage

logger = get_logger(__name__)

class VectorIndexer:
    """Gerencia o índice vetorial no Qdrant."""

    COLLECTION_NAME = "geminiclaw_knowledge"

    def __init__(self, url: str = QDRANT_URL):
        if url == ":memory:":
            self.client = QdrantClient(location=":memory:")
        elif url.startswith("http"):
            self.client = QdrantClient(url=url)
        else:
            self.client = QdrantClient(path=url)
        self._ensure_collection()

    def _ensure_collection(self):
        """Garante que a coleção existe no Qdrant."""
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == self.COLLECTION_NAME for c in collections)
            
            if not exists:
                logger.info(f"Criando coleção {self.COLLECTION_NAME}")
                self.client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )
                # Cria índices para filtros comuns
                self.client.create_payload_index(
                    collection_name=self.COLLECTION_NAME,
                    field_name="domain",
                    field_schema="keyword",
                )
                self.client.create_payload_index(
                    collection_name=self.COLLECTION_NAME,
                    field_name="data_type",
                    field_schema="keyword",
                )
        except Exception as e:
            logger.error(f"Erro ao verificar/criar coleção Qdrant: {e}")

    async def index_pages(self, pages: List[CrawledPage]):
        """Indexa as páginas no Qdrant com chunking e embeddings."""
        points = []
        for page in pages:
            chunks = self._chunk_text(page.content)
            for i, chunk in enumerate(chunks):
                # Gera ID determinístico
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{page.url}#{i}"))
                
                # Gera embedding (mock por enquanto, até integrar modelo real)
                # TODO: Substituir por modelo real (sentence-transformers)
                vector = self._generate_mock_embedding(chunk)
                
                payload = {
                    "url": page.url,
                    "domain": page.domain,
                    "title": page.title,
                    "content": chunk,
                    "data_type": page.content_type,
                    "crawled_at": page.crawled_at,
                    "chunk_index": i
                }
                
                points.append(PointStruct(id=point_id, vector=vector, payload=payload))
        
        if points:
            self.client.upsert(
                collection_name=self.COLLECTION_NAME,
                points=points
            )
            logger.info(f"Indexados {len(points)} chunks da página {page.url}")

    def _chunk_text(self, text: str, chunk_size: int = 1500, overlap: int = 150) -> List[str]:
        """Divide o texto em chunks com sobreposição."""
        # Simplificado: divide por caracteres
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += chunk_size - overlap
        return chunks

    def _generate_mock_embedding(self, text: str) -> List[float]:
        """Gera um embedding mockado de 384 dimensões."""
        # Apenas para teste inicial sem carregar modelo pesado
        import random
        random.seed(text[:50])
        return [random.uniform(-1, 1) for _ in range(384)]

    async def search(self, query: str, limit: int = 5, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Realiza busca vetorial no Qdrant."""
        # Gera embedding da query
        query_vector = self._generate_mock_embedding(query)
        
        query_filter = None
        if domain:
            query_filter = Filter(
                must=[FieldCondition(key="domain", match=MatchValue(value=domain))]
            )
        
        results = self.client.search(
            collection_name=self.COLLECTION_NAME,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True
        )
        
        return [
            {
                "content": hit.payload["content"],
                "url": hit.payload["url"],
                "title": hit.payload["title"],
                "score": hit.score,
                "metadata": hit.payload
            }
            for hit in results
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas da coleção."""
        collection_info = self.client.get_collection(self.COLLECTION_NAME)
        return {
            "points_count": collection_info.points_count,
            "status": str(collection_info.status)
        }

if __name__ == "__main__":
    import asyncio
    from .indexer_cli import main
    asyncio.run(main())
