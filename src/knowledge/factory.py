"""Construção do ``GraphStore`` de produção a partir da configuração."""

from __future__ import annotations

from src import config
from src.knowledge.graph_store import AgeGraphStore, GraphStore


def open_graph_store() -> GraphStore:
    """Abre o ``AgeGraphStore`` com as variáveis de ``src.config``.

    Returns:
        Store pronto para uso.

    Raises:
        RuntimeError: Se ``KNOWLEDGE_READER_DATABASE_URL`` não está configurada.
    """
    if not config.KNOWLEDGE_READER_DATABASE_URL:
        raise RuntimeError(
            "KNOWLEDGE_READER_DATABASE_URL não configurada; defina-a no .env (ver .env.example)."
        )
    return AgeGraphStore(
        config.KNOWLEDGE_GRAPH_NAME,
        reader_conninfo=config.KNOWLEDGE_READER_DATABASE_URL,
        read_timeout_ms=config.KNOWLEDGE_READ_TIMEOUT_MS,
    )
