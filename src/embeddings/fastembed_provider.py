"""Provedor de embeddings local baseado em FastEmbed (ONNX, CPU).

Adequado ao Raspberry Pi 5: sem GPU, footprint de memória baixo (~90 MB em
RAM para o modelo padrão `sentence-transformers/all-MiniLM-L6-v2`),
carregado sob demanda e uma única vez por processo. Nenhuma chamada de rede é
feita durante o cálculo de embeddings — apenas, opcionalmente, no primeiro
download do artefato do modelo (desabilitado quando `EMBEDDING_OFFLINE=true`,
como no Raspberry Pi 5 após o pré-download feito por `scripts/setup_pi.sh`).
"""

from __future__ import annotations

import threading
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from typing import Any

from src.config import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_CACHE_DIR,
    EMBEDDING_MODEL,
    EMBEDDING_OFFLINE,
)
from src.embeddings.base import EmbeddingInfo, EmbeddingProvider
from src.logger import get_logger

logger = get_logger(__name__)


class FastEmbedProvider(EmbeddingProvider):
    """Provedor de embeddings local via `fastembed.TextEmbedding`.

    O modelo ONNX é carregado de forma preguiçosa (lazy) no primeiro uso e
    reutilizado por todas as chamadas subsequentes desta instância. O
    carregamento é protegido por lock para ser seguro sob uso concorrente
    (ex.: múltiplas skills chamando `embed_query` no mesmo processo).
    """

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        cache_dir: str = EMBEDDING_CACHE_DIR,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        offline: bool = EMBEDDING_OFFLINE,
    ) -> None:
        """Inicializa o provedor sem carregar o modelo (carregamento preguiçoso).

        Args:
            model_name: Identificador do modelo FastEmbed/HuggingFace a usar.
            cache_dir: Diretório de cache local dos artefatos do modelo.
            batch_size: Tamanho de lote usado internamente em `embed_documents`.
            offline: Se True, impede qualquer tentativa de download do
                modelo — falha explicitamente se o modelo não estiver em cache.
        """
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._batch_size = batch_size
        self._offline = offline
        self._model: Any = None
        self._dimension: int | None = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        """Carrega o modelo ONNX na primeira chamada (thread-safe, idempotente)."""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            logger.info(
                "Carregando modelo de embeddings local",
                extra={
                    "event": "embedding_model_load_start",
                    "model": self._model_name,
                    "cache_dir": self._cache_dir,
                    "offline": self._offline,
                },
            )
            from fastembed import TextEmbedding

            self._dimension = self._lookup_dimension(TextEmbedding)
            self._model = TextEmbedding(
                model_name=self._model_name,
                cache_dir=self._cache_dir,
                local_files_only=self._offline,
            )
            logger.info(
                "Modelo de embeddings carregado",
                extra={
                    "event": "embedding_model_load_done",
                    "model": self._model_name,
                    "dimension": self._dimension,
                },
            )

    def _lookup_dimension(self, text_embedding_cls: Any) -> int:
        """Resolve a dimensão do modelo configurado a partir do catálogo do FastEmbed.

        Args:
            text_embedding_cls: A classe `fastembed.TextEmbedding` (injetada para
                evitar um segundo import).

        Returns:
            Dimensão dos vetores produzidos pelo modelo configurado.

        Raises:
            RuntimeError: Se `EMBEDDING_MODEL` não constar no catálogo de
                modelos suportados pelo FastEmbed.
        """
        for entry in text_embedding_cls.list_supported_models():
            if entry.get("model") == self._model_name:
                return int(entry["dim"])
        raise RuntimeError(
            f"Modelo de embedding '{self._model_name}' não encontrado no catálogo do FastEmbed. "
            "Verifique EMBEDDING_MODEL no .env."
        )

    @property
    def info(self) -> EmbeddingInfo:
        """Metadados do modelo carregado (carrega o modelo sob demanda)."""
        self._ensure_loaded()
        assert self._dimension is not None
        return EmbeddingInfo(
            model=self._model_name,
            version=self._resolve_version(),
            dimension=self._dimension,
        )

    def _resolve_version(self) -> str:
        """Resolve a versão a registrar como metadado de cada vetor.

        Usa a versão instalada do pacote `fastembed` como proxy estável da
        versão do artefato do modelo: o FastEmbed não expõe um hash de
        revisão por modelo, mas fixamos a versão do pacote no `pyproject.toml`,
        o que já garante reprodutibilidade e permite detectar trocas de modelo
        entre execuções (Requisito "Versão do embedding como metadado").

        Returns:
            String de versão do pacote `fastembed`, ou "unknown" se não for
            possível resolvê-la (ex.: instalação editável sem metadados).
        """
        try:
            return pkg_version("fastembed")
        except PackageNotFoundError:
            return "unknown"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Gera embeddings para um lote de textos.

        Args:
            texts: Textos a vetorizar.

        Returns:
            Lista de vetores (listas de float), uma por texto de entrada, na
            mesma ordem. Lista vazia se `texts` for vazio (não carrega o
            modelo nesse caso).
        """
        if not texts:
            return []
        self._ensure_loaded()
        assert self._model is not None
        embeddings = self._model.embed(texts, batch_size=self._batch_size)
        return [vector.tolist() for vector in embeddings]

    def embed_query(self, text: str) -> list[float]:
        """Gera o embedding de uma consulta de busca.

        Args:
            text: Texto da consulta.

        Returns:
            Vetor de embedding da consulta.
        """
        self._ensure_loaded()
        assert self._model is not None
        vectors = list(self._model.query_embed(text))
        return vectors[0].tolist()
