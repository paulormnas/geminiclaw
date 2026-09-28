"""Pacote de embeddings locais do GeminiClaw (Roadmap V16 / ADR 011 §3).

Todo embedding usado pelo GeminiClaw é gerado localmente — nunca enviado a um
provedor externo (Google, OpenAI, Anthropic ou qualquer outro). Este pacote
define a interface `EmbeddingProvider` e a implementação local baseada em
FastEmbed (ONNX, CPU), usada pelos indexadores do Qdrant (`search_deep` e
`document_processor`).
"""

from src.embeddings.base import (
    EmbeddingInfo,
    EmbeddingProvider,
    embedding_payload,
    get_embedding_provider,
    reset_embedding_provider,
    text_hash,
)

__all__ = [
    "EmbeddingInfo",
    "EmbeddingProvider",
    "embedding_payload",
    "get_embedding_provider",
    "reset_embedding_provider",
    "text_hash",
]
