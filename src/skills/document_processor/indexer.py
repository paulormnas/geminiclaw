import asyncio
import time
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from src.config import QDRANT_CHECK_COMPATIBILITY, QDRANT_URL
from src.db import get_connection
from src.embeddings.base import EmbeddingProvider, embedding_payload, get_embedding_provider
from src.logger import get_logger
from src.skills.document_processor.chunker import DocumentChunk
from src.skills.document_processor.registry_store import DocumentRegistry, PostgresDocumentRegistry

logger = get_logger(__name__)

# Chunks vetorizados por lote (limita memória e permite respeitar o prazo da indexação).
EMBED_BATCH = 32


class DocumentIndexer:
    """Indexa documentos processados no Qdrant e PostgreSQL, usando embeddings locais.

    Os vetores são gerados por um `EmbeddingProvider` local (Roadmap V16 /
    ADR 011 §3). Cada ponto gravado carrega os metadados de versão do
    embedding, usados para detectar incompatibilidade entre o modelo
    configurado e os vetores já indexados.
    """

    COLLECTION_NAME = "geminiclaw_documents"

    def __init__(
        self,
        url: str = QDRANT_URL,
        embedding_provider: Optional[EmbeddingProvider] = None,
        registry: Optional[DocumentRegistry] = None,
    ):
        """Inicializa o indexador e garante a coleção do Qdrant.

        Args:
            url: URL do Qdrant (``http(s)://...``), caminho local, ou
                ``":memory:"`` para um cliente em memória (testes).
            embedding_provider: Provedor de embeddings a usar. Se omitido,
                usa o singleton do processo (`get_embedding_provider`).
            registry: Registro relacional de documentos e trechos. Se omitido, usa o PostgreSQL.
        """
        self.registry: DocumentRegistry = registry or PostgresDocumentRegistry(lambda: get_connection())
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
                self._ensure_payload_indexes()
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
                return
            self._ensure_payload_indexes()
        except Exception as e:
            logger.error(f"Erro ao verificar/criar coleção Qdrant para documentos: {e}")

    def _ensure_payload_indexes(self) -> None:
        """Cria (de forma idempotente e aditiva) os índices de payload ``projeto_id`` e ``insumo_id``."""
        for field_name in ("projeto_id", "insumo_id"):
            try:
                self.qdrant.create_payload_index(
                    collection_name=self.COLLECTION_NAME, field_name=field_name, field_schema="keyword"
                )
            except Exception as e:  # noqa: BLE001 - índice é otimização; a busca funciona sem ele
                logger.warning(
                    "Índice de payload não criado",
                    extra={"field": field_name, "error": type(e).__name__},
                )

    async def _index_vectors(self, chunks: List[DocumentChunk], deadline: Optional[float] = None) -> int:
        """Indexa no Qdrant para busca semântica, usando embeddings locais.

        O vetor é gerado a partir de ``chunk.embed_text`` (cabeçalho enriquecido + trecho), quando
        informado; o payload guarda só o trecho em ``content``. A vetorização é feita em lotes e
        para quando ``deadline`` (instante de ``time.monotonic``) é ultrapassado.

        Args:
            chunks: Chunks já registrados.
            deadline: Instante limite opcional.

        Returns:
            Quantidade de chunks vetorizados (0 se a coleção está desabilitada).

        Raises:
            Exception: Falha do modelo de embedding ou do Qdrant (quem chama decide o estado pendente).
        """
        if not chunks:
            return 0

        if self._search_disabled:
            logger.warning(
                "Indexação vetorial ignorada: coleção desabilitada por incompatibilidade de dimensão de embedding.",
                extra={"collection": self.COLLECTION_NAME},
            )
            return 0

        done = 0
        for start in range(0, len(chunks), EMBED_BATCH):
            if deadline is not None and start > 0 and time.monotonic() >= deadline:
                break
            batch = chunks[start:start + EMBED_BATCH]
            texts = [chunk.embed_text or chunk.content for chunk in batch]
            vectors = await asyncio.to_thread(self._embedding_provider.embed_documents, texts)

            points = []
            for chunk, text, vector in zip(batch, texts, vectors):
                payload = {
                    "document_id": chunk.document_id,
                    "content": chunk.content,
                    "format": chunk.metadata.get("format", ""),
                    "chunk_index": chunk.chunk_index,
                    **chunk.payload_extra,
                    **embedding_payload(text, self._embedding_provider),
                }
                points.append(PointStruct(id=chunk.chunk_id, vector=vector, payload=payload))

            self.qdrant.upsert(collection_name=self.COLLECTION_NAME, points=points)
            done += len(batch)
        return done

    async def vectorize(self, chunks: List[DocumentChunk], deadline: Optional[float] = None) -> bool:
        """Vetoriza os chunks sem levantar: ``False`` quando Qdrant/embedding falham ou o prazo acaba.

        Returns:
            ``True`` se todos os chunks foram vetorizados; ``False`` deixa o documento ``pendente``.
        """
        try:
            return await self._index_vectors(chunks, deadline) == len(chunks)
        except Exception as e:  # noqa: BLE001 - a sessão não depende do Qdrant (vetorização pendente)
            logger.warning(
                "Vetorização falhou; documento fica pendente",
                extra={"collection": self.COLLECTION_NAME, "error": type(e).__name__},
            )
            return False

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

    def search(
        self,
        query: str,
        limit: int = 5,
        document_id: Optional[str] = None,
        projeto_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Busca semântica no Qdrant usando o provedor de embeddings local.

        Args:
            query: Texto da consulta.
            limit: Número máximo de resultados.
            document_id: Filtro opcional por documento.
            projeto_id: Restringe a busca aos pontos do projeto; ``None`` busca em todos os projetos.

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
        if projeto_id:
            must_conditions.append(FieldCondition(key="projeto_id", match=MatchValue(value=projeto_id)))
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
                "projeto_id": hit.payload.get("projeto_id"),
                "titulo": hit.payload.get("titulo"),
                "tipo_insumo": hit.payload.get("tipo_insumo"),
                "tipo_ponto": hit.payload.get("tipo_ponto"),
                "insumo_id": hit.payload.get("insumo_id"),
            }
            for hit in results_obj.points
        ]

    def list_documents(self, limit: int = 10, projeto_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lista os documentos ingeridos; ``projeto_id`` restringe ao projeto (``None`` lista todos)."""
        return self.registry.list_documents(limit, projeto_id)

    def get_document_info(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Recupera detalhes de um documento."""
        return self.registry.get(document_id)
