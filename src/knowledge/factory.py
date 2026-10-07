"""Construção do ``GraphStore`` de produção a partir da configuração."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src import config
from src.knowledge.graph_store import AgeGraphStore, GraphStore

if TYPE_CHECKING:
    from src.knowledge.semantic_runtime import SemanticRuntime


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


def open_knowledge_runtime() -> "SemanticRuntime | None":
    """Abre o ``SemanticRuntime`` de produção (store indexado, índice e fila de similaridade).

    Returns:
        O runtime, ou ``None`` quando ``KNOWLEDGE_SEMANTIC_INDEX_ENABLED`` está desligado (use o store cru).

    Raises:
        RuntimeError: Se ``KNOWLEDGE_READER_DATABASE_URL`` não está configurada.
    """
    if not config.KNOWLEDGE_SEMANTIC_INDEX_ENABLED:
        return None
    from src.knowledge.semantic_runtime import open_runtime

    return open_runtime()


def open_graph_store(*, reconcile: bool = False) -> GraphStore:
    """Abre o ``GraphStore`` de produção.

    Com ``KNOWLEDGE_SEMANTIC_INDEX_ENABLED`` (padrão), devolve o store **indexado**
    (``IndexedGraphStore``): toda escrita (inclusive as do vocabulário controlado) passa
    pelo gancho de vetorização e pela geração de candidatos de similaridade; falhas do
    índice nunca desfazem o nó. Com a variável desligada, devolve o store cru.

    Args:
        reconcile: Se verdadeiro (início de sessão), reconcilia o índice semântico com o grafo **antes** de devolver o
            store (``reconcile_on_session_start``; nunca levanta). Ignorado com o índice desligado.

    Returns:
        Store pronto para uso.

    Raises:
        RuntimeError: Se ``KNOWLEDGE_READER_DATABASE_URL`` não está configurada.
    """
    runtime = open_knowledge_runtime()
    if runtime is None:
        return open_raw_graph_store()
    if reconcile:
        from src.knowledge.semantic_runtime import reconcile_on_session_start

        reconcile_on_session_start(runtime)
    return runtime.store
