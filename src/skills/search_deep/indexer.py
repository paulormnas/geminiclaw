import asyncio
import uuid
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from src.config import QDRANT_CHECK_COMPATIBILITY, QDRANT_URL
from src.embeddings.base import EmbeddingProvider, embedding_payload, get_embedding_provider
from src.logger import get_logger

from .crawler import CrawledPage

logger = get_logger(__name__)


class VectorIndexer:
    """Gerencia o índice vetorial no Qdrant, usando embeddings locais (Roadmap V16).

    Os vetores são gerados por um `EmbeddingProvider` local (nunca por um
    provedor remoto — ADR 011 §3). Cada ponto gravado carrega os metadados de
    versão do embedding (`embedding_model`, `embedding_version`,
    `embedding_dim`, `text_hash`), usados para detectar incompatibilidade
    entre o modelo configurado e os vetores já indexados.
    """

    COLLECTION_NAME = "geminiclaw_knowledge"

    def __init__(self, url: str = QDRANT_URL, embedding_provider: Optional[EmbeddingProvider] = None):
        """Inicializa o indexador e garante a coleção do Qdrant.

        Args:
            url: URL do Qdrant (``http(s)://...``), caminho local, ou
                ``":memory:"`` para um cliente em memória (testes).
            embedding_provider: Provedor de embeddings a usar. Se omitido,
                usa o singleton do processo (`get_embedding_provider`).
        """
        self._embedding_provider = embedding_provider or get_embedding_provider()
        self._search_disabled = False
        if url == ":memory:":
            self.client = QdrantClient(location=":memory:")
        elif url.startswith("http"):
            self.client = QdrantClient(url=url, check_compatibility=QDRANT_CHECK_COMPATIBILITY)
        else:
            self.client = QdrantClient(path=url)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Garante que a coleção existe e é compatível com o provedor de embeddings atual.

        Se a coleção já existir com uma dimensão diferente da do provedor
        configurado, a coleção NÃO é recriada automaticamente (perda de
        dados) — a busca semântica é desabilitada para esta instância e um
        erro orientando `geminiclaw embeddings reindex` é registrado
        (Requisito "Proteção contra mistura de modelos").
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
            collections = self.client.get_collections().collections
            existing = next((c for c in collections if c.name == self.COLLECTION_NAME), None)

            if existing is None:
                logger.info(f"Criando coleção {self.COLLECTION_NAME}")
                self.client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(size=provider_dimension, distance=Distance.COSINE),
                )
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
                return

            collection_dimension = self.client.get_collection(self.COLLECTION_NAME).config.params.vectors.size
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

            logger.info(f"Coleção {self.COLLECTION_NAME} já existe e é compatível com o modelo atual.")
        except Exception as e:
            error_msg = str(e)
            if "Connection refused" in error_msg or "111" in error_msg:
                logger.error(
                    "Não foi possível conectar ao Qdrant. Verifique se o container está rodando e é "
                    f"compatível com o sistema (Page Size 16KB no Pi 5): {e}"
                )
            else:
                logger.error(f"Erro ao verificar/criar coleção Qdrant: {e}")

    async def index_pages(self, pages: List[CrawledPage]) -> None:
        """Indexa as páginas no Qdrant com chunking e embeddings locais.

        Args:
            pages: Páginas crawleadas a indexar.
        """
        if self._search_disabled:
            logger.warning(
                "Indexação ignorada: coleção desabilitada por incompatibilidade de dimensão de embedding.",
                extra={"collection": self.COLLECTION_NAME},
            )
            return

        chunk_records: list[tuple[str, int, str, CrawledPage]] = []
        for page in pages:
            chunks = self._chunk_text(page.content)
            for i, chunk in enumerate(chunks):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{page.url}#{i}"))
                chunk_records.append((point_id, i, chunk, page))

        if not chunk_records:
            return

        texts = [chunk for _, _, chunk, _ in chunk_records]
        vectors = await asyncio.to_thread(self._embedding_provider.embed_documents, texts)

        points = []
        for (point_id, chunk_index, chunk, page), vector in zip(chunk_records, vectors):
            payload = {
                "url": page.url,
                "domain": page.domain,
                "title": page.title,
                "content": chunk,
                "data_type": page.content_type,
                "crawled_at": page.crawled_at,
                "chunk_index": chunk_index,
                **embedding_payload(chunk, self._embedding_provider),
            }
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        self.client.upsert(collection_name=self.COLLECTION_NAME, points=points)
        logger.info(
            f"Indexados {len(points)} chunks de {len(pages)} página(s)",
            extra={"pages": len(pages), "chunks": len(points)},
        )

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
            total = self.client.count(collection_name=self.COLLECTION_NAME).count
            current = self.client.count(
                collection_name=self.COLLECTION_NAME,
                count_filter=Filter(must=self._current_model_conditions()),
            ).count
            if not isinstance(total, int) or not isinstance(current, int):
                return 0
            return max(0, total - current)
        except Exception as e:
            logger.debug(f"Não foi possível contar pontos de embedding desatualizados: {e}")
            return 0

    async def search(self, query: str, limit: int = 5, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Realiza busca vetorial no Qdrant usando o provedor de embeddings local.

        Args:
            query: Texto da consulta.
            limit: Número máximo de resultados.
            domain: Filtro opcional por domínio.

        Returns:
            Lista de resultados (vazia se a busca semântica estiver
            desabilitada por incompatibilidade de dimensão). Pontos com
            embedding desatualizado (modelo/versão diferentes do atual) são
            excluídos e contados em um aviso de log.
        """
        if self._search_disabled:
            logger.warning(
                "Busca semântica desabilitada: dimensão da coleção incompatível com o modelo de embedding atual.",
                extra={"collection": self.COLLECTION_NAME},
            )
            return []

        query_vector = await asyncio.to_thread(self._embedding_provider.embed_query, query)

        must_conditions = self._current_model_conditions()
        if domain:
            must_conditions.append(FieldCondition(key="domain", match=MatchValue(value=domain)))
        query_filter = Filter(must=must_conditions)

        results_obj = self.client.query_points(
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
                "url": hit.payload["url"],
                "title": hit.payload["title"],
                "score": hit.score,
                "metadata": hit.payload,
            }
            for hit in results_obj.points
        ]

    async def reindex(self, domain: str) -> None:
        """Deleta todos os pontos pertencentes ao domínio especificado para permitir reindexação.

        Args:
            domain: Domínio cujos pontos devem ser removidos do índice.
        """
        logger.info(f"Removendo todos os pontos do domínio {domain} do índice...")
        self.client.delete(
            collection_name=self.COLLECTION_NAME,
            points_selector=Filter(must=[FieldCondition(key="domain", match=MatchValue(value=domain))]),
        )
        logger.info(f"Pontos do domínio {domain} removidos com sucesso.")

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas da coleção."""
        collection_info = self.client.get_collection(self.COLLECTION_NAME)
        return {
            "points_count": collection_info.points_count,
            "status": str(collection_info.status),
        }


if __name__ == "__main__":
    import asyncio

    from .indexer_cli import main

    asyncio.run(main())
