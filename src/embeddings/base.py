"""Interface e utilitários para provedores de embeddings locais.

Todo embedding usado pelo GeminiClaw é gerado localmente, nunca por meio de um
provedor remoto (ADR 011 §3 — "Provedores Agnósticos"). Este módulo define o
contrato `EmbeddingProvider` que qualquer backend deve implementar, além de
utilitários de hashing e metadados usados pelos indexadores do Qdrant.

Garantia estrutural: não existe (e não deve existir) uma fábrica de
embeddings que aceite URL de serviço externo. Cada implementação concreta
desta interface roda inteiramente no host.
"""

from __future__ import annotations

import hashlib
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EmbeddingInfo:
    """Metadados descritivos do modelo de embedding em uso.

    Attributes:
        model: Identificador do modelo (ex.: "sentence-transformers/all-MiniLM-L6-v2").
        version: Versão do artefato do modelo (revisão/hash do ONNX ou versão do
            pacote provedor), usada para detectar incompatibilidade entre vetores.
        dimension: Dimensão dos vetores produzidos pelo modelo.
    """

    model: str
    version: str
    dimension: int


class EmbeddingProvider(ABC):
    """Contrato para provedores de embeddings executados localmente.

    Implementações desta interface DEVEM rodar inteiramente no host (CPU ou
    GPU local) e NUNCA enviar texto ou vetores para um serviço externo. Os
    métodos são síncronos porque o cálculo é CPU-bound (ONNX Runtime);
    chamadores assíncronos devem usar `asyncio.to_thread`.
    """

    @property
    @abstractmethod
    def info(self) -> EmbeddingInfo:
        """Retorna os metadados do modelo carregado por este provedor."""
        raise NotImplementedError

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Gera embeddings para um lote de textos a serem indexados.

        Args:
            texts: Textos a vetorizar (chunks de documentos, trechos crawleados).

        Returns:
            Lista de vetores, na mesma ordem de `texts`. Lista vazia se
            `texts` for vazio.
        """
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Gera o embedding de uma consulta de busca.

        Args:
            text: Texto da consulta.

        Returns:
            Vetor de embedding da consulta.
        """
        raise NotImplementedError


_provider_singleton: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Retorna o provedor de embeddings singleton do processo.

    Cria o `FastEmbedProvider` na primeira chamada e reutiliza a mesma
    instância nas chamadas seguintes, evitando recarregar o modelo ONNX mais
    de uma vez por processo. O import da implementação concreta é feito de
    forma tardia para não obrigar o carregamento de `fastembed` em processos
    que não usam embeddings.

    Returns:
        A instância singleton de `EmbeddingProvider`.
    """
    global _provider_singleton
    if _provider_singleton is None:
        from src.embeddings.fastembed_provider import FastEmbedProvider

        _provider_singleton = FastEmbedProvider()
    return _provider_singleton


def reset_embedding_provider() -> None:
    """Reseta o singleton do provedor de embeddings.

    Uso exclusivo de testes — permite que cada teste injete seu próprio
    provedor (real ou falso) sem interferência do estado de outros testes.
    """
    global _provider_singleton
    _provider_singleton = None


def text_hash(text: str) -> str:
    """Calcula o hash SHA-256 de um texto normalizado.

    A normalização (Unicode NFC + `strip`) garante que o mesmo conteúdo
    semântico produza o mesmo hash independentemente de espaços incidentais
    ou da forma de normalização Unicode usada pela fonte do texto.

    Args:
        text: Texto de origem.

    Returns:
        Hash SHA-256 hexadecimal do texto normalizado.
    """
    normalized = unicodedata.normalize("NFC", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def embedding_payload(text: str, provider: EmbeddingProvider | None = None) -> dict[str, Any]:
    """Monta os metadados de embedding a gravar no payload de um ponto do Qdrant.

    Args:
        text: Texto de origem do trecho vetorizado.
        provider: Provedor a usar para obter os metadados do modelo. Se
            omitido, usa o singleton do processo (`get_embedding_provider`).

    Returns:
        Dicionário com as chaves `embedding_model`, `embedding_version`,
        `embedding_dim` e `text_hash`.
    """
    info = (provider or get_embedding_provider()).info
    return {
        "embedding_model": info.model,
        "embedding_version": info.version,
        "embedding_dim": info.dimension,
        "text_hash": text_hash(text),
    }
