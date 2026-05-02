import uuid
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

from src.db import get_connection
from src.config import QDRANT_URL, QDRANT_CHECK_COMPATIBILITY
from src.logger import get_logger
from src.skills.document_processor.extractors.base import ExtractedDocument
from src.skills.document_processor.chunker import DocumentChunker, DocumentChunk

logger = get_logger(__name__)

class DocumentIndexer:
    """Indexa documentos processados no Qdrant e PostgreSQL."""

    COLLECTION_NAME = "geminiclaw_documents"

    def __init__(self, url: str = QDRANT_URL):
        self.chunker = DocumentChunker()
        if url == ":memory:":
            self.qdrant = QdrantClient(location=":memory:")
        elif url.startswith("http"):
            self.qdrant = QdrantClient(url=url, check_compatibility=QDRANT_CHECK_COMPATIBILITY)
        else:
            self.qdrant = QdrantClient(path=url)
        self._ensure_collection()

    def _ensure_collection(self):
        """Garante que a coleção de documentos existe no Qdrant."""
        try:
            collections = self.qdrant.get_collections().collections
            exists = any(c.name == self.COLLECTION_NAME for c in collections)
            
            if exists:
                return

            logger.info(f"Criando coleção {self.COLLECTION_NAME}")
            self.qdrant.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )
            self.qdrant.create_payload_index(
                collection_name=self.COLLECTION_NAME,
                field_name="format",
                field_schema="keyword",
            )
            self.qdrant.create_payload_index(
                collection_name=self.COLLECTION_NAME,
                field_name="document_id",
                field_schema="keyword",
            )
        except Exception as e:
            logger.error(f"Erro ao verificar/criar coleção Qdrant para documentos: {e}")

    async def ingest(self, doc: ExtractedDocument) -> str:
        """Pipeline completo de ingestão."""
        document_id = str(uuid.uuid4())
        
        chunks = self.chunker.chunk(doc, document_id)
        
        self._register_document(document_id, doc, len(chunks))
        self._register_chunks(chunks)
        await self._index_vectors(chunks)
        
        logger.info(f"Documento {doc.title} ingerido com sucesso (ID: {document_id})", extra={"chunks": len(chunks)})
        return document_id

    def _register_document(self, doc_id: str, doc: ExtractedDocument, num_chunks: int):
        """Registra metadados do documento no PostgreSQL."""
        query = """
            INSERT INTO documents (
                id, source_path, filename, format, title, num_chunks, num_pages, file_size_bytes, ingested_at, metadata_json
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """
        
        file_size = 0
        import os
        if os.path.exists(doc.source_path):
            file_size = os.path.getsize(doc.source_path)
            
        params = (
            doc_id,
            doc.source_path,
            doc.title,
            doc.format,
            doc.title,
            num_chunks,
            doc.num_pages,
            file_size,
            datetime.now(timezone.utc),
            json.dumps(doc.metadata)
        )
        
        with get_connection() as conn:
            conn.execute(query, params)

    def _register_chunks(self, chunks: List[DocumentChunk]):
        """Registra chunks no PostgreSQL."""
        if not chunks:
            return
            
        query = """
            INSERT INTO document_chunks (
                id, document_id, chunk_index, content, token_count, metadata_json
            ) VALUES (
                %s, %s, %s, %s, %s, %s
            )
        """
        with get_connection() as conn:
            with conn.transaction():
                for chunk in chunks:
                    params = (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.chunk_index,
                        chunk.content,
                        chunk.token_count,
                        json.dumps(chunk.metadata)
                    )
                    conn.execute(query, params)

    async def _index_vectors(self, chunks: List[DocumentChunk]):
        """Indexa no Qdrant para busca semântica."""
        if not chunks:
            return
            
        points = []
        for chunk in chunks:
            # Mock de embedding 384d (mesmo usado no deep_search para Pi 5 sem carregamento pesado)
            import random
            random.seed(chunk.content[:50])
            vector = [random.uniform(-1, 1) for _ in range(384)]
            
            payload = {
                "document_id": chunk.document_id,
                "content": chunk.content,
                "format": chunk.metadata.get("format", ""),
                "chunk_index": chunk.chunk_index
            }
            points.append(PointStruct(id=chunk.chunk_id, vector=vector, payload=payload))
            
        self.qdrant.upsert(
            collection_name=self.COLLECTION_NAME,
            points=points
        )

    def search(self, query: str, limit: int = 5, document_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Busca semântica no Qdrant."""
        import random
        random.seed(query[:50])
        query_vector = [random.uniform(-1, 1) for _ in range(384)]
        
        query_filter = None
        if document_id:
            query_filter = Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            )
            
        results_obj = self.qdrant.query_points(
            collection_name=self.COLLECTION_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True
        )
        
        return [
            {
                "content": hit.payload["content"],
                "document_id": hit.payload["document_id"],
                "score": hit.score
            }
            for hit in results_obj.points
        ]

    def list_documents(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Lista os documentos ingeridos a partir do PostgreSQL."""
        query = "SELECT * FROM documents ORDER BY ingested_at DESC LIMIT %s"
        with get_connection() as conn:
            docs = conn.execute(query, (limit,)).fetchall()
            return [dict(d) for d in docs]
            
    def get_document_info(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Recupera detalhes de um documento no PostgreSQL."""
        query = "SELECT * FROM documents WHERE id = %s"
        with get_connection() as conn:
            doc = conn.execute(query, (document_id,)).fetchone()
            if doc:
                return dict(doc)
            return None
