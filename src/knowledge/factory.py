"""Construção do ``GraphStore`` de produção a partir da configuração."""

from __future__ import annotations

from src import config
from src.knowledge.graph_store import AgeGraphStore, GraphStore


def open_raw_graph_store() -> AgeGraphStore:
    """Abre o ``AgeGraphStore`` cru (sem o gancho do índice semântico).

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


def open_graph_store() -> GraphStore:
    """Abre o ``GraphStore`` de produção.

    Com ``KNOWLEDGE_SEMANTIC_INDEX_ENABLED`` (padrão), devolve o store **indexado**
    (``IndexedGraphStore``): toda escrita (inclusive as do vocabulário controlado) passa
    pelo gancho de vetorização e pela geração de candidatos de similaridade; falhas do
    índice nunca desfazem o nó. Com a variável desligada, devolve o store cru.

    Returns:
        Store pronto para uso.

    Raises:
        RuntimeError: Se ``KNOWLEDGE_READER_DATABASE_URL`` não está configurada.
    """
    if not config.KNOWLEDGE_SEMANTIC_INDEX_ENABLED:
        return open_raw_graph_store()
    from src.knowledge.semantic_runtime import open_runtime

    return open_runtime().store
