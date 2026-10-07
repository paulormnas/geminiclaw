"""Governança, prioridade e avaliação das hipóteses de um ciclo (v18-hypothesis-loop, design §3 a §5 e §8).

Tudo aqui é **determinístico** (sem LLM, exceto o ``custo_estimado`` que o Researcher declara) e passa pelo
``GraphStore``:

- ``HypothesisCycle.select``: governança por ``SessionMode`` (``assisted`` exige aprovação do pesquisador para
  hipóteses de agentes; ``semi``/``auto`` executam as ``HYPOTHESES_PER_CYCLE`` de maior prioridade);
- prioridade ``0,35·relevância + 0,30·apoio_prévio + 0,20·novidade + 0,15·(1 − custo)`` (pesos configuráveis);
- ``sync_statuses``: ``validada``/``refutada`` **só** a partir do veredito calculado (nunca por julgamento de LLM);
- ``evaluate_decisions``: ``Decisao.resultado_posterior`` preenchido deterministicamente;
- ``check_solution``: critério "solução encontrada" (veredito moderado **e** melhor resultado *validado* no alvo).

A aprovação em lote do ``assisted`` é uma ação do **pesquisador no terminal** (``terminal_approver``): a resposta de
``ask_researcher`` (inclusive a do consultor), de agente ou de documento nunca aprova hipótese — sem TTY nada é
aprovado e as hipóteses ficam pendentes (falha fechada).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from src import config
from src.knowledge import opportunities
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.graph_views import sanitize_text
from src.knowledge.hypotheses import (
    CONCLUDED_STATUSES,
    OPEN_STATUSES,
    ORIGEM_PESQUISADOR,
    STATUS_ABANDONADA,
    STATUS_EM_TESTE,
    STATUS_PROPOSTA,
    STATUS_REFUTADA,
    STATUS_VALIDADA,
)
from src.knowledge.normalization import clean_free_text, normalize_domain_term
from src.knowledge.projects import get_active_problem
from src.knowledge.provenance import Actor
from src.knowledge.service import KnowledgeService
from src.knowledge.verdict import Attempt, Criterion
from src.logger import get_logger

logger = get_logger(__name__)

PESQUISADOR = Actor(kind="pesquisador")
ORQUESTRADOR = Actor(kind="orquestrador")

CUSTO_VALUES = {"baixo": 0.0, "medio": 0.5, "alto": 1.0}
NEUTRAL = 0.5
STRONG_FAILURE_VERDICT = -0.5
STRONG_FAILURE_SIMILARITY = 0.8
SESSION_MODES = ("assisted", "semi", "auto")
MAX_APPROVAL_BATCH = 20
_MAX_SCAN = 1000
_MAX_MOTIVO = 500

ACTION_APPROVE = "aprovar"
ACTION_REJECT = "rejeitar"
ACTION_EDIT = "editar"


@dataclass(frozen=True)
class ApprovalItem:
    """Hipótese apresentada ao pesquisador no lote de aprovação (texto de agente: dado não confiável)."""

    id: str
    enunciado: str
    justificativa: str
    origem: str
    prioridade: float


@dataclass(frozen=True)
class ApprovalDecision:
    """Decisão do pesquisador sobre uma hipótese do lote."""

    action: str  # aprovar | rejeitar | editar
    motivo: str = ""
    enunciado: str = ""


Approver = Callable[[list[ApprovalItem]], dict[str, ApprovalDecision]]


@dataclass
class Selection:
    """Resultado da governança de um ciclo.

    Attributes:
        execute: IDs das hipóteses que podem executar neste ciclo.
        pending_approval: IDs que aguardam o pesquisador (``assisted`` sem resposta) — **não** executam.
        deferred: IDs de menor prioridade (``semi``/``auto``) que ficam ``proposta`` para um próximo ciclo.
        rejected: ID -> motivo das rejeitadas pelo pesquisador (viraram ``abandonada``).
        excluded: IDs que não executam por já estarem concluídas ou abandonadas.
        priorities: ID -> prioridade calculada.
    """

    execute: list[str] = field(default_factory=list)
    pending_approval: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)
    excluded: list[str] = field(default_factory=list)
    priorities: dict[str, float] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        """Contagens para a telemetria (nenhum texto de pesquisa)."""
        return {
            "executadas": len(self.execute),
            "pendentes_de_aprovacao": len(self.pending_approval),
            "adiadas": len(self.deferred),
            "rejeitadas": len(self.rejected),
            "excluidas": len(self.excluded),
        }


@dataclass(frozen=True)
class SolutionStatus:
    """Resultado de ``check_solution`` (valores numéricos e IDs; nada de texto de pesquisa)."""

    found: bool
    hypothesis_id: str | None = None
    verdict: float | None = None
    best_value: float | None = None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _hypothesis_text(node: Node) -> str:
    from src.knowledge.semantic_index import canonical_text

    return canonical_text("Hipotese", node.properties) or str(node.properties.get("enunciado", ""))


class HypothesisCycle:
    """Operações de grafo do ciclo de hipóteses de uma sessão (prioridade, governança, status, parada)."""

    def __init__(
        self,
        store: GraphStore,
        *,
        project_id: str,
        session_id: str,
        index: Any | None = None,
        service: KnowledgeService | None = None,
        weights: tuple[float, float, float, float] | None = None,
        per_cycle: int | None = None,
    ) -> None:
        """Inicializa o ciclo.

        Args:
            store: Porta única do grafo (de produção, o store indexado).
            project_id: Projeto da sessão.
            session_id: Sessão mestra.
            index: ``SemanticIndex`` (relevância/novidade/apoio prévio); sem ele, os termos semânticos ficam neutros.
            service: ``KnowledgeService`` (veredito); padrão: um novo sobre ``store``.
            weights: Pesos da prioridade (padrão: ``HYPOTHESIS_PRIORITY_WEIGHTS``).
            per_cycle: Hipóteses por ciclo no ``semi``/``auto`` (padrão: ``HYPOTHESES_PER_CYCLE``).
        """
        self._store = store
        self._project_id = project_id
        self._session_id = session_id
        self._index = index
        self._service = service or KnowledgeService(store)
        self._weights = weights or config.HYPOTHESIS_PRIORITY_WEIGHTS
        self._per_cycle = per_cycle if per_cycle is not None else config.HYPOTHESES_PER_CYCLE

    # ------------------------------------------------------------------ leitura

    def hypothesis(self, node_id: str) -> Node | None:
        """``Hipotese`` do projeto (``None`` se não existe ou é de outro projeto)."""
        node = self._store.get_node(node_id)
        if node is None or node.label != "Hipotese" or node.properties.get("projeto_id") != self._project_id:
            return None
        return node

    def project_hypotheses(self) -> list[Node]:
        """Hipóteses do projeto (limitadas)."""
        return self._store.find_nodes("Hipotese", {"projeto_id": self._project_id}, limit=_MAX_SCAN)

    # ------------------------------------------------------------------ prioridade

    def _relevance(self, node: Node, problem: Node | None) -> float:
        if self._index is None or problem is None:
            return NEUTRAL
        try:
            found = self._index.similarity_to(_hypothesis_text(node), [problem.id])
        except Exception as exc:  # noqa: BLE001 - sem índice o termo fica neutro
            logger.debug("Relevância indisponível", extra={"extra": {"erro": type(exc).__name__}})
            return NEUTRAL
        return _clamp01(found[problem.id]) if problem.id in found else NEUTRAL

    def _novelty(self, node: Node) -> float:
        tested: list[Node] = []
        for status in CONCLUDED_STATUSES:
            found = self._store.find_nodes(
                "Hipotese", {"projeto_id": self._project_id, "status": status}, limit=_MAX_SCAN
            )
            tested.extend(n for n in found if n.id != node.id)
        if not tested:
            return 1.0
        if self._index is not None:
            try:
                sims = self._index.similarity_to(_hypothesis_text(node), [n.id for n in tested])
                return _clamp01(1.0 - max(sims.values(), default=0.0))
            except Exception as exc:  # noqa: BLE001
                logger.debug("Novidade semântica indisponível", extra={"extra": {"erro": type(exc).__name__}})
        key = normalize_domain_term(str(node.properties.get("enunciado", "")))
        same = any(normalize_domain_term(str(n.properties.get("enunciado", ""))) == key for n in tested)
        return 0.0 if same else 1.0

    def _prior_support(self, node: Node, problem: Node | None) -> float:
        """``max(0, veredito)`` da melhor descoberta ``FUNCIONOU_PARA`` da abordagem em problemas similares.

        0,5 quando não há experiência; 0 quando há ``FALHOU_PARA`` forte (veredito <= -0,5) em problema com
        similaridade >= 0,8. Só enxerga problemas do projeto ou ``compartilhavel``.
        """
        approaches = [n for n in self._neighbors_out(node.id, "PROPOE") if n.label == "Abordagem"]
        if not approaches or problem is None:
            return NEUTRAL
        similar = self._similar_problems(problem)
        best: float | None = None
        for approach in approaches:
            canonical = self._service.canonical_approach(approach.id)
            for rel in ("FUNCIONOU_PARA", "FALHOU_PARA"):
                sub = self._store.neighbors(canonical, [rel], direction="out", depth=1)
                for edge in sub.edges:
                    if edge.src_id != canonical or edge.rel_type != rel:
                        continue
                    if edge.properties.get("status") == "contestada":
                        continue
                    sim = similar.get(edge.dst_id)
                    if sim is None:
                        continue
                    verdict = self._discovery_verdict(edge.properties.get("descoberta_id"))
                    if verdict is None:
                        continue
                    if rel == "FALHOU_PARA" and verdict <= STRONG_FAILURE_VERDICT and sim >= STRONG_FAILURE_SIMILARITY:
                        return 0.0
                    if rel == "FUNCIONOU_PARA":
                        best = max(best if best is not None else 0.0, max(0.0, verdict))
        return NEUTRAL if best is None else _clamp01(best)

    def _neighbors_out(self, node_id: str, rel: str) -> list[Node]:
        sub = self._store.neighbors(node_id, [rel], direction="out", depth=1)
        by_id = {n.id: n for n in sub.nodes}
        return [by_id[e.dst_id] for e in sub.edges if e.src_id == node_id and e.rel_type == rel and e.dst_id in by_id]

    def _similar_problems(self, problem: Node) -> dict[str, float]:
        """``Problema`` do projeto (similaridade 1) e os similares visíveis, com a similaridade."""
        out = {problem.id: 1.0}
        if self._index is None:
            return out
        try:
            for hit in self._index.similar(
                node_id=problem.id, labels=["Problema"], min_score=0.0, limit=50, projeto_id=self._project_id
            ):
                out.setdefault(hit.node_id, float(hit.score))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Problemas similares indisponíveis", extra={"extra": {"erro": type(exc).__name__}})
        return out

    def _discovery_verdict(self, discovery_id: Any) -> float | None:
        if not isinstance(discovery_id, str):
            return None
        node = self._store.get_node(discovery_id)
        value = node.properties.get("veredito") if node is not None else None
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def priority(self, node: Node, custo: str = "medio") -> float:
        """Prioridade da hipótese (``0..1``) pela fórmula do design §5.

        Args:
            node: A ``Hipotese``.
            custo: ``custo_estimado`` declarado pelo Researcher (``baixo``/``medio``/``alto``).
        """
        problem = get_active_problem(self._store, self._project_id)
        w_rel, w_prior, w_new, w_cost = self._weights
        cost = CUSTO_VALUES.get(custo, CUSTO_VALUES["medio"])
        return round(
            w_rel * self._relevance(node, problem)
            + w_prior * self._prior_support(node, problem)
            + w_new * self._novelty(node)
            + w_cost * (1.0 - cost),
            6,
        )

    # ------------------------------------------------------------------ governança

    def select(
        self,
        hypothesis_ids: list[str],
        *,
        mode: str,
        approver: Approver | None = None,
        custos: dict[str, str] | None = None,
    ) -> Selection:
        """Governança por ``SessionMode`` das hipóteses de um ciclo.

        - ``pesquisador``: sempre executa (qualquer modo);
        - ``assisted``: hipóteses de agente ainda ``proposta`` exigem aprovação do pesquisador (lote, uma vez);
          sem ``approver`` ou sem resposta, ficam **pendentes** e não executam;
        - ``semi``/``auto``: as ``HYPOTHESES_PER_CYCLE`` de maior prioridade executam; as demais ficam ``proposta``;
        - modo desconhecido: tratado como ``assisted`` (falha fechada);
        - hipótese ``abandonada``, ``validada`` ou ``refutada`` nunca executa de novo.

        Args:
            hypothesis_ids: Hipóteses referenciadas pelas subtarefas do plano.
            mode: ``SessionMode`` da sessão.
            approver: Quem aprova no ``assisted`` (padrão em produção: ``terminal_approver``).
            custos: ``id`` -> ``custo_estimado`` declarado.
        """
        mode = mode if mode in SESSION_MODES else "assisted"
        selection = Selection()
        custos = custos or {}
        agent_driven: list[Node] = []
        for hid in dict.fromkeys(hypothesis_ids):
            node = self.hypothesis(hid)
            if node is None:
                continue
            status = node.properties.get("status")
            if status in CONCLUDED_STATUSES or status == STATUS_ABANDONADA:
                selection.excluded.append(hid)
                continue
            if node.properties.get("origem") == ORIGEM_PESQUISADOR:
                selection.execute.append(hid)
                self._mark_in_test(node, ORQUESTRADOR)
            else:
                agent_driven.append(node)
        for node in agent_driven:
            selection.priorities[node.id] = self.priority(node, custos.get(node.id, "medio"))
        if mode == "assisted":
            self._select_assisted(agent_driven, selection, approver)
        else:
            self._select_autonomous(agent_driven, selection)
        return selection

    def _mark_in_test(self, node: Node, actor: Actor) -> None:
        if node.properties.get("status") == STATUS_PROPOSTA:
            self._store.update_node(node.id, {"status": STATUS_EM_TESTE}, actor=actor)

    def _select_autonomous(self, nodes: list[Node], selection: Selection) -> None:
        ranked = sorted(nodes, key=lambda n: (-selection.priorities[n.id], n.id))
        for node in ranked[: self._per_cycle]:
            selection.execute.append(node.id)
            self._mark_in_test(node, ORQUESTRADOR)
        selection.deferred.extend(n.id for n in ranked[self._per_cycle :])

    def _select_assisted(self, nodes: list[Node], selection: Selection, approver: Approver | None) -> None:
        awaiting = [n for n in nodes if n.properties.get("status") == STATUS_PROPOSTA]
        for node in nodes:  # já aprovadas ou em teste (aprovação anterior): seguem
            if node not in awaiting:
                selection.execute.append(node.id)
        if not awaiting:
            return
        batch = sorted(awaiting, key=lambda n: (-selection.priorities[n.id], n.id))[:MAX_APPROVAL_BATCH]
        overflow = [n for n in awaiting if n not in batch]
        selection.pending_approval.extend(n.id for n in overflow)
        decisions: dict[str, ApprovalDecision] = {}
        if approver is not None:
            items = [
                ApprovalItem(
                    n.id,
                    clean_free_text(str(n.properties.get("enunciado", ""))),
                    clean_free_text(str(n.properties.get("justificativa", ""))),
                    str(n.properties.get("origem", "")),
                    selection.priorities[n.id],
                )
                for n in batch
            ]
            try:
                decisions = approver(items) or {}
            except Exception as exc:  # noqa: BLE001 - falha do aprovador: nada é aprovado
                logger.warning("Aprovação de hipóteses falhou", extra={"extra": {"erro": type(exc).__name__}})
        for node in batch:
            decision = decisions.get(node.id)
            if decision is None or decision.action not in (ACTION_APPROVE, ACTION_REJECT, ACTION_EDIT):
                selection.pending_approval.append(node.id)
            elif decision.action == ACTION_REJECT:
                motivo = clean_free_text(decision.motivo)[:_MAX_MOTIVO] or "rejeitada pelo pesquisador"
                self._reject(node, motivo)
                selection.rejected[node.id] = motivo
            else:
                self._approve(node, decision)
                selection.execute.append(node.id)

    def _approve(self, node: Node, decision: ApprovalDecision) -> None:
        changes: dict[str, Any] = {"status": STATUS_EM_TESTE}
        edited = clean_free_text(decision.enunciado)[: config.HYPOTHESIS_TEXT_MAX_CHARS] if decision.enunciado else ""
        if decision.action == ACTION_EDIT and edited:
            changes["enunciado"] = edited
        self._store.update_node(node.id, changes, actor=PESQUISADOR)
        self._store.record_audit_note(
            node.id, PESQUISADOR, {"decisao": "aprovada", "editada": "enunciado" in changes}
        )

    def _reject(self, node: Node, motivo: str) -> None:
        self._store.update_node(node.id, {"status": STATUS_ABANDONADA}, actor=PESQUISADOR)
        self._store.record_audit_note(node.id, PESQUISADOR, {"decisao": "rejeitada", "motivo": motivo})

    # ------------------------------------------------------------------ status e decisões

    def sync_statuses(self, hypothesis_ids: list[str]) -> dict[str, str]:
        """``validada``/``refutada`` a partir do **veredito calculado** (``|veredito| >= DECISION_EVAL_MIN_VERDICT``).

        Nunca por julgamento de LLM e nunca altera hipótese ``abandonada``. Uma oportunidade ``em_investigacao``
        ligada por ``GEROU`` a uma hipótese concluída avança a ``concluida`` (pelo orquestrador).

        Returns:
            ``id`` -> novo status, só das que mudaram.
        """
        changed: dict[str, str] = {}
        floor = config.DECISION_EVAL_MIN_VERDICT
        for hid in dict.fromkeys(hypothesis_ids):
            node = self.hypothesis(hid)
            if node is None or node.properties.get("status") in (STATUS_ABANDONADA, *CONCLUDED_STATUSES):
                continue
            verdict = node.properties.get("veredito")
            if not isinstance(verdict, (int, float)) or isinstance(verdict, bool):
                continue
            new = STATUS_VALIDADA if verdict >= floor else (STATUS_REFUTADA if verdict <= -floor else None)
            if new is None:
                continue
            self._store.update_node(node.id, {"status": new}, actor=ORQUESTRADOR)
            changed[node.id] = new
            self._conclude_opportunities(node.id)
        return changed

    def _conclude_opportunities(self, hypothesis_id: str) -> None:
        sub = self._store.neighbors(hypothesis_id, ["GEROU"], direction="in", depth=1)
        for edge in sub.edges:
            if edge.dst_id == hypothesis_id and edge.rel_type == "GEROU":
                opportunities.advance_opportunity(self._store, edge.src_id, opportunities.STATUS_CONCLUIDA)

    def evaluate_decisions(self) -> dict[str, str]:
        """Preenche ``Decisao.resultado_posterior`` quando a hipótese escolhida atinge ``|veredito| >= 0,3``.

        ``"acertada"`` com veredito positivo, ``"nao_acertada"`` com negativo; o valor do veredito vai para a
        trilha de auditoria da decisão. Só decisões ainda sem ``resultado_posterior`` são avaliadas.

        Returns:
            ``id da decisão`` -> avaliação.
        """
        floor = config.DECISION_EVAL_MIN_VERDICT
        evaluated: dict[str, str] = {}
        for decision in self._store.find_nodes("Decisao", {"projeto_id": self._project_id}, limit=_MAX_SCAN):
            if decision.properties.get("resultado_posterior"):
                continue
            for chosen in self._neighbors_out(decision.id, "ESCOLHEU"):
                verdict = chosen.properties.get("veredito")
                if chosen.label != "Hipotese" or not isinstance(verdict, (int, float)) or isinstance(verdict, bool):
                    continue
                if abs(verdict) < floor:
                    continue
                result = "acertada" if verdict > 0 else "nao_acertada"
                self._store.update_node(decision.id, {"resultado_posterior": result}, actor=ORQUESTRADOR)
                self._store.record_audit_note(
                    decision.id, ORQUESTRADOR,
                    {"avaliacao": result, "hipotese_id": chosen.id, "veredito": round(float(verdict), 4)},
                )
                evaluated[decision.id] = result
                break
        return evaluated

    # ------------------------------------------------------------------ parada

    @staticmethod
    def _meets_target(attempt: Attempt, criterion: Criterion) -> bool:
        """Resultado *validado* que atinge o ``alvo`` (ou, sem alvo, supera o baseline em ``delta_min``)."""
        if attempt.outcome_kind != "resultado" or attempt.validation != "validado" or attempt.value is None:
            return False
        better = (lambda a, b: a >= b) if criterion.sentido == "maior_melhor" else (lambda a, b: a <= b)
        if criterion.alvo is not None:
            return better(attempt.value, criterion.alvo)
        if criterion.delta_min is not None and attempt.baseline is not None:
            delta = (
                attempt.value - attempt.baseline
                if criterion.sentido == "maior_melhor"
                else attempt.baseline - attempt.value
            )
            return delta >= criterion.delta_min
        return False

    def check_solution(self) -> SolutionStatus:
        """Critério "solução encontrada" (design §8): veredito >= ``SOLUTION_MIN_VERDICT`` **e** alvo atingido.

        Só conta resultado ``validado`` (honestidade epistemológica); hipótese ``abandonada`` não conta. O veredito é
        recalculado agora pelo ``KnowledgeService`` (a única fonte do cálculo).
        """
        problem = get_active_problem(self._store, self._project_id)
        if problem is None:
            return SolutionStatus(False)
        try:
            criterion, _ = self._service.criterion_for(problem)
        except GraphStoreError:
            return SolutionStatus(False)
        best: SolutionStatus = SolutionStatus(False)
        for node in self.project_hypotheses():
            if node.properties.get("status") == STATUS_ABANDONADA:
                continue
            try:
                result, collected, _ = self._service.verdict_for_hypothesis(node.id)
            except GraphStoreError:
                continue
            if result.veredito < config.SOLUTION_MIN_VERDICT:
                continue
            hits = [c.attempt.value for c in collected if self._meets_target(c.attempt, criterion)]
            if not hits:
                continue
            value = max(hits) if criterion.sentido == "maior_melhor" else min(hits)  # type: ignore[type-var]
            if not best.found or result.veredito > (best.verdict or 0.0):
                best = SolutionStatus(True, node.id, round(result.veredito, 6), float(value))
        return best

    # ------------------------------------------------------------------ pendências

    def pending_runnable(self, exclude: set[str]) -> list[str]:
        """Hipóteses ``em_teste`` do projeto (aprovadas/selecionadas) fora de ``exclude``: há caminho em aberto."""
        return [
            n.id
            for n in self.project_hypotheses()
            if n.properties.get("status") == STATUS_EM_TESTE and n.id not in exclude
        ]

    def open_hypotheses_view(self, limit: int = 20) -> list[dict[str, Any]]:
        """Hipóteses abertas e recém-concluídas para o contexto do Researcher (texto: dado não confiável)."""
        out: list[dict[str, Any]] = []
        for node in self.project_hypotheses():
            status = node.properties.get("status")
            if status not in (*OPEN_STATUSES, *CONCLUDED_STATUSES):
                continue
            item: dict[str, Any] = {
                "id": node.id,
                "status": status,
                "origem": node.properties.get("origem"),
                "enunciado": sanitize_text(node.properties.get("enunciado", ""), 300),
            }
            verdict = node.properties.get("veredito")
            if isinstance(verdict, (int, float)) and not isinstance(verdict, bool):
                item["veredito"] = round(float(verdict), 3)
            out.append(item)
            if len(out) >= limit:
                break
        return out


# ---------------------------------------------------------------------------
# Aprovação no terminal (ação do pesquisador)
# ---------------------------------------------------------------------------


def _is_interactive() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def terminal_approver(
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], Any] = print,
    interactive: bool | None = None,
) -> Approver:
    """Aprovador do ``assisted``: o pesquisador decide no **terminal interativo**, em lote.

    Sem TTY devolve ``{}`` (nada é aprovado: as hipóteses ficam pendentes). A decisão de agente, do consultor ou
    de documento nunca chega aqui. Entradas: ``a`` aprova, ``r`` rejeita (pede o motivo), ``e`` edita o enunciado e
    aprova, ``p`` (ou vazio) pula e deixa pendente.

    Args:
        input_fn: Leitura do terminal (injetável em testes).
        output_fn: Saída de texto.
        interactive: Força o estado interativo (testes).
    """

    def approve(items: list[ApprovalItem]) -> dict[str, ApprovalDecision]:
        if not (_is_interactive() if interactive is None else interactive):
            output_fn("Hipóteses aguardam aprovação do pesquisador, mas não há terminal interativo: nada foi aprovado.")
            return {}
        decisions: dict[str, ApprovalDecision] = {}
        output_fn(f"\nHipóteses propostas por agentes aguardam sua aprovação ({len(items)}):")
        try:
            for n, item in enumerate(items, start=1):
                output_fn(
                    f"\n[{n}] origem: {sanitize_text(item.origem, 40)} | prioridade: {item.prioridade:.2f}\n"
                    f"    {sanitize_text(item.enunciado, 400)}\n"
                    f"    justificativa: {sanitize_text(item.justificativa, 400)}"
                )
                reply = input_fn("    [a]provar / [r]ejeitar / [e]ditar / [p]ular: ").strip().lower()
                if reply in ("a", "aprovar"):
                    decisions[item.id] = ApprovalDecision(ACTION_APPROVE)
                elif reply in ("r", "rejeitar"):
                    motivo = input_fn("    Motivo da rejeição: ").strip()
                    decisions[item.id] = ApprovalDecision(ACTION_REJECT, motivo=motivo or "rejeitada pelo pesquisador")
                elif reply in ("e", "editar"):
                    novo = input_fn("    Novo enunciado: ").strip()
                    if novo:
                        decisions[item.id] = ApprovalDecision(ACTION_EDIT, enunciado=novo)
        except (EOFError, KeyboardInterrupt):
            output_fn("Aprovação interrompida: o que não foi decidido continua pendente.")
        return decisions

    return approve
