"""Provedor de embeddings falso e determinístico, para uso exclusivo em testes.

Nunca carrega o modelo FastEmbed real: gera vetores a partir do hash SHA-256
do texto de entrada, garantindo que o mesmo texto sempre produza o mesmo
vetor (determinismo) sem depender de download/carregamento de modelo ONNX.

Isso substitui, nos testes, o antigo `_generate_mock_embedding` que existia
em código de *produção* — a mudança v16-local-embeddings remove aquele mock
do runtime; este utilitário é o duplo de teste esperado no lugar dele.
"""

from __future__ import annotations

import hashlib

from src.embeddings.base import EmbeddingInfo, EmbeddingProvider


class FakeEmbeddingProvider(EmbeddingProvider):
    """Provedor determinístico (hash → vetor) para testes unitários e de integração leve."""

    def __init__(
        self,
        dimension: int = 384,
        model: str = "fake/test-embedding",
        version: str = "test-1",
    ) -> None:
        """Inicializa o provedor falso.

        Args:
            dimension: Dimensão dos vetores gerados.
            model: Nome do "modelo" reportado em `info`.
            version: Versão reportada em `info`.
        """
        self._info = EmbeddingInfo(model=model, version=version, dimension=dimension)

    @property
    def info(self) -> EmbeddingInfo:
        return self._info

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        """Deriva um vetor determinístico de tamanho `dimension` a partir do hash do texto."""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        repeated = (digest * ((self._info.dimension // len(digest)) + 1))[: self._info.dimension]
        return [(b / 127.5) - 1.0 for b in repeated]
