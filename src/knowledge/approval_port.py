"""Interface comum de aprovação do pesquisador usada pelo laço de hipóteses (v18.7-hypothesis-linking, tarefa 0.5).

``ApprovalPort`` é o ``Approver`` de sempre (lote de itens -> decisões; item fora do dicionário continua pendente) mais
``previously_approved``, que confere se o pesquisador já aprovou a hipótese. A implementação de produção sobre o gate
persistente (``PersistentGateApprover``) é de ``v18.7-persistent-human-gate``; antes dela, ``NoGateApprovalPort``
envolve o ``Approver`` injetado e nunca confirma uma aprovação anterior.

``previously_approved`` MUST ler o gate persistente, nunca a trilha de auditoria do grafo (parecer de segurança).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.knowledge.hypothesis_cycle import ApprovalDecision, ApprovalItem, Approver


@runtime_checkable
class ApprovalPort(Protocol):
    """Pede e confere a aprovação de hipóteses pelo pesquisador."""

    def __call__(self, items: "list[ApprovalItem]") -> "dict[str, ApprovalDecision]":
        """Mesma assinatura do ``Approver``; o item fora do dicionário continua pendente."""
        ...

    def previously_approved(self, hypothesis_id: str, session_chain: Iterable[str]) -> bool:
        """Verdadeiro só com pedido ``aprovar_hipotese`` desse id, ``autorizada`` e resolvido por humano."""
        ...


class NoGateApprovalPort:
    """Implementação provisória: envolve o ``Approver`` injetado; ``previously_approved`` devolve sempre ``False``.

    No ``assisted``, a reabertura de uma hipótese do sistema volta então sempre a ``proposta``.
    """

    def __init__(self, approver: "Approver | None") -> None:
        self._approver = approver

    def __call__(self, items: "list[ApprovalItem]") -> "dict[str, ApprovalDecision]":
        return self._approver(items) if self._approver is not None else {}

    def previously_approved(self, hypothesis_id: str, session_chain: Iterable[str]) -> bool:
        return False


def as_approval_port(approver: "Approver | ApprovalPort | None") -> ApprovalPort:
    """O próprio ``ApprovalPort`` quando já é um; senão o ``NoGateApprovalPort`` sobre o ``Approver``."""
    if approver is not None and callable(getattr(approver, "previously_approved", None)):
        return approver  # type: ignore[return-value]
    return NoGateApprovalPort(approver)  # type: ignore[arg-type]
