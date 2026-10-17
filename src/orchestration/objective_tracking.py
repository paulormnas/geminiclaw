"""Acompanhamento do objetivo tipado na sessão e política ao atingi-lo (v18.7-exploration-limits, design §5 e §6).

``ObjectiveTracker`` avalia o objetivo do ``Problema`` ao fim de cada ciclo (``objective.evaluate``), grava
o marco ``objetivo_atingido`` e emite o evento na primeira vez da sessão, aplica a política ``parar`` / ``perguntar`` /
``continuar`` e registra os pedidos dos desfechos da discriminação e da cobertura. Substitui ``check_solution``,
``confirm_solution`` e ``declined_solutions``.

O estado (memória do critério, atingimento, política efetiva da sessão, desfechos já relatados) vai no checkpoint da
sessão (``exploracao_estado``) para a retomada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from src import config
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore
from src.knowledge.objective import (
    DESFECHO_AGUARDA_FISICO,
    DESFECHO_TODAS_CONTRARIADAS,
    DESFECHO_VARIAS_COMPATIVEIS,
    SATURACAO_SO_AVISO,
    CycleView,
    GraphObjectiveReader,
    ObjectiveError,
    ObjectiveMemory,
    ObjectiveState,
    effective_type,
    evaluate,
)
from src.knowledge.projects import get_active_problem
from src.knowledge.provenance import Actor
from src.logger import get_logger

logger = get_logger(__name__)

_ORCHESTRATOR = Actor(kind="orquestrador")
POLICIES = ("parar", "perguntar", "continuar")
DECISION_STOP = "encerrar"
DECISION_KEEP = "seguir"
DECISION_WAIT = "aguardar"

#: Pedido (``decidir_continuidade``) de cada desfecho: motivo, opções e pergunta (design §5.2, §5.3, §10).
CONTINUITY_REQUESTS: dict[str, tuple[str, tuple[str, ...], str]] = {
    DESFECHO_VARIAS_COMPATIVEIS: (
        "varias_compativeis", ("aceitar_conjunto", "orientar", "continuar", "parar"),
        "Várias hipóteses concorrentes seguem compatíveis e nenhum experimento planejado as distingue. Aceitar o "
        "conjunto, orientar a pesquisa, continuar ou parar?",
    ),
    DESFECHO_AGUARDA_FISICO: (
        "aguarda_experimento_fisico", ("orientar", "continuar", "parar"),
        "O único experimento que distinguiria as hipóteses restantes exige bancada ou equipamento fora do sandbox. "
        "Orientar, continuar ou parar?",
    ),
    "cobertura": (
        "cobertura_saturada", ("objetivo_atingido", "orientar", "continuar", "parar"),
        "A novidade de hipóteses por ciclo caiu abaixo do mínimo. Declarar o objetivo atingido, orientar, continuar "
        "ou parar?",
    ),
}


@dataclass(frozen=True)
class Achievement:
    """O que foi atingido, para o evento, o marco e o pedido ao pesquisador."""

    reference: str
    tipo: str
    desfecho: str | None = None
    hipotese_id: str | None = None
    resultado_id: str | None = None
    valor: float | None = None
    politica: str = "parar"

    def to_dict(self) -> dict[str, Any]:
        return {
            "referencia": self.reference, "tipo": self.tipo, "desfecho": self.desfecho,
            "hipotese_id": self.hipotese_id, "resultado_id": self.resultado_id, "valor": self.valor,
            "politica": self.politica,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "Achievement | None":
        if not isinstance(raw, dict) or not raw.get("referencia"):
            return None
        valor = raw.get("valor")
        return cls(
            reference=str(raw["referencia"])[:128], tipo=str(raw.get("tipo") or "limiar")[:32],
            desfecho=raw.get("desfecho") if isinstance(raw.get("desfecho"), str) else None,
            hipotese_id=raw.get("hipotese_id") if isinstance(raw.get("hipotese_id"), str) else None,
            resultado_id=raw.get("resultado_id") if isinstance(raw.get("resultado_id"), str) else None,
            valor=float(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) else None,
            politica=raw.get("politica") if raw.get("politica") in POLICIES else "parar",
        )


Confirmer = Callable[[Achievement], "str | None"]
ContinuityRequester = Callable[[str, str, tuple[str, ...], str], None]
Emitter = Callable[[str, dict[str, Any]], None]


class ObjectiveTracker:
    """Avalia o objetivo a cada ciclo e aplica a política ao atingi-lo."""

    def __init__(
        self,
        store_getter: Callable[[], GraphStore],
        project_id: str,
        session_id: str,
        *,
        mode: str,
        emit: Emitter,
        confirmer: Confirmer,
        requester: ContinuityRequester,
    ) -> None:
        """
        Args:
            store_getter: Abre o grafo.
            project_id: Projeto da sessão.
            session_id: Sessão (proveniência do marco).
            mode: ``SessionMode``; define a política quando o ``Problema`` não declara.
            emit: Telemetria ``(tipo, payload)``.
            confirmer: Pedido ``decidir_objetivo_atingido``: ``encerrar``, ``continuar`` ou ``None`` (pendente).
            requester: Registra um pedido ``decidir_continuidade`` ``(motivo, referencia, opcoes, pergunta)``.
        """
        self._store_getter = store_getter
        self._project_id = project_id
        self._session_id = session_id
        self._mode = mode
        self._emit = emit
        self._confirm = confirmer
        self._request = requester
        self.memory = ObjectiveMemory()
        self.achievement: Achievement | None = None
        self.session_policy: str | None = None  # ``continuar`` depois da resposta do pesquisador
        self.reported: set[str] = set()
        self.last_state: ObjectiveState | None = None
        self._feedback = ""

    # ------------------------------------------------------------------ política

    def default_policy(self) -> str:
        return "perguntar" if self._mode == "assisted" else "parar"

    def effective_policy(self, criterion: dict[str, Any] | None) -> str:
        """Política da sessão: a escolha ``continuar`` do pesquisador, a do ``Problema`` ou o padrão do modo."""
        if self.session_policy is not None:
            return self.session_policy
        declared = (criterion or {}).get("ao_atingir_objetivo")
        return declared if declared in POLICIES else self.default_policy()

    # ------------------------------------------------------------------ avaliação

    def evaluate(self, cycle: CycleView, service: Any) -> ObjectiveState | None:
        """Avalia o objetivo no fim do ciclo; ``None`` quando o ``Problema`` não tem objetivo avaliável."""
        store = self._store_getter()
        problem = get_active_problem(store, self._project_id)
        criterion = problem.properties.get("criterio_sucesso") if problem is not None else None
        kind = effective_type(criterion if isinstance(criterion, dict) else None)
        if problem is None or kind is None:
            return None
        reader = GraphObjectiveReader(store, service, self._project_id, problem.id)
        try:
            state = evaluate(reader, dict(criterion), self.memory, cycle)
        except ObjectiveError as exc:
            logger.warning("Objetivo não avaliável", extra={"extra": {"motivo": str(exc)[:160]}})
            return None
        self.memory = state.memory
        self.last_state = state
        self._feedback = ""
        if state.atingido and self.achievement is None:
            self._record_achievement(store, problem.id, dict(criterion), state)
        self._report_outcomes(state, cycle)
        return state

    def _record_achievement(
        self, store: GraphStore, problem_id: str, criterion: dict[str, Any], state: ObjectiveState
    ) -> None:
        d = state.detalhes
        reference = str(d.get("resultado_id") or d.get("hipotese_id") or problem_id)
        policy = self.effective_policy(criterion)
        self.achievement = Achievement(
            reference=reference, tipo=state.tipo, desfecho=state.desfecho,
            hipotese_id=d.get("hipotese_id"), resultado_id=d.get("resultado_id"),
            valor=d.get("valor"), politica=policy,
        )
        self._emit("objetivo_atingido", {k: v for k, v in self.achievement.to_dict().items() if v is not None})
        mark = {
            "em": datetime.now(timezone.utc).isoformat(), "sessao_id": self._session_id, "tipo": state.tipo,
            **{k: v for k, v in (
                ("resultado_id", self.achievement.resultado_id), ("hipotese_id", self.achievement.hipotese_id),
                ("valor", self.achievement.valor),
            ) if v is not None},
        }
        try:
            node = store.get_node(problem_id)
            marks = list((node.properties.get("objetivo_atingido") if node else None) or [])
            store.update_node(problem_id, {"objetivo_atingido": [*marks, mark]}, actor=_ORCHESTRATOR)
        except GraphStoreError as exc:
            logger.warning("Marco de objetivo atingido não gravado", extra={"extra": {"erro": type(exc).__name__}})

    def _report_outcomes(self, state: ObjectiveState, cycle: CycleView) -> None:
        """Eventos e pedidos dos desfechos que não atingem o objetivo (uma vez por desfecho e referência)."""
        if state.desfecho == DESFECHO_TODAS_CONTRARIADAS and self._once("todas_contrariadas"):
            self._emit("objetivo_desfecho", {"tipo": state.tipo, "desfecho": state.desfecho, **_ids(state)})
        if state.desfecho == DESFECHO_TODAS_CONTRARIADAS:
            self._feedback = (
                "OBJETIVO DE DISCRIMINAÇÃO: todas as hipóteses concorrentes foram contrariadas pelos resultados "
                "validados. Proponha hipóteses novas que expliquem o que foi observado."
            )
        elif state.desfecho in (DESFECHO_VARIAS_COMPATIVEIS, DESFECHO_AGUARDA_FISICO):
            compatible = ",".join(state.detalhes.get("compativeis", []))
            key = f"{state.desfecho}:{state.detalhes.get('subtarefa', '')}:{compatible}"
            if self._once(key):
                payload = {"tipo": state.tipo, "desfecho": state.desfecho, **_ids(state)}
                if state.detalhes.get("subtarefa"):
                    payload["subtarefa"] = str(state.detalhes["subtarefa"])[:120]
                self._emit("objetivo_desfecho", payload)
                motivo, options, question = CONTINUITY_REQUESTS[state.desfecho]
                self._request(motivo, key[:128], options, question)
        if state.tipo == "cobertura" and state.saturacao == SATURACAO_SO_AVISO and self._once("cobertura_aviso"):
            window = config.COVERAGE_NOVELTY_WINDOW
            self._emit("cobertura_aviso", {"taxa": state.detalhes.get("taxa"), "janela": window})
            motivo, options, question = CONTINUITY_REQUESTS["cobertura"]
            self._request(motivo, "cobertura", options, question)

    def _once(self, key: str) -> bool:
        if key in self.reported:
            return False
        self.reported.add(key)
        return True

    def feedback(self) -> str:
        """Texto para o replanejamento (``todas_contrariadas`` pede hipóteses novas); vazio sem desfecho."""
        return self._feedback

    # ------------------------------------------------------------------ decisão

    def decision(self, criterion: dict[str, Any] | None = None) -> str:
        """``encerrar``, ``seguir`` ou ``aguardar`` a resposta do pesquisador, conforme a política."""
        if self.achievement is None:
            return DECISION_KEEP
        policy = self.effective_policy(criterion)
        if policy == "parar":
            return DECISION_STOP
        if policy == "continuar":
            return DECISION_KEEP
        answer = self._confirm(self.achievement)
        if answer == "encerrar":
            return DECISION_STOP
        if answer == "continuar":
            self.session_policy = "continuar"
            return DECISION_KEEP
        return DECISION_WAIT

    # ------------------------------------------------------------------ checkpoint

    def snapshot(self) -> dict[str, Any]:
        return {
            "memoria": self.memory.to_dict(),
            "atingido": self.achievement.to_dict() if self.achievement else None,
            "politica_sessao": self.session_policy,
            "relatados": sorted(self.reported)[:50],
        }

    def restore(self, raw: Any) -> None:
        """Estado do checkpoint (dado não confiável): valor inválido volta ao padrão, nunca levanta."""
        if not isinstance(raw, dict):
            return
        self.memory = ObjectiveMemory.from_dict(raw.get("memoria"))
        self.achievement = Achievement.from_dict(raw.get("atingido"))
        self.session_policy = "continuar" if raw.get("politica_sessao") == "continuar" else None
        self.reported = {str(v)[:128] for v in (raw.get("relatados") or []) if isinstance(v, str)}


def _ids(state: ObjectiveState) -> dict[str, Any]:
    d = state.detalhes
    return {k: d[k] for k in ("contrariadas", "compativeis") if d.get(k)}
