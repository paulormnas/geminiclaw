"""Restrições de direção na ``ExplorationSession`` (v18.7-exploration-limits, design §8).

``RestrictionsMixin`` aplica as restrições ativas ao plano (retirada por abordagem ou similaridade), registra os casos
duvidosos apontados pelo Validator como pedidos ao pesquisador e aplica as respostas: ``restringir`` cria a restrição
(a sessão consome o pedido autorizado) e ``liberar`` deixa a subtarefa voltar.
"""

from __future__ import annotations

from typing import Any

from src.knowledge import restrictions as rules
from src.logger import get_logger
from src.orchestration.exploration_linking import DROP_DOUBT, DROP_RESTRICTED
from src.utils.display_text import sanitize_line

logger = get_logger(__name__)

DECISION = "restringir_direcao"
MOTIVE = "restricao_duvidosa"
_MAX_CONTEXT = 20


def _approach_names(task: Any) -> list[str]:
    approach = getattr(task, "approach", None)
    name = approach.get("nome") if isinstance(approach, dict) else None
    return [str(name)] if name else []


class RestrictionsMixin:
    """Parte da ``ExplorationSession`` que cuida das restrições (usa ``store``, ``cycle``, ``_emit``, ``_index``)."""

    _doubts: list[dict[str, str]] | None = None
    _doubt_context: dict[str, dict[str, Any]] | None = None
    _released: set[str] | None = None

    # ------------------------------------------------------------------ leitura

    def _active_rules(self) -> list[rules.Restriction]:
        try:
            return rules.active_restrictions(self.store, self.ctx.project_id)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - sem leitura do grafo não há restrição a aplicar nem a inventar
            logger.warning("Restrições indisponíveis", extra={"extra": {"erro": type(exc).__name__}})
            return []

    @staticmethod
    def _as_data(rule: rules.Restriction) -> dict[str, Any]:
        return {
            "id": rule.id, "direcao": rule.direcao, "categoria": rule.categoria, "abordagens": list(rule.abordagens),
            "escopo": rule.escopo,
        }

    def restrictions_for_validation(self) -> list[dict[str, Any]]:
        """Restrições ativas como dado para o Validator do plano (síncrono); vazio quando não há."""
        return [self._as_data(r) for r in self._active_rules()][:_MAX_CONTEXT]

    def note_plan_doubts(self, doubts: Any) -> None:
        """Casos duvidosos do plano aprovado (``restricoes_duvidosas`` do Validator), a tratar em ``prepare_cycle``."""
        self._doubts = [d for d in doubts or [] if isinstance(d, dict)]

    # ------------------------------------------------------------------ aplicação

    def apply_restrictions(self, live: list[Any], dropped: dict[str, str]) -> None:
        """Retira as hipóteses que caem em restrição ativa e as subtarefas em dúvida (antes da seleção).

        Atualiza ``dropped`` (``task_name`` -> código) e entrega às subtarefas de teste que seguem as restrições
        ativas para a revisão (``restricoes_contexto``).
        """
        self._apply_answers()
        active = self._active_rules()
        data = [self._as_data(r) for r in active][:_MAX_CONTEXT]
        if active:
            self._withdraw_matching(live, dropped, active)
        for task in live:
            if task.task_name not in dropped and getattr(task, "hypothesis_id", ""):
                task.restricoes_contexto = data
        self._register_doubts(live, dropped, {r.id: r for r in active})

    def _withdraw_matching(self, live: list[Any], dropped: dict[str, str], active: list[rules.Restriction]) -> None:
        from src.knowledge.service import KnowledgeService

        service = KnowledgeService(self.store)  # type: ignore[attr-defined]
        by_hypothesis: dict[str, list[Any]] = {}
        for task in live:
            hid = getattr(task, "hypothesis_id", "")
            if hid and task.task_name not in dropped and getattr(task, "papel_decidido", "") == "teste":
                by_hypothesis.setdefault(hid, []).append(task)
        for hid, tasks in by_hypothesis.items():
            node = self.cycle.hypothesis(hid)  # type: ignore[attr-defined]
            if node is None or node.properties.get("status") == "abandonada":
                continue
            found = rules.match_hypothesis(self.store, service, self._index, node, active)  # type: ignore[attr-defined]
            if found is None:
                continue
            rules.withdraw_hypothesis(self.store, hid, found.restricao_id)  # type: ignore[attr-defined]
            self._emit(  # type: ignore[attr-defined]
                "restricao_retirada",
                {
                    "restricao_id": found.restricao_id, "hipotese_id": hid, "criterio": found.criterio,
                    "similaridade": found.similaridade,
                },
            )
            for task in tasks:
                dropped[task.task_name] = DROP_RESTRICTED

    # ------------------------------------------------------------------ casos duvidosos

    def _register_doubts(
        self, live: list[Any], dropped: dict[str, str], active: dict[str, rules.Restriction]
    ) -> None:
        doubts, self._doubts = self._doubts or [], None
        self._released = self._released if self._released is not None else set()
        self._doubt_context = self._doubt_context if self._doubt_context is not None else {}
        by_name = {t.task_name: t for t in live}
        for doubt in doubts:
            name, rid = doubt.get("task_name", ""), doubt.get("restricao_id", "")
            ref = f"{rid}:{name}"[:128]
            task, rule = by_name.get(name), active.get(rid)
            if task is None or rule is None or name in dropped or ref in self._released:
                continue
            dropped[name] = DROP_DOUBT
            self._doubt_context[ref] = {
                "direcao": sanitize_line(str(getattr(task, "hypothesis", "") or name), 400),
                "categoria": rule.categoria,
                "abordagens": _approach_names(task),
            }
            self._request_doubt(ref, name, rule, doubt.get("motivo", ""))

    def _request_doubt(self, ref: str, task_name: str, rule: rules.Restriction, reason: str) -> None:
        question = (
            f"A subtarefa '{sanitize_line(task_name, 80)}' parece cair na restrição "
            f"'{sanitize_line(rule.direcao, 160)}' ({sanitize_line(reason, 160)}). Restringir esta direção "
            "ou liberar a subtarefa?"
        )
        self._gate_request(DECISION, ref, question, ("restringir", "liberar"), MOTIVE)

    def report_violation(self, task_name: str, restriction_id: str, hypothesis_text: str = "") -> None:
        """Violação apontada pela revisão: o resultado já saiu não validado; registra o pedido ao pesquisador."""
        ref = f"{restriction_id}:{task_name}"[:128]
        question = (
            f"A execução de '{sanitize_line(task_name, 80)}' seguiu uma direção vedada pela restrição "
            f"{sanitize_line(restriction_id, 64)}; o resultado não foi validado. Restringir a direção ou liberar?"
        )
        self._doubt_context = self._doubt_context if self._doubt_context is not None else {}
        self._doubt_context.setdefault(
            ref, {"direcao": sanitize_line(hypothesis_text or task_name, 400), "categoria": "recurso", "abordagens": []}
        )
        self._emit("restricao_violada", {"restricao_id": restriction_id, "subtarefa": task_name[:128]})  # type: ignore[attr-defined]
        self._gate_request(DECISION, ref, question, ("restringir", "liberar"), MOTIVE)

    def _gate_request(self, decision: str, ref: str, question: str, options: tuple[str, ...], motive: str) -> None:
        try:
            from src.gate.persistent_gate import session_gate

            session_gate().request(
                decision, ref, question, options, motivo=motive, session_id=self.ctx.session_id,  # type: ignore[attr-defined]
                project_id=self.ctx.project_id,  # type: ignore[attr-defined]
            )
        except Exception as exc:  # noqa: BLE001 - sem o pedido o evento ainda registra o caso
            logger.warning("Pedido de restrição não registrado", extra={"extra": {"erro": type(exc).__name__}})

    # ------------------------------------------------------------------ respostas

    def _apply_answers(self) -> None:
        try:
            from src.gate.persistent_gate import session_gate

            gate = session_gate()
            answered = gate.answered_unconsumed(self._chain())  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Respostas de restrição indisponíveis", extra={"extra": {"erro": type(exc).__name__}})
            return
        self._released = self._released if self._released is not None else set()
        for request in answered:
            if request.decisao != DECISION or request.motivo != MOTIVE:
                continue
            action = (request.resposta or {}).get("acao")
            if action == "liberar":
                self._released.add(request.referencia)
                gate.mark_consumed(request.id)
            elif action == "restringir":
                self._create_from_answer(gate, request)

    def _create_from_answer(self, gate: Any, request: Any) -> None:
        context = (self._doubt_context or {}).get(request.referencia)
        if context is None:
            # A sessão foi retomada sem o contexto do caso: o pedido fica sem consumir; o comando `project restrict`
            # cobre a decisão.
            logger.warning("Restrição não criada: contexto do caso ausente", extra={"extra": {"pedido": request.id}})
            return
        try:
            rules.create_from_request(
                self.store, gate, self._chain(), request.referencia, self.ctx.project_id,  # type: ignore[attr-defined]
                direcao=context["direcao"], categoria=context["categoria"], abordagens=context["abordagens"],
            )
        except Exception as exc:  # noqa: BLE001 - a recusa do grafo ou do gate nunca derruba a pesquisa
            logger.warning("Restrição não criada", extra={"extra": {"erro": type(exc).__name__}})
