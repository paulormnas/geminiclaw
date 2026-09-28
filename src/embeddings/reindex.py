"""Reindexação de coleções Qdrant após troca do modelo de embeddings local.

Implementa `geminiclaw embeddings reindex [--collection NOME] [--yes]`
(Roadmap V16 / ADR 011 §3, `openspec/changes/v16-local-embeddings/design.md`
"Reindexação"). Revetoriza os pontos de uma coleção usando o provedor de
embeddings local atualmente configurado, atualizando os metadados
(`embedding_model`, `embedding_version`, `embedding_dim`, `text_hash`) de
cada ponto.

**Atenção:** esta é uma operação sobre dados persistidos — apaga os vetores
existentes de cada ponto reescrito. Conforme `proposal.md` "Aprovações
necessárias" e AGENTS.md §1 regra 5, nunca deve ser executada contra um
Qdrant com dados reais sem aprovação explícita do pesquisador.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from src.config import QDRANT_URL
from src.embeddings.base import EmbeddingProvider, embedding_payload, get_embedding_provider
from src.logger import get_logger

logger = get_logger(__name__)

# Coleções do Qdrant que os indexadores locais sabem revetorizar. A coleção
# do grafo de conhecimento (V17) está fora do escopo desta mudança.
REINDEXABLE_COLLECTIONS: tuple[str, ...] = ("geminiclaw_knowledge", "geminiclaw_documents")


class CollectionNotFoundError(Exception):
    """A coleção alvo não existe no Qdrant configurado."""


@dataclass
class ReindexReport:
    """Resultado da reindexação de uma coleção.

    Attributes:
        collection: Nome da coleção reindexada.
        updated: Quantidade de pontos revetorizados com sucesso.
        skipped_no_text: Pontos ignorados por não terem texto de origem
            recuperável no payload.
        already_current: Pontos que já estavam no modelo/versão atuais e não
            precisaram ser reescritos.
        recreated_collection: True se a coleção foi recriada (mudança de
            dimensão) — nesse caso todos os pontos antigos foram descartados
            e `updated`/`skipped_no_text`/`already_current` são 0 (nada foi
            revetorizado; a fonte precisa ser reingerida).
        elapsed_seconds: Tempo total da operação.
    """

    collection: str
    updated: int = 0
    skipped_no_text: int = 0
    already_current: int = 0
    recreated_collection: bool = False
    elapsed_seconds: float = 0.0

    def summary(self) -> str:
        """Linha de relatório legível para exibição na CLI."""
        if self.recreated_collection:
            return (
                f"Coleção '{self.collection}': recriada vazia (dimensão do modelo mudou) "
                f"em {self.elapsed_seconds:.1f}s — reingestão da fonte é necessária para "
                "repovoá-la."
            )
        return (
            f"Coleção '{self.collection}': {self.updated} ponto(s) atualizados, "
            f"{self.already_current} já atualizados, {self.skipped_no_text} ignorado(s) "
            f"sem texto de origem ({self.elapsed_seconds:.1f}s)."
        )


def _make_client(url: str) -> QdrantClient:
    """Cria um `QdrantClient` a partir de uma URL/caminho/``:memory:``."""
    if url == ":memory:":
        return QdrantClient(location=":memory:")
    if url.startswith("http"):
        return QdrantClient(url=url)
    return QdrantClient(path=url)


class CollectionReindexer:
    """Revetoriza uma única coleção do Qdrant com o provedor de embeddings atual."""

    def __init__(
        self,
        collection: str,
        url: str = QDRANT_URL,
        embedding_provider: EmbeddingProvider | None = None,
        client: QdrantClient | None = None,
        batch_size: int = 64,
    ) -> None:
        """Inicializa o reindexador de uma coleção.

        Args:
            collection: Nome da coleção Qdrant (deve estar em
                `REINDEXABLE_COLLECTIONS`).
            url: URL/caminho do Qdrant (ignorado se `client` for informado).
            embedding_provider: Provedor a usar. Se omitido, usa o singleton
                do processo.
            client: Cliente Qdrant já construído (uso em testes).
            batch_size: Tamanho do lote para leitura (`scroll`) e escrita
                (`upsert`).

        Raises:
            ValueError: Se `collection` não estiver em `REINDEXABLE_COLLECTIONS`.
        """
        if collection not in REINDEXABLE_COLLECTIONS:
            raise ValueError(
                f"Coleção '{collection}' não é reindexável por este comando. "
                f"Coleções suportadas: {', '.join(REINDEXABLE_COLLECTIONS)}."
            )
        self.collection = collection
        self._provider = embedding_provider or get_embedding_provider()
        self._batch_size = batch_size
        self.client = client or _make_client(url)

    def collection_exists(self) -> bool:
        """Retorna True se a coleção existir no Qdrant configurado."""
        names = {c.name for c in self.client.get_collections().collections}
        return self.collection in names

    def _iter_all_points(self):
        """Itera todos os pontos da coleção (payload, sem vetores) via `scroll`."""
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                with_payload=True,
                with_vectors=False,
                limit=self._batch_size,
                offset=offset,
            )
            yield from points
            if offset is None:
                break

    def _is_outdated(self, payload: dict, info) -> bool:
        return payload.get("embedding_model") != info.model or payload.get("embedding_version") != info.version

    def count_outdated(self) -> int:
        """Conta pontos com `embedding_model`/`embedding_version` diferentes do provedor atual.

        Pontos sem esses metadados (ex.: os antigos vetores aleatórios) também
        contam como desatualizados.

        Raises:
            CollectionNotFoundError: Se a coleção não existir.
        """
        if not self.collection_exists():
            raise CollectionNotFoundError(self.collection)
        info = self._provider.info
        return sum(1 for p in self._iter_all_points() if self._is_outdated(p.payload or {}, info))

    def run(self) -> ReindexReport:
        """Executa a reindexação completa da coleção.

        Se a dimensão da coleção existente for diferente da dimensão do
        provedor atual, a coleção é recriada vazia (perda de dados — os
        pontos antigos são descartados; a fonte precisa ser reingerida pelo
        pipeline normal). Caso contrário, cada ponto desatualizado é
        revetorizado a partir do texto já presente em seu payload
        (`payload["content"]`) e reescrito com os novos metadados de
        embedding.

        Raises:
            CollectionNotFoundError: Se a coleção não existir.
        """
        start = time.monotonic()
        if not self.collection_exists():
            raise CollectionNotFoundError(self.collection)

        report = ReindexReport(collection=self.collection)
        info = self._provider.info
        current_dim = self.client.get_collection(self.collection).config.params.vectors.size

        if current_dim != info.dimension:
            logger.warning(
                "Dimensão do modelo de embedding mudou; recriando coleção (dados antigos descartados)",
                extra={"collection": self.collection, "old_dim": current_dim, "new_dim": info.dimension},
            )
            self.client.delete_collection(self.collection)
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=info.dimension, distance=Distance.COSINE),
            )
            report.recreated_collection = True
            report.elapsed_seconds = time.monotonic() - start
            return report

        pending: list[PointStruct] = []

        def _flush() -> None:
            if not pending:
                return
            texts = [p.payload["content"] for p in pending]
            vectors = self._provider.embed_documents(texts)
            batch = []
            for point, vector in zip(pending, vectors):
                payload = dict(point.payload)
                payload.update(embedding_payload(payload["content"], self._provider))
                batch.append(PointStruct(id=point.id, vector=vector, payload=payload))
            self.client.upsert(collection_name=self.collection, points=batch)
            report.updated += len(batch)
            pending.clear()

        for point in self._iter_all_points():
            payload = point.payload or {}
            if not self._is_outdated(payload, info):
                report.already_current += 1
                continue
            text = payload.get("content")
            if not text:
                report.skipped_no_text += 1
                logger.warning(
                    "Ponto sem texto de origem recuperável no payload; ignorado na reindexação",
                    extra={"collection": self.collection, "point_id": str(point.id)},
                )
                continue
            pending.append(PointStruct(id=point.id, vector=[], payload=payload))
            if len(pending) >= self._batch_size:
                _flush()
        _flush()

        report.elapsed_seconds = time.monotonic() - start
        return report


def reindex_collections(
    collections: list[str] | None = None,
    url: str = QDRANT_URL,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[ReindexReport]:
    """Reindexa uma ou mais coleções com o provedor de embeddings atual.

    Args:
        collections: Coleções a reindexar. Se omitido, reindexa todas as
            coleções em `REINDEXABLE_COLLECTIONS`.
        url: URL/caminho do Qdrant.
        embedding_provider: Provedor a usar. Se omitido, usa o singleton do
            processo (carrega o modelo uma única vez, reaproveitado entre
            coleções).

    Returns:
        Um `ReindexReport` por coleção processada.

    Raises:
        ValueError: Se alguma coleção em `collections` não for reindexável.
        CollectionNotFoundError: Se alguma coleção alvo não existir no Qdrant.
    """
    targets = collections or list(REINDEXABLE_COLLECTIONS)
    provider = embedding_provider or get_embedding_provider()
    reports = []
    for name in targets:
        reindexer = CollectionReindexer(name, url=url, embedding_provider=provider)
        reports.append(reindexer.run())
    return reports
