"""Aplicação da resposta ao pedido ``revisao_objetivo`` (v18.7-exploration-limits, 5.2 e 9).

No ``assisted`` e no ``semi`` o objetivo do plano nunca é aplicado: vira pedido ``confirmar_problema``
(``motivo = revisao_objetivo``). Aqui, ``autorizar`` consome o pedido e grava a revisão com o ``Actor`` pesquisador
derivado do pedido; ``negar`` só o consome. Só os tipos sem hipóteses concorrentes (``limiar`` e ``cobertura``) são
aplicados: a revisão para ``discriminacao`` exige as concorrentes e fica a cargo do pesquisador.
"""

from __future__ import annotations

from typing import Any

from src.knowledge.errors import GraphStoreError
from src.knowledge.projects import get_active_problem
from src.knowledge.provenance import Actor
from src.logger import get_logger

logger = get_logger(__name__)

DECISION = "confirmar_problema"
MOTIVE = "revisao_objetivo"
APPLICABLE = ("limiar", "cobertura")


class ObjectiveRevisionMixin:
    """Parte da ``ExplorationSession`` que aplica a resposta à revisão do objetivo."""

    _revision_proposals: dict[str, str] | None = None

    def remember_revision(self, reference: str, kind: str) -> None:
        """Guarda o tipo proposto para a referência do pedido (a resposta chega depois, em outro ciclo)."""
        self._revision_proposals = self._revision_proposals if self._revision_proposals is not None else {}
        self._revision_proposals[reference] = kind

    def apply_objective_revisions(self) -> None:
        """Aplica as respostas ``autorizar`` e ``negar`` já dadas (síncrono; falha nunca derruba a pesquisa)."""
        try:
            from src.gate.persistent_gate import session_gate

            gate = session_gate()
            answered = gate.answered_unconsumed(self._chain())  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Respostas de revisão indisponíveis", extra={"extra": {"erro": type(exc).__name__}})
            return
        for request in answered:
            if request.decisao != DECISION or request.motivo != MOTIVE:
                continue
            action = (request.resposta or {}).get("acao")
            if action == "negar":
                gate.mark_consumed(request.id)
            elif action == "autorizar":
                self._authorize_revision(gate, request)

    def _authorize_revision(self, gate: Any, request: Any) -> None:
        kind = (self._revision_proposals or {}).get(request.referencia)
        if kind not in APPLICABLE:
            # Sem a proposta em memória (sessão retomada) ou tipo que exige concorrentes: o pedido fica sem consumir.
            self._emit(  # type: ignore[attr-defined]
                "objetivo_nao_aplicado", {"tipo": str(kind)[:32], "motivo": "revisao_nao_aplicavel"}
            )
            return
        try:
            consumed = gate.consume_authorized(DECISION, request.referencia, self._chain())  # type: ignore[attr-defined]
            problem = get_active_problem(self.store, self.ctx.project_id)  # type: ignore[attr-defined]
            if problem is None:
                return
            new = dict(problem.properties.get("criterio_sucesso") or {})
            new.update({"tipo": kind, "definido_por": "pesquisador"})
            if kind == "cobertura":
                for key in ("alvo", "delta_min", "hipoteses_concorrentes"):
                    new.pop(key, None)
            self.store.update_node(  # type: ignore[attr-defined]
                problem.id, {"criterio_sucesso": new}, actor=Actor.under_request(consumed.id)
            )
            self._emit("objetivo_revisado", {"tipo": kind, "pedido_id": consumed.id})  # type: ignore[attr-defined]
        except (GraphStoreError, Exception) as exc:  # noqa: BLE001 - a recusa do gate ou do grafo não derruba a sessão
            logger.warning("Revisão do objetivo não aplicada", extra={"extra": {"erro": type(exc).__name__}})
