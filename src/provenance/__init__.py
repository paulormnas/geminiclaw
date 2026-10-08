"""Registro de execuções encadeado por hash (v18.5-execution-provenance, ADR 019 §4).

Não confundir com ``src.knowledge.provenance``, que trata da autoria das escritas no grafo (ADR 015 §4): este pacote
registra **execuções do sandbox**. O código de um não importa o do outro.
"""

from src.provenance.errors import ProvenanceError, ProvenanceUnavailable
from src.provenance.ledger import ExecutionLedger, get_ledger, set_ledger

__all__ = ["ExecutionLedger", "ProvenanceError", "ProvenanceUnavailable", "get_ledger", "set_ledger"]
