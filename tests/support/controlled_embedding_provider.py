"""Provedor de embeddings controlável, para testes que exigem similaridades exatas.

Mapeia **marcadores** (substrings do texto canônico) para vetores definidos pelo
teste, de modo que o cosseno entre dois nós seja conhecido de antemão (ex.: 0,65).
Texto sem marcador conhecido falha alto — nunca devolve vetor inventado.
"""

from __future__ import annotations

import math

from src.embeddings.base import EmbeddingInfo, EmbeddingProvider


def pair_vectors(dimension: int, axis: int, cosine: float) -> tuple[list[float], list[float]]:
    """Dois vetores unitários com o cosseno dado, em um par de eixos isolado.

    Pares com ``axis`` diferentes são ortogonais entre si (cosseno 0).

    Args:
        dimension: Dimensão total (>= 2 * (axis + 1)).
        axis: Índice do par (usa os eixos ``2*axis`` e ``2*axis + 1``).
        cosine: Cosseno desejado entre os dois vetores.
    """
    a = [0.0] * dimension
    b = [0.0] * dimension
    a[2 * axis] = 1.0
    b[2 * axis] = cosine
    b[2 * axis + 1] = math.sqrt(1.0 - cosine**2)
    return a, b


class ControlledEmbeddingProvider(EmbeddingProvider):
    """Provedor determinístico: vetor definido por marcador presente no texto."""

    def __init__(
        self,
        vectors: dict[str, list[float]] | None = None,
        *,
        dimension: int = 8,
        model: str = "controlled/test",
        version: str = "1",
    ) -> None:
        self.vectors: dict[str, list[float]] = dict(vectors or {})
        self._info = EmbeddingInfo(model=model, version=version, dimension=dimension)
        self.embedded_texts: list[str] = []

    @property
    def info(self) -> EmbeddingInfo:
        return self._info

    def set_info(self, *, model: str | None = None, version: str | None = None) -> None:
        """Simula a troca de modelo/versão (mesma dimensão)."""
        self._info = EmbeddingInfo(
            model=model or self._info.model, version=version or self._info.version, dimension=self._info.dimension
        )

    def _vector(self, text: str) -> list[float]:
        for marker, vector in self.vectors.items():
            if marker in text:
                return list(vector)
        raise KeyError(f"Nenhum marcador do ControlledEmbeddingProvider casa com o texto: {text!r}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embedded_texts.extend(texts)
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
