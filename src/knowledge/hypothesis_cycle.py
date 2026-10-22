"""Governança, prioridade e avaliação das hipóteses de um ciclo (v18-hypothesis-loop, design §3 a §5 e §8).

Tudo aqui é **determinístico** (sem LLM, exceto o ``custo_estimado`` que o Researcher declara) e passa pelo
``GraphStore``:

- ``HypothesisCycle.select``: governança por ``SessionMode`` (``assisted`` exige aprovação do pesquisador para
  hipóteses de agentes; ``semi``/``auto`` executam todas as não bloqueadas, por prioridade);
- prioridade ``0,35·relevância + 0,30·apoio_prévio + 0,20·novidade + 0,15·(1 − custo)`` (pesos configuráveis);
- ``sync_statuses``: ``validada``/``refutada`` **só** pela regra de réplicas (ADR 026 §3; nunca por julgamento de LLM);
- ``evaluate_decisions``: ``Decisao.resultado_posterior`` preenchido deterministicamente;

A aprovação do ``assisted`` é uma ação do **pesquisador no terminal**, registrada no gate persistente: a resposta de
``ask_researcher`` (inclusive a do consultor), de agente ou de documento nunca aprova hipótese — sem TTY nada é
aprovado e as hipóteses ficam pendentes (falha fechada).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from src import config
from src.knowledge import opportunities
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
from src.knowledge.projects import get_active_problem
from src.knowledge.provenance import Actor
from src.knowledge.result_records import hypothesis_state
from src.knowledge.schema import MOTIVO_ABANDONO_MAX_CHARS, ORIGEM_SISTEMA
from src.knowledge.service import KnowledgeService
from src.knowledge.validation import REVERT_ON_REOPEN_ROLE
from src.logger import get_logger
from src.utils.normalization import clean_free_text, normalize_domain_term

logger = get_logger(__name__)

PESQUISADOR = Actor(kind="pesquisador")
ORQUESTRADOR = Actor(kind="orquestrador")
# Só a revisão dos efeitos de ``sync_statuses`` reverte ``Oportunidade`` ``concluida`` (REVERT_ON_REOPEN_ROLE).
ORQUESTRADOR_REABERTURA = Actor(kind="orquestrador", role=REVERT_ON_REOPEN_ROLE)

CUSTO_VALUES = {"baixo": 0.0, "medio": 0.5, "alto": 1.0}
NEUTRAL = 0.5
STRONG_FAILURE_SIMILARITY = 0.8
SESSION_MODES = ("assisted", "semi", "auto")
MAX_APPROVAL_BATCH = 20
_MAX_SCAN = 1000
_MAX_MOTIVO = 500
MOTIVO_ABANDONO_MAX = MOTIVO_ABANDONO_MAX_CHARS

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
    enunciado_fonte: str = ""  # hipótese do sistema: ``texto_livre`` ou ``modelo`` (mostrado ao pesquisador)


@dataclass(frozen=True)
class ApprovalDecision:
    """Decisão do pesquisador sobre uma hipótese do lote."""

    action: str  # aprovar | rejeitar | editar
    motivo: str = ""
    enunciado: str = ""


Approver = Callable[[list[ApprovalItem]], dict[str, ApprovalDecision]]  # também aceita ``ApprovalPort``


@dataclass
class Selection:
    """Resultado da governança de um ciclo.

    Attributes:
        execute: IDs das hipóteses que podem executar neste ciclo.
        pending_approval: IDs que aguardam o pesquisador (``assisted`` sem resposta) — **não** executam.
        rejected: ID -> motivo das rejeitadas pelo pesquisador (viraram ``abandonada``).
        excluded: IDs que não executam por já estarem concluídas ou abandonadas.
        priorities: ID -> prioridade calculada.
    """

    execute: list[str] = field(default_factory=list)
    pending_approval: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)
    excluded: list[str] = field(default_factory=list)
    priorities: dict[str, float] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        """Contagens para a telemetria (nenhum texto de pesquisa)."""
        return {
            "executadas": len(self.execute),
            "pendentes_de_aprovacao": len(self.pending_approval),
            "rejeitadas": len(self.rejected),
            "excluidas": len(self.excluded),
        }


@dataclass(frozen=True)
class Transition:
    """Transição de status de uma hipótese ao fim do ciclo (só IDs, status e números)."""

    hypothesis_id: str
    status_anterior: str
    status_novo: str
    regra: str
    n_atingiu_alvo: int
    n_abaixo_alvo: int


def _count(value: Any) -> int | None:
    """Contagem inteira não negativa de uma propriedade, ou ``None`` quando ausente ou inválida."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


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
    ) -> None:
        """Inicializa o ciclo.

        Args:
            store: Porta única do grafo (de produção, o store indexado).
            project_id: Projeto da sessão.
            session_id: Sessão mestra.
            index: ``SemanticIndex`` (relevância/novidade/apoio prévio); sem ele, os termos semânticos ficam neutros.
            service: ``KnowledgeService`` (registros de resultado); padrão: um novo sobre ``store``.
            weights: Pesos da prioridade (padrão: ``HYPOTHESIS_PRIORITY_WEIGHTS``).
        """
        self._store = store
        self._project_id = project_id
        self._session_id = session_id
        self._index = index
        self._service = service or KnowledgeService(store)
        self._weights = weights or config.HYPOTHESIS_PRIORITY_WEIGHTS
        self.transitions: list[Transition] = []  # da última chamada de ``sync_statuses``

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
        """Apoio prévio da abordagem da hipótese em problemas similares (atalhos derivados dos registros).

        A maior similaridade entre o problema do projeto e um problema com ``FUNCIONOU_PARA`` ativo da abordagem (1,0
        no próprio problema); 0,0 quando há ``FALHOU_PARA`` ativo em problema com similaridade >= 0,8; 0,5 quando não
        há experiência. Só enxerga problemas do projeto ou ``compartilhavel``.
        """
        approaches = [n for n in self._neighbors_out(node.id, "PROPOE") if n.label == "Abordagem"]
        if not approaches or problem is None:
            return NEUTRAL
        similar = self._similar_problems(problem)
        worked: float | None = None
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
                    if rel == "FALHOU_PARA" and sim >= STRONG_FAILURE_SIMILARITY:
                        return 0.0
                    if rel == "FUNCIONOU_PARA":
                        worked = max(worked if worked is not None else 0.0, sim)
        return NEUTRAL if worked is None else _clamp01(worked)

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
        - ``semi``/``auto``: todas as não bloqueadas executam, em ordem de prioridade (ADR 021 §5.1);
        - modo desconhecido: tratado como ``assisted`` (falha fechada);
        - hipótese ``abandonada`` (pelo pesquisador) nunca executa de novo; ``validada`` e ``refutada`` recebem novos
          testes sem mudar de status no meio do ciclo (``v18.7-hypothesis-linking`` §5.2).

        Args:
            hypothesis_ids: Hipóteses referenciadas pelas subtarefas do plano.
            mode: ``SessionMode`` da sessão.
            approver: Quem aprova no ``assisted`` (em produção, ``PersistentGateApprover`` sobre o gate persistente).
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
            if node.properties.get("status") == STATUS_ABANDONADA:
                selection.excluded.append(hid)  # abandonada pelo pesquisador (as demais já foram reabertas no plano)
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
        for node in ranked:
            selection.execute.append(node.id)
            self._mark_in_test(node, ORQUESTRADOR)

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
                    self._statement_source(n),
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

    def _statement_source(self, node: Node) -> str:
        """``enunciado_fonte`` da hipótese do sistema (nota de auditoria da criação); vazio para as demais.

        Só exibição ao pesquisador: nunca serve de prova de aprovação.
        """
        if node.properties.get("origem") != ORIGEM_SISTEMA:
            return ""
        for entry in self._store.audit_history(node.id, limit=_MAX_SCAN):
            source = (entry.get("changes") or {}).get("enunciado_fonte")
            if isinstance(source, str):
                return source
        return ""

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
        self._store.update_node(
            node.id,
            {
                "status": STATUS_ABANDONADA,
                "abandonada_por": "pesquisador",
                "motivo_abandono": motivo[:MOTIVO_ABANDONO_MAX],
            },
            actor=PESQUISADOR,
        )
        self._store.record_audit_note(node.id, PESQUISADOR, {"decisao": "rejeitada", "motivo": motivo})

    # ------------------------------------------------------------------ status e decisões

    def sync_statuses(self, hypothesis_ids: list[str]) -> dict[str, str]:
        """Transições de status nos dois sentidos pela **regra de réplicas** (ADR 026 §3).

        Com ``n_atingiu_alvo`` e ``n_abaixo_alvo`` (tentativas válidas e independentes) gravados pelo orquestrador:
        ``validada`` quando ``n_atingiu_alvo >= HYPOTHESIS_MIN_REPLICAS`` e ``refutada`` quando
        ``n_abaixo_alvo >= HYPOTHESIS_MIN_REFUTATIONS`` e nenhuma atinge o alvo. Uma concluída que deixa de cumprir a
        própria condição muda de lado, se a outra vale, ou volta a ``em_teste``. ``proposta`` só transita com
        tentativas. Nunca por julgamento de LLM, nunca altera hipótese ``abandonada`` e só deve ser chamada ao fim do
        ciclo. Cada transição grava uma nota de auditoria (``self.transitions``) e revê os efeitos
        (``_review_effects``).

        Returns:
            ``id`` -> novo status, só das que mudaram.
        """
        changed: dict[str, str] = {}
        self.transitions = []
        for hid in dict.fromkeys(hypothesis_ids):
            node = self.hypothesis(hid)
            if node is None:
                continue
            status = node.properties.get("status")
            if status not in (*OPEN_STATUSES, *CONCLUDED_STATUSES):
                continue
            n_at, n_ab = _count(node.properties.get("n_atingiu_alvo")), _count(node.properties.get("n_abaixo_alvo"))
            if n_at is None or n_ab is None:
                continue
            if status == STATUS_PROPOSTA and (_count(node.properties.get("n_tentativas")) or 0) <= 0:
                continue
            new, rule = self._next_status(str(status), n_at, n_ab)
            if new is None:
                continue
            self._store.update_node(node.id, {"status": new}, actor=ORQUESTRADOR)
            self._store.record_audit_note(
                node.id,
                ORQUESTRADOR,
                {
                    "status_anterior": status,
                    "status_novo": new,
                    "regra": rule,
                    "n_atingiu_alvo": n_at,
                    "n_abaixo_alvo": n_ab,
                },
            )
            changed[node.id] = new
            self.transitions.append(Transition(node.id, str(status), new, rule, n_at, n_ab))
            self._review_effects(node, str(status), new, n_at)
        return changed

    @staticmethod
    def _next_status(status: str, n_atingiu: int, n_abaixo: int) -> tuple[str | None, str]:
        """``(novo status, regra)`` pela contagem; ``(None, "")`` quando o status não muda."""
        target = hypothesis_state(
            n_atingiu, n_abaixo,
            min_replicas=config.HYPOTHESIS_MIN_REPLICAS, min_refutations=config.HYPOTHESIS_MIN_REFUTATIONS,
        )
        rules = {STATUS_VALIDADA: "replicas_atingiram_alvo", STATUS_REFUTADA: "replicas_abaixo_alvo"}
        if status in OPEN_STATUSES:
            return (target, rules[target]) if target is not None else (None, "")
        if status in (STATUS_VALIDADA, STATUS_REFUTADA):
            if target == status:
                return None, ""
            if target is not None:
                return target, rules[target]
            return STATUS_EM_TESTE, "reabertura"
        return None, ""

    def _review_effects(self, node: Node, old: str, new: str, n_atingiu: int) -> None:
        """Revisão dos efeitos de uma transição (ADR 021 §4.4): ``Oportunidade``, decisões e atalhos."""
        concluded = (STATUS_VALIDADA, STATUS_REFUTADA)
        if new in concluded and old not in concluded:
            self._conclude_opportunities(node.id)
            return
        if old not in concluded:
            return
        reopened = new == STATUS_EM_TESTE
        if reopened:
            self._reopen_opportunities(node.id, n_atingiu)
        result = None if reopened else ("acertada" if new == STATUS_VALIDADA else "nao_acertada")
        self._revalidate_decisions(node.id, result, n_atingiu)

    def _conclude_opportunities(self, hypothesis_id: str) -> None:
        sub = self._store.neighbors(hypothesis_id, ["GEROU"], direction="in", depth=1)
        for edge in sub.edges:
            if edge.dst_id == hypothesis_id and edge.rel_type == "GEROU":
                opportunities.advance_opportunity(self._store, edge.src_id, opportunities.STATUS_CONCLUIDA)

    def _reopen_opportunities(self, hypothesis_id: str, n_atingiu: int) -> None:
        """``Oportunidade`` ``concluida`` ligada por ``GEROU`` volta a ``em_investigacao`` (só por este caminho)."""
        sub = self._store.neighbors(hypothesis_id, ["GEROU"], direction="in", depth=1)
        for edge in sub.edges:
            if edge.dst_id != hypothesis_id or edge.rel_type != "GEROU":
                continue
            opportunity = self._store.get_node(edge.src_id)
            if opportunity is None or opportunity.properties.get("status") != opportunities.STATUS_CONCLUIDA:
                continue
            self._store.update_node(
                opportunity.id, {"status": opportunities.STATUS_EM_INVESTIGACAO}, actor=ORQUESTRADOR_REABERTURA
            )
            self._store.record_audit_note(
                opportunity.id,
                ORQUESTRADOR,
                {"reaberta_pela_hipotese": hypothesis_id, "n_atingiu_alvo": n_atingiu},
            )

    def _revalidate_decisions(self, hypothesis_id: str, result: str | None, n_atingiu: int) -> None:
        """Decisões com ``ESCOLHEU->`` a hipótese e ``resultado_posterior``: limpa (reabertura) ou inverte."""
        sub = self._store.neighbors(hypothesis_id, ["ESCOLHEU"], direction="in", depth=1)
        for edge in sub.edges:
            if edge.dst_id != hypothesis_id or edge.rel_type != "ESCOLHEU":
                continue
            decision = self._store.get_node(edge.src_id)
            if decision is None or not decision.properties.get("resultado_posterior"):
                continue
            if decision.properties.get("resultado_posterior") == result:
                continue
            self._store.update_node(decision.id, {"resultado_posterior": result}, actor=ORQUESTRADOR)
            self._store.record_audit_note(
                decision.id,
                ORQUESTRADOR,
                {"reavaliacao": result or "reaberta", "hipotese_id": hypothesis_id, "n_atingiu_alvo": n_atingiu},
            )

    def evaluate_decisions(self) -> dict[str, str]:
        """Preenche ``Decisao.resultado_posterior`` quando a hipótese escolhida cumpre a regra de réplicas.

        ``"acertada"`` com a hipótese validada pela contagem, ``"nao_acertada"`` com a refutada; as contagens vão para
        a trilha de auditoria da decisão. Só decisões ainda sem ``resultado_posterior`` são avaliadas.

        Returns:
            ``id da decisão`` -> avaliação.
        """
        evaluated: dict[str, str] = {}
        for decision in self._store.find_nodes("Decisao", {"projeto_id": self._project_id}, limit=_MAX_SCAN):
            if decision.properties.get("resultado_posterior"):
                continue
            for chosen in self._neighbors_out(decision.id, "ESCOLHEU"):
                n_at = _count(chosen.properties.get("n_atingiu_alvo"))
                n_ab = _count(chosen.properties.get("n_abaixo_alvo"))
                if chosen.label != "Hipotese" or n_at is None or n_ab is None:
                    continue
                state = hypothesis_state(
                    n_at, n_ab,
                    min_replicas=config.HYPOTHESIS_MIN_REPLICAS, min_refutations=config.HYPOTHESIS_MIN_REFUTATIONS,
                )
                if state is None:
                    continue
                result = "acertada" if state == STATUS_VALIDADA else "nao_acertada"
                self._store.update_node(decision.id, {"resultado_posterior": result}, actor=ORQUESTRADOR)
                self._store.record_audit_note(
                    decision.id, ORQUESTRADOR,
                    {"avaliacao": result, "hipotese_id": chosen.id, "n_atingiu_alvo": n_at, "n_abaixo_alvo": n_ab},
                )
                evaluated[decision.id] = result
                break
        return evaluated

    # ------------------------------------------------------------------ parada

    # ------------------------------------------------------------------ pendências

    def pending_runnable(self, exclude: set[str]) -> list[str]:
        """Hipóteses ``em_teste`` do projeto (aprovadas/selecionadas) fora de ``exclude``: há caminho em aberto."""
        return [
            n.id
            for n in self.project_hypotheses()
            if n.properties.get("status") == STATUS_EM_TESTE and n.id not in exclude
        ]

    def untested_hypotheses(self) -> list[Node]:
        """Hipóteses ``em_teste`` do projeto sem nenhuma tentativa (``n_tentativas = 0`` ou ainda não calculado).

        Hipótese no plano e nunca testada é caminho aberto (``v18.6-hypothesis-closure`` §5).
        """
        out: list[Node] = []
        for n in self.project_hypotheses():
            if n.properties.get("status") != STATUS_EM_TESTE:
                continue
            tries = n.properties.get("n_tentativas")
            if not isinstance(tries, (int, float)) or isinstance(tries, bool) or tries <= 0:
                out.append(n)
        return out

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
            for key in ("n_atingiu_alvo", "n_abaixo_alvo"):
                count = _count(node.properties.get(key))
                if count is not None:
                    item[key] = count
            out.append(item)
            if len(out) >= limit:
                break
        return out
