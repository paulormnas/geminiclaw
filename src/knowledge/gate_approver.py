"""Aprovação de hipóteses pelo gate persistente (v18.7-persistent-human-gate, design §2.4).

``PersistentGateApprover`` é o ``ApprovalPort`` de produção: cria um pedido ``aprovar_hipotese`` por item
(idempotente) e devolve só as decisões que o terminal já respondeu e que a sessão consumiu. Item sem resposta
continua pendente; a sessão não espera por ele. Fica em ``knowledge`` (e não em ``gate``) porque usa
``ApprovalItem`` e ``ApprovalDecision``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.gate.persistent_gate import PersistentGate
from src.gate.types import GateAuthorizationRefused, GatePendingLimitReached
from src.knowledge.hypothesis_cycle import (
    ACTION_APPROVE,
    ACTION_EDIT,
    ACTION_REJECT,
    ApprovalDecision,
    ApprovalItem,
)
from src.logger import get_logger
from src.utils.display_text import sanitize_line

logger = get_logger(__name__)

DECISAO = "aprovar_hipotese"
OPCOES = (ACTION_APPROVE, ACTION_REJECT, ACTION_EDIT)
_ENUNCIADO_PREVIA = 300


def _question(item: ApprovalItem) -> str:
    """Texto do pedido a partir de campos estruturados; o enunciado vem rotulado como texto de agente (dado)."""
    source = f", enunciado {item.enunciado_fonte}" if item.enunciado_fonte else ""
    return (
        f"Aprovar a hipótese {item.id} (origem {item.origem}{source})? "
        f"[texto de agente] {sanitize_line(item.enunciado, _ENUNCIADO_PREVIA)}"
    )


class PersistentGateApprover:
    """``ApprovalPort`` sobre o gate persistente, ligado a uma sessão e à cadeia dela."""

    def __init__(
        self,
        gate: PersistentGate,
        session_id: str,
        session_chain: Iterable[str] | None = None,
        project_id: str | None = None,
    ) -> None:
        self._gate = gate
        self._session_id = session_id
        self._chain = list(session_chain) if session_chain else [session_id]
        self._project_id = project_id

    def __call__(self, items: list[ApprovalItem]) -> dict[str, ApprovalDecision]:
        decisions: dict[str, ApprovalDecision] = {}
        for item in items:
            try:
                # Na retomada, o pedido da sessão anterior (pendente ou já respondido) é o desta hipótese.
                req = self._gate.find_in_chain(DECISAO, item.id, self._chain) or self._gate.request(
                    DECISAO, item.id, _question(item), OPCOES, session_id=self._session_id, project_id=self._project_id
                )
            except GatePendingLimitReached:
                logger.warning("Pedidos pendentes demais: a hipótese segue pendente", extra={"extra": {"id": item.id}})
                continue
            if req.estado == "pendente" or req.consumido:
                continue
            resposta = req.resposta or {}
            if req.estado == "negada":
                self._gate.mark_consumed(req.id)
                decisions[item.id] = ApprovalDecision(ACTION_REJECT, motivo=str(resposta.get("motivo", "")))
                continue
            try:
                consumed = self._gate.consume_authorized(DECISAO, item.id, self._chain)
            except GateAuthorizationRefused as exc:
                logger.warning("Autorização recusada", extra={"extra": {"id": item.id, "motivo": exc.motivo}})
                continue
            resposta = consumed.resposta or {}
            if resposta.get("acao") == ACTION_EDIT:
                decisions[item.id] = ApprovalDecision(ACTION_EDIT, enunciado=str(resposta.get("enunciado", "")))
            else:
                decisions[item.id] = ApprovalDecision(ACTION_APPROVE)
        return decisions

    def previously_approved(self, hypothesis_id: str, session_chain: Iterable[str]) -> bool:
        """Verdadeiro só com pedido ``aprovar_hipotese`` desse id, autorizado por humano, na cadeia da sessão."""
        return self._gate.was_authorized(DECISAO, hypothesis_id, session_chain)


CONFIRM_DECISAO = "decidir_objetivo_atingido"
CONFIRM_OPCOES = ("encerrar", "continuar")


class PersistentGateConfirmer:
    """Pedido ``decidir_objetivo_atingido`` (política ``perguntar``): ``encerrar``, ``continuar`` ou ``None``.

    O processo da sessão não lê o terminal. O pedido leva a referência do que foi atingido (resultado ou hipótese) e só
    vale uma vez (``consume_authorized``).
    """

    def __init__(
        self,
        gate: PersistentGate,
        session_id: str,
        session_chain: Iterable[str] | None = None,
        project_id: str | None = None,
    ) -> None:
        self._gate = gate
        self._session_id = session_id
        self._chain = list(session_chain) if session_chain else [session_id]
        self._project_id = project_id

    def __call__(self, achievement: Any) -> str | None:
        reference = str(achievement.reference or "-")
        value = f"{achievement.valor:g}" if achievement.valor is not None else "-"
        question = (
            f"Objetivo ({sanitize_line(str(achievement.tipo), 32)}) atingido em {sanitize_line(reference, 64)} "
            f"(valor {value}). Encerrar a pesquisa agora ou continuar explorando?"
        )
        try:
            req = self._gate.find_in_chain(CONFIRM_DECISAO, reference, self._chain) or self._gate.request(
                CONFIRM_DECISAO, reference, question, CONFIRM_OPCOES,
                session_id=self._session_id, project_id=self._project_id,
            )
        except GatePendingLimitReached:
            return None
        if req.estado == "pendente" or req.consumido:
            return None
        try:
            consumed = self._gate.consume_authorized(CONFIRM_DECISAO, reference, self._chain)
        except GateAuthorizationRefused as exc:
            logger.warning("Autorização recusada", extra={"extra": {"id": reference, "motivo": exc.motivo}})
            return None
        action = (consumed.resposta or {}).get("acao")
        return action if action in CONFIRM_OPCOES else None
