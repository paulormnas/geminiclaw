import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from src.config import QDRANT_CHECK_COMPATIBILITY, QDRANT_URL
from src.db import get_connection
from src.embeddings.base import EmbeddingProvider, embedding_payload, get_embedding_provider
from src.logger import get_logger
from src.skills.document_processor.chunker import DocumentChunk, DocumentChunker
from src.skills.document_processor.extractors.base import ExtractedDocument

logger = get_logger(__name__)


class DocumentIndexer:
    """Indexa documentos processados no Qdrant e PostgreSQL, usando embeddings locais.

    Os vetores são gerados por um `EmbeddingProvider` local (Roadmap V16 /
    ADR 011 §3). Cada ponto gravado carrega os metadados de versão do
    embedding, usados para detectar incompatibilidade entre o modelo
    configurado e os vetores já indexados.
    """

    COLLECTION_NAME = "geminiclaw_documents"

    def __init__(self, url: str = QDRANT_URL, embedding_provider: Optional[EmbeddingProvider] = None):
        """Inicializa o indexador e garante a coleção do Qdrant.

        Args:
            url: URL do Qdrant (``http(s)://...``), caminho local, ou
                ``":memory:"`` para um cliente em memória (testes).
            embedding_provider: Provedor de embeddings a usar. Se omitido,
                usa o singleton do processo (`get_embedding_provider`).
        """
        self.chunker = DocumentChunker()
        self._embedding_provider = embedding_provider or get_embedding_provider()
        self._search_disabled = False
        if url == ":memory:":
            self.qdrant = QdrantClient(location=":memory:")
        elif url.startswith("http"):
            self.qdrant = QdrantClient(url=url, check_compatibility=QDRANT_CHECK_COMPATIBILITY)
        else:
            self.qdrant = QdrantClient(path=url)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Garante que a coleção de documentos existe e é compatível com o provedor atual.

        Se a coleção já existir com uma dimensão diferente da do provedor
        configurado, a coleção NÃO é recriada automaticamente — a busca
        semântica é desabilitada e um erro orientando
        `geminiclaw embeddings reindex` é registrado.
        """
        try:
            provider_dimension = self._embedding_provider.info.dimension
        except Exception as e:
            logger.error(
                "Falha ao carregar o provedor de embeddings local; busca semântica desabilitada",
                extra={"collection": self.COLLECTION_NAME, "error": str(e)},
            )
            self._search_disabled = True
            return

        try:
            collections = self.qdrant.get_collections().collections
            existing = next((c for c in collections if c.name == self.COLLECTION_NAME), None)

            if existing is None:
                logger.info(f"Criando coleção {self.COLLECTION_NAME}")
                self.qdrant.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(size=provider_dimension, distance=Distance.COSINE),
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
                return

            collection_dimension = self.qdrant.get_collection(self.COLLECTION_NAME).config.params.vectors.size
            if collection_dimension != provider_dimension:
                logger.error(
                    "Dimensão da coleção incompatível com o modelo de embedding atual; busca semântica desabilitada",
                    extra={
                        "collection": self.COLLECTION_NAME,
                        "collection_dimension": collection_dimension,
                        "provider_dimension": provider_dimension,
                        "hint": f"geminiclaw embeddings reindex --collection {self.COLLECTION_NAME}",
                    },
                )
                self._search_disabled = True
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
                id, source_path, filename, format, title, num_chunks, num_pages, file_size_bytes,
                ingested_at, metadata_json
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """

        file_size = 0
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
            json.dumps(doc.metadata),
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
                        json.dumps(chunk.metadata),
                    )
                    conn.execute(query, params)

    async def _index_vectors(self, chunks: List[DocumentChunk]) -> None:
        """Indexa no Qdrant para busca semântica, usando embeddings locais.

        Args:
            chunks: Chunks de documento já registrados no PostgreSQL.
        """
        if not chunks:
            return

        if self._search_disabled:
            logger.warning(
                "Indexação vetorial ignorada: coleção desabilitada por incompatibilidade de dimensão de embedding.",
                extra={"collection": self.COLLECTION_NAME},
            )
            return

        texts = [chunk.content for chunk in chunks]
        vectors = await asyncio.to_thread(self._embedding_provider.embed_documents, texts)

        points = []
        for chunk, vector in zip(chunks, vectors):
            payload = {
                "document_id": chunk.document_id,
                "content": chunk.content,
                "format": chunk.metadata.get("format", ""),
                "chunk_index": chunk.chunk_index,
                **embedding_payload(chunk.content, self._embedding_provider),
            }
            points.append(PointStruct(id=chunk.chunk_id, vector=vector, payload=payload))

        self.qdrant.upsert(collection_name=self.COLLECTION_NAME, points=points)

    def _current_model_conditions(self) -> List[FieldCondition]:
        """Condições de filtro que casam apenas pontos do modelo/versão atuais."""
        info = self._embedding_provider.info
        return [
            FieldCondition(key="embedding_model", match=MatchValue(value=info.model)),
            FieldCondition(key="embedding_version", match=MatchValue(value=info.version)),
        ]

    def _count_outdated_points(self) -> int:
        """Conta pontos indexados com um modelo/versão de embedding diferente do atual.

        Falha de forma silenciosa (retorna 0) se a contagem não puder ser
        calculada — este é um aviso auxiliar, não deve derrubar a busca.
        """
        try:
            total = self.qdrant.count(collection_name=self.COLLECTION_NAME).count
            current = self.qdrant.count(
                collection_name=self.COLLECTION_NAME,
                count_filter=Filter(must=self._current_model_conditions()),
            ).count
            if not isinstance(total, int) or not isinstance(current, int):
                return 0
            return max(0, total - current)
        except Exception as e:
            logger.debug(f"Não foi possível contar pontos de embedding desatualizados: {e}")
            return 0

    def search(self, query: str, limit: int = 5, document_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Busca semântica no Qdrant usando o provedor de embeddings local.

        Args:
            query: Texto da consulta.
            limit: Número máximo de resultados.
            document_id: Filtro opcional por documento.

        Returns:
            Lista de resultados (vazia se a busca semântica estiver
            desabilitada por incompatibilidade de dimensão). Pontos com
            embedding desatualizado são excluídos e contados em um aviso.
        """
        if self._search_disabled:
            logger.warning(
                "Busca semântica desabilitada: dimensão da coleção incompatível com o modelo de embedding atual.",
                extra={"collection": self.COLLECTION_NAME},
            )
            return []

        query_vector = self._embedding_provider.embed_query(query)

        must_conditions = self._current_model_conditions()
        if document_id:
            must_conditions.append(FieldCondition(key="document_id", match=MatchValue(value=document_id)))
        query_filter = Filter(must=must_conditions)

        results_obj = self.qdrant.query_points(
            collection_name=self.COLLECTION_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

        outdated_count = self._count_outdated_points()
        if outdated_count:
            logger.warning(
                f"{outdated_count} ponto(s) com embedding desatualizado foram excluídos da busca.",
                extra={"collection": self.COLLECTION_NAME, "outdated_count": outdated_count},
            )

        return [
            {
                "content": hit.payload["content"],
                "document_id": hit.payload["document_id"],
                "score": hit.score,
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
