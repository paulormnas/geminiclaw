"""Filtro de defesa em profundidade para ``GraphStore.read_query`` (ADR 015 §5).

A garantia real de que ``read_query`` não escreve no grafo é o papel de banco
``knowledge_reader`` (sem privilégio de escrita) executando em transação
``READ ONLY`` (ver ``scripts/migrations/v17_001_knowledge_graph.sql`` e
``AgeGraphStore.read_query``). Este filtro textual é uma camada adicional,
não a garantia principal — por isso aceita falsos positivos (recusar texto
legítimo que contenha as palavras) em troca de simplicidade e previsibilidade.
"""

from __future__ import annotations

import re

from src.knowledge.errors import ReadOnlyQueryViolation

_FORBIDDEN_KEYWORDS = ("CREATE", "MERGE", "SET", "DELETE", "REMOVE")
_KEYWORD_PATTERN = re.compile(r"\b(" + "|".join(_FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE)


def reject_unsafe_read_query(cypher: str) -> None:
    """Recusa consultas Cypher que contenham palavras-chave de escrita.

    Args:
        cypher: Texto da consulta Cypher livre.

    Raises:
        ReadOnlyQueryViolation: Se qualquer palavra-chave de escrita
            (``CREATE``, ``MERGE``, ``SET``, ``DELETE``, ``REMOVE``)
            aparecer como palavra isolada no texto.
    """
    match = _KEYWORD_PATTERN.search(cypher)
    if match:
        raise ReadOnlyQueryViolation(match.group(1).upper())
