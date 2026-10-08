"""Exceções do registro de execuções."""

from __future__ import annotations


class ProvenanceError(RuntimeError):
    """Falha do registro de execuções (mensagem acionável)."""


class ProvenanceUnavailable(ProvenanceError):
    """O armazenamento do registro não está disponível (banco fora do ar, tabela ausente)."""


class MetricNotRecorded(ProvenanceError):
    """A execução ou a métrica consultada não existe no registro (sem valor padrão)."""
