"""Invólucros somente leitura do grafo e do Qdrant para a consulta do terminal (v18.7-session-events-terminal, §1.6).

A consulta do terminal lê o projeto enquanto a sessão escreve. Três barreiras valem juntas: o grafo pelo papel
``knowledge_reader`` em transação ``READ ONLY`` (``read_query``), o banco relacional com
``default_transaction_read_only = on`` (variável ``PGOPTIONS`` do processo filho) e estes invólucros, que **levantam**
em qualquer método que escreva. Eles protegem contra o código da consulta, não contra a rede (o Qdrant publicado sem
autenticação é pendência anterior, fora do escopo).
"""

from __future__ import annotations

from typing import Any


class ReadOnlyViolation(RuntimeError):
    """A consulta tentou escrever no grafo, no banco ou no Qdrant."""


#: Métodos do ``GraphStore`` que só leem. Qualquer outro nome levanta ``ReadOnlyViolation``.
GRAPH_READ_METHODS = frozenset({
    "get_node", "find_nodes", "list_nodes", "neighbors", "project_subgraph", "read_query", "audit_history",
})
#: Métodos do ``QdrantClient`` que só leem.
QDRANT_READ_METHODS = frozenset({
    "search", "query_points", "scroll", "count", "retrieve", "get_collection", "get_collections", "collection_exists",
})


class _Guard:
    """Delegação por allowlist: o que não está na lista levanta, inclusive atributos de escrita futuros."""

    _label = ""
    _allowed: frozenset[str] = frozenset()

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name not in self._allowed:
            raise ReadOnlyViolation(f"{self._label} somente leitura: '{name}' não é permitido na consulta do terminal.")
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise ReadOnlyViolation(f"{self._label} somente leitura: não é possível alterar '{name}'.")


class ReadOnlyGraphStore(_Guard):
    _label = "Grafo"
    _allowed = GRAPH_READ_METHODS


class ReadOnlyQdrant(_Guard):
    _label = "Qdrant"
    _allowed = QDRANT_READ_METHODS
