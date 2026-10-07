"""Hipóteses, decisões de caminho e respostas a sugestões: leitura e gravação do plano (v18-hypothesis-loop).

O Researcher declara, no plano, as **hipóteses** que as subtarefas testam, as **decisões de caminho** (o que escolheu,
o que descartou e por quê) e as **respostas às sugestões do Curator**. Este módulo:

1. ``split_plan``: separa o envelope do plano (``hipoteses``/``decisoes``/``respostas_sugestoes``/``subtarefas``)
   da lista de subtarefas; o formato antigo (lista simples) segue aceito e nada é inventado para ele;
2. ``HypothesisBook.record``: grava hipóteses (``Hipotese`` + ``SOBRE``/``PROPOE``/``DERIVADA_DE``), decisões
   (``Decisao`` + ``TOMADA_EM``/``ESCOLHEU``/``DESCARTOU``/``INFORMADA_POR``) e as respostas às sugestões.

Princípios de segurança:

- **Tudo o que vem do plano é dado não confiável** (saída de LLM): texto limpo e limitado, identificadores validados por
  expressão fechada, e **todo ``id`` citado é conferido no grafo** (existe, é do projeto e tem o rótulo esperado);
- a **origem** de uma hipótese nunca vem do LLM: ``pesquisador`` só existe para nós que o pesquisador criou; a
  hipótese nova nasce ``researcher``, ``curator`` (resposta a sugestão aceita) ou ``oportunidade`` (oportunidade
  **aprovada** pelo pesquisador). Uma oportunidade ``documentada`` nunca origina hipótese (o pedido fica
  pendente no ``HumanGate``);
- uma hipótese ``abandonada`` (rejeitada pelo pesquisador) não volta: nem por ``id``, nem por repetição de enunciado;
- toda escrita passa pela porta única (``GraphStore``): o schema, a proveniência e ``validate_human_only`` valem aqui.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from src import config
from src.human_gate import default_gate
from src.knowledge import opportunities
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.ingestion import (
    ACTOR_ORQUESTRADOR,
    ACTOR_RESEARCHER,
    TIPOS_ABORDAGEM,
    SessionContext,
    _Writer,
)
from src.knowledge.normalization import clean_free_text, normalize_domain_term
from src.knowledge.projects import get_active_problem
from src.logger import get_logger

logger = get_logger(__name__)

STATUS_PROPOSTA = "proposta"
STATUS_EM_TESTE = "em_teste"
STATUS_VALIDADA = "validada"
STATUS_REFUTADA = "refutada"
STATUS_INCONCLUSIVA = "inconclusiva"
STATUS_ABANDONADA = "abandonada"
OPEN_STATUSES = (STATUS_PROPOSTA, STATUS_EM_TESTE, STATUS_INCONCLUSIVA)
CONCLUDED_STATUSES = (STATUS_VALIDADA, STATUS_REFUTADA)

ORIGEM_PESQUISADOR = "pesquisador"
ORIGEM_RESEARCHER = "researcher"
ORIGEM_CURATOR = "curator"
ORIGEM_OPORTUNIDADE = "oportunidade"

CUSTOS = ("baixo", "medio", "alto")
CRITERIOS_MAX_CHARS = 100
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_REF_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_PLAN_LIST_KEYS = ("subtarefas", "tasks", "plan", "subtasks", "steps")
_MAX_LIST_ITEMS = 20
_MAX_CONSULTED = 50
_MAX_SIMILAR = 5
_MAX_DISCARDED = 10
_PLAN_DATA_KEYS = ("hipoteses", "decisoes", "respostas_sugestoes")


class HypothesisError(GraphStoreError):
    """O plano não pôde ser gravado no grafo (sem Problema confirmado, grafo indisponível...)."""


# ---------------------------------------------------------------------------
# Modelo do plano (dado não confiável, já saneado)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HypothesisDecl:
    """Hipótese declarada no plano.

    Attributes:
        ref: Referência local (``h1``) usada por ``hypothesis_ref`` das subtarefas.
        id: ID de uma hipótese já existente (continuação), ou ``None``.
        enunciado: Enunciado testável.
        justificativa: Por que a hipótese é razoável.
        derivada_de: IDs de ``Descoberta``/``Oportunidade``/``Insumo`` de onde ela deriva (a verificar no grafo).
        custo: ``baixo``, ``medio`` ou ``alto``.
        abordagem: ``{"nome", "tipo"}`` da abordagem proposta, ou ``None``.
    """

    ref: str
    id: str | None
    enunciado: str
    justificativa: str
    derivada_de: tuple[str, ...] = ()
    custo: str = "medio"
    abordagem: dict[str, str] | None = None


@dataclass(frozen=True)
class DiscardedDecl:
    """Alternativa descartada numa decisão (referência a nó existente ou a um nome novo)."""

    tipo: str  # "Abordagem" | "Hipotese"
    motivo: str
    id: str | None = None
    ref: str | None = None
    nome: str | None = None


@dataclass(frozen=True)
class DecisionDecl:
    """Decisão de caminho declarada no plano."""

    contexto: str
    justificativa: str
    escolhido_tipo: str  # "Abordagem" | "Hipotese"
    escolhido_id: str | None = None
    escolhido_ref: str | None = None
    escolhido_nome: str | None = None
    descartados: tuple[DiscardedDecl, ...] = ()
    criterio: str | None = None
    informada_por: tuple[str, ...] = ()


@dataclass(frozen=True)
class SuggestionReply:
    """Resposta do Researcher a uma sugestão do Curator."""

    sugestao_id: str
    decisao: str  # "aceita" | "recusada"
    motivo: str
    hipotese_ref: str | None = None


@dataclass(frozen=True)
class PlanExtras:
    """O que o plano declara além das subtarefas (vazio no formato antigo)."""

    hipoteses: tuple[HypothesisDecl, ...] = ()
    decisoes: tuple[DecisionDecl, ...] = ()
    respostas: tuple[SuggestionReply, ...] = ()
    novo_formato: bool = False
    descartados_do_plano: int = 0  # entradas inválidas ignoradas (só contagem, para telemetria)

    @property
    def vazio(self) -> bool:
        return not (self.hipoteses or self.decisoes or self.respostas)


def _text(value: Any, limit: int | None = None) -> str:
    cap = limit or config.HYPOTHESIS_TEXT_MAX_CHARS
    text = clean_free_text(value) if isinstance(value, str) else ""
    return text[:cap].strip()


def _ident(value: Any, regex: re.Pattern[str] = _ID_RE) -> str | None:
    return value.strip() if isinstance(value, str) and regex.fullmatch(value.strip()) else None


def _ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    found = [i for i in (_ident(v) for v in value[:_MAX_LIST_ITEMS]) if i]
    return tuple(dict.fromkeys(found))


def _approach(value: Any) -> dict[str, str] | None:
    if isinstance(value, str) and _text(value, 200):
        return {"nome": _text(value, 200)}
    if not isinstance(value, dict):
        return None
    nome = _text(value.get("nome"), 200)
    if not nome:
        return None
    out = {"nome": nome}
    tipo = value.get("tipo")
    if isinstance(tipo, str) and tipo in TIPOS_ABORDAGEM:
        out["tipo"] = tipo
    descricao = _text(value.get("descricao"))
    if descricao:
        out["descricao"] = descricao
    return out


def _parse_hypotheses(raw: Any) -> tuple[list[HypothesisDecl], int]:
    out: list[HypothesisDecl] = []
    dropped = 0
    seen: set[str] = set()
    for item in (raw if isinstance(raw, list) else [])[: config.HYPOTHESES_MAX_PER_PLAN]:
        if not isinstance(item, dict):
            dropped += 1
            continue
        ref = _ident(item.get("ref"), _REF_RE)
        hid = _ident(item.get("id"))
        enunciado = _text(item.get("enunciado"))
        if (ref is None and hid is None) or ref in seen or (hid is None and not enunciado):
            dropped += 1
            continue
        key = ref or f"@{hid}"
        seen.add(key)
        custo = item.get("custo_estimado")
        out.append(
            HypothesisDecl(
                ref=ref or key,
                id=hid,
                enunciado=enunciado,
                justificativa=_text(item.get("justificativa")),
                derivada_de=_ids(item.get("derivada_de")),
                custo=custo if custo in CUSTOS else "medio",
                abordagem=_approach(item.get("abordagem")),
            )
        )
    return out, dropped


def _parse_discarded(raw: Any) -> tuple[list[DiscardedDecl], int]:
    out: list[DiscardedDecl] = []
    dropped = 0
    for item in (raw if isinstance(raw, list) else [])[:_MAX_DISCARDED]:
        if not isinstance(item, dict):
            dropped += 1
            continue
        tipo = item.get("tipo")
        motivo = _text(item.get("motivo"))
        did, dref, nome = _ident(item.get("id")), _ident(item.get("ref"), _REF_RE), _text(item.get("nome"), 200)
        if tipo not in ("Abordagem", "Hipotese") or not motivo or not (did or dref or nome):
            dropped += 1
            continue
        out.append(DiscardedDecl(tipo=tipo, motivo=motivo, id=did, ref=dref, nome=nome or None))
    return out, dropped


def _parse_decisions(raw: Any) -> tuple[list[DecisionDecl], int]:
    out: list[DecisionDecl] = []
    dropped = 0
    for item in (raw if isinstance(raw, list) else [])[: config.DECISIONS_MAX_PER_PLAN]:
        if not isinstance(item, dict) or not isinstance(item.get("escolhido"), dict):
            dropped += 1
            continue
        chosen = item["escolhido"]
        tipo = chosen.get("tipo")
        cid, cref, cnome = _ident(chosen.get("id")), _ident(chosen.get("ref"), _REF_RE), _text(chosen.get("nome"), 200)
        contexto, justificativa = _text(item.get("contexto")), _text(item.get("justificativa"))
        if tipo not in ("Abordagem", "Hipotese") or not (cid or cref or cnome) or not contexto or not justificativa:
            dropped += 1
            continue
        discarded, bad = _parse_discarded(item.get("descartados"))
        dropped += bad
        out.append(
            DecisionDecl(
                contexto=contexto,
                justificativa=justificativa,
                escolhido_tipo=tipo,
                escolhido_id=cid,
                escolhido_ref=cref,
                escolhido_nome=cnome or None,
                descartados=tuple(discarded),
                criterio=_text(item.get("criterio"), CRITERIOS_MAX_CHARS) or None,
                informada_por=_ids(item.get("informada_por")),
            )
        )
    return out, dropped


def _parse_replies(raw: Any) -> tuple[list[SuggestionReply], int]:
    out: list[SuggestionReply] = []
    dropped = 0
    seen: set[str] = set()
    for item in (raw if isinstance(raw, list) else [])[:_MAX_LIST_ITEMS]:
        if not isinstance(item, dict):
            dropped += 1
            continue
        sid, decisao = _ident(item.get("sugestao_id")), item.get("decisao")
        if sid is None or sid in seen or decisao not in ("aceita", "recusada"):
            dropped += 1
            continue
        seen.add(sid)
        out.append(
            SuggestionReply(
                sugestao_id=sid,
                decisao=decisao,
                motivo=_text(item.get("motivo")) or "sem motivo informado",
                hipotese_ref=_ident(item.get("hipotese_ref"), _REF_RE),
            )
        )
    return out, dropped


def split_plan(raw: Any) -> tuple[Any, PlanExtras]:
    """Separa o plano do Researcher em subtarefas e declarações de hipótese/decisão/resposta.

    O formato novo é um objeto com a lista de subtarefas (``subtarefas``) e, opcionalmente, ``hipoteses``,
    ``decisoes`` e ``respostas_sugestoes``. Qualquer outra forma (lista simples ou envelope antigo) devolve-se
    **inalterada**, com ``PlanExtras`` vazio: o parser antigo (``normalize_plan``) segue valendo.

    Args:
        raw: JSON extraído da resposta do Researcher (dado não confiável).

    Returns:
        ``(subtarefas_brutas, extras)``. As subtarefas continuam passando pelo normalizador e pelo Validator.
    """
    if not isinstance(raw, dict) or not any(k in raw for k in _PLAN_DATA_KEYS):
        return raw, PlanExtras()
    subtasks: Any = None
    for key in _PLAN_LIST_KEYS:
        if isinstance(raw.get(key), list):
            subtasks = raw[key]
            break
    if subtasks is None:
        return raw, PlanExtras()
    hips, d1 = _parse_hypotheses(raw.get("hipoteses"))
    decs, d2 = _parse_decisions(raw.get("decisoes"))
    replies, d3 = _parse_replies(raw.get("respostas_sugestoes"))
    return subtasks, PlanExtras(tuple(hips), tuple(decs), tuple(replies), True, d1 + d2 + d3)


def legacy_hypotheses(tasks: list[dict[str, Any]]) -> tuple[HypothesisDecl, ...]:
    """Promove o campo ``hypothesis`` (texto) das subtarefas do formato antigo a hipóteses **formais e governadas**.

    O mesmo texto vira uma só hipótese ``researcher`` (``proposta``): no ``assisted`` ela exige aprovação como
    qualquer outra. Subtarefas sem texto de hipótese seguem sem hipótese (preparatórias).
    """
    out: dict[str, HypothesisDecl] = {}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        text = _text(task.get("hypothesis"))
        if not text:
            continue
        key = normalize_domain_term(text)
        if key and key not in out:
            out[key] = HypothesisDecl(
                ref=f"legado_{len(out) + 1}",
                id=None,
                enunciado=text,
                justificativa=_text(task.get("scientific_rationale")) or "Declarada no plano (formato antigo).",
                abordagem=_approach(task.get("approach")),
            )
    return tuple(out.values())


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------


@dataclass
class RecordReport:
    """Resultado de ``HypothesisBook.record`` (só ids e contagens; nunca texto de pesquisa na telemetria).

    Attributes:
        ref_map: ``ref`` do plano -> ``id`` da ``Hipotese`` (criada, reutilizada ou existente).
        rejeitadas: ``ref`` -> motivo curto (código) das hipóteses recusadas na gravação; as subtarefas que as
            referenciam não executam.
        criadas / reutilizadas: IDs de hipóteses criadas e reutilizadas por similaridade.
        decisoes: IDs de ``Decisao`` criadas.
        respostas_registradas: ``sugestao_id`` -> ``aceita``/``recusada`` efetivamente registrada.
        oportunidades_pendentes: IDs de oportunidades ``documentadas`` citadas (decisão pendente do pesquisador).
    """

    ref_map: dict[str, str] = field(default_factory=dict)
    rejeitadas: dict[str, str] = field(default_factory=dict)
    criadas: list[str] = field(default_factory=list)
    reutilizadas: list[str] = field(default_factory=list)
    decisoes: list[str] = field(default_factory=list)
    respostas_registradas: dict[str, str] = field(default_factory=dict)
    oportunidades_pendentes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Contagens para a telemetria."""
        return {
            "hipoteses_criadas": len(self.criadas),
            "hipoteses_reutilizadas": len(self.reutilizadas),
            "hipoteses_rejeitadas": len(self.rejeitadas),
            "decisoes": len(self.decisoes),
            "sugestoes_aceitas": sum(1 for v in self.respostas_registradas.values() if v == "aceita"),
            "sugestoes_recusadas": sum(1 for v in self.respostas_registradas.values() if v == "recusada"),
        }


@dataclass(frozen=True)
class PendingSuggestion:
    """Sugestão pendente conhecida pelo orquestrador (``curator_suggestions.jsonl``), usada para validar respostas."""

    id: str
    texto: str
    fundamento_ids: tuple[str, ...]
    tipo: str


class HypothesisBook:
    """Grava no grafo as hipóteses, decisões e respostas do plano de uma sessão."""

    def __init__(
        self,
        store: GraphStore,
        ctx: SessionContext,
        *,
        index: Any | None = None,
        similarity: float | None = None,
        pending_suggestions: Callable[[], list[PendingSuggestion]] | None = None,
    ) -> None:
        """Inicializa o livro de hipóteses da sessão.

        Args:
            store: Porta única do grafo (de produção, o store indexado).
            ctx: Contexto da sessão (projeto, sessão, modo, nó de execução).
            index: ``SemanticIndex`` para a deduplicação; sem ele a deduplicação é por enunciado normalizado exato.
            similarity: Limiar de reutilização (padrão: ``HYPOTHESIS_DEDUP_SIMILARITY``).
            pending_suggestions: Fornece as sugestões pendentes (para validar ``respostas_sugestoes``).
        """
        self._store = store
        self._ctx = ctx
        self._index = index
        self._threshold = config.HYPOTHESIS_DEDUP_SIMILARITY if similarity is None else similarity
        self._pending = pending_suggestions or (lambda: [])
        self._writer = _Writer(store, ctx)
        self._session_node: str | None = None

    # -- leitura confiável do grafo ------------------------------------------------------

    def _project_node(self, node_id: str | None, labels: tuple[str, ...]) -> Node | None:
        """Nó existente do **projeto** com um dos rótulos (nunca confia no ID vindo do plano)."""
        if not node_id:
            return None
        node = self._store.get_node(node_id)
        if node is None or node.label not in labels or node.properties.get("projeto_id") != self._ctx.project_id:
            return None
        return node

    def session_node(self) -> str:
        """``id`` da ``Sessao`` no grafo (criada se preciso; idempotente)."""
        if self._session_node is None:
            self._session_node = self._writer.session()
        return self._session_node

    def _problem(self) -> Node:
        problem = get_active_problem(self._store, self._ctx.project_id)
        if problem is None:
            raise HypothesisError("Projeto sem Problema confirmado: hipóteses não podem ser gravadas.")
        return problem

    # -- deduplicação --------------------------------------------------------------------

    def find_similar(self, enunciado: str, justificativa: str) -> tuple[Node | None, float]:
        """Hipótese do projeto semanticamente equivalente (≥ limiar), ou exata por enunciado normalizado.

        Inclui hipóteses ``abandonada``: o chamador decide o que fazer com elas (nunca reaproveitá-las).
        """
        key = normalize_domain_term(enunciado)
        if self._index is not None:
            from src.knowledge.semantic_index import canonical_text

            text = canonical_text("Hipotese", {"enunciado": enunciado, "justificativa": justificativa})
            if text:
                try:
                    hits = self._index.similar(
                        text=text,
                        labels=["Hipotese"],
                        filters={"projeto_id": self._ctx.project_id},
                        min_score=self._threshold,
                        limit=_MAX_SIMILAR,
                        projeto_id=self._ctx.project_id,
                    )
                except Exception as exc:  # noqa: BLE001 - índice fora do ar: cai para a comparação exata
                    logger.warning(
                        "Busca semântica de hipóteses indisponível", extra={"extra": {"erro": type(exc).__name__}}
                    )
                    hits = []
                for hit in hits:
                    node = self._project_node(hit.node_id, ("Hipotese",))
                    if node is not None:
                        return node, float(hit.score)
        for node in self._store.find_nodes("Hipotese", {"projeto_id": self._ctx.project_id}, limit=1000):
            if key and normalize_domain_term(str(node.properties.get("enunciado", ""))) == key:
                return node, 1.0
        return None, 0.0

    # -- gravação ------------------------------------------------------------------------

    def record(self, extras: PlanExtras) -> RecordReport:
        """Grava hipóteses, respostas a sugestões e decisões do plano (nessa ordem: as decisões citam as hipóteses).

        Args:
            extras: Declarações do plano (já saneadas por ``split_plan``).

        Returns:
            O ``RecordReport`` (mapa ``ref -> id`` etc.).

        Raises:
            HypothesisError: Projeto sem ``Problema`` confirmado.
            GraphStoreError: Falha do grafo (propagada: o chamador decide fechar a sessão com checkpoint).
        """
        report = RecordReport()
        problem = self._problem()
        pending = {s.id: s for s in self._pending()}
        replies = {r.sugestao_id: r for r in extras.respostas if r.sugestao_id in pending}
        accepted_by_ref: dict[str, PendingSuggestion] = {}
        for reply in replies.values():
            ref = reply.hipotese_ref
            if reply.decisao == "aceita" and ref and ref not in accepted_by_ref:
                accepted_by_ref[ref] = pending[reply.sugestao_id]
        for decl in extras.hipoteses:
            self._record_hypothesis(decl, problem, report, accepted_by_ref.get(decl.ref))
        self._record_replies(replies, pending, problem, report)
        for decision in extras.decisoes:
            self._record_decision(decision, report)
        return report

    def _declared_sources(self, decl: HypothesisDecl, suggestion: PendingSuggestion | None) -> list[Node]:
        """Nós de origem (``DERIVADA_DE``) **verificados no grafo**: ID inventado ou de outro projeto é ignorado."""
        ids = list(decl.derivada_de) + (list(suggestion.fundamento_ids) if suggestion else [])
        nodes: list[Node] = []
        for node_id in dict.fromkeys(ids):
            node = self._project_node(node_id, ("Insumo", "Descoberta", "Oportunidade"))
            if node is not None:
                nodes.append(node)
        return nodes

    def _record_hypothesis(
        self,
        decl: HypothesisDecl,
        problem: Node,
        report: RecordReport,
        suggestion: PendingSuggestion | None,
    ) -> None:
        if decl.id is not None:  # continuação: só uma hipótese existente do projeto, nunca uma abandonada
            node = self._project_node(decl.id, ("Hipotese",))
            if node is None:
                report.rejeitadas[decl.ref] = "id_inexistente"
            elif node.properties.get("status") == STATUS_ABANDONADA:
                report.rejeitadas[decl.ref] = "hipotese_abandonada"
            else:
                report.ref_map[decl.ref] = node.id
            return
        if not decl.enunciado:
            report.rejeitadas[decl.ref] = "sem_enunciado"
            return
        sources = self._declared_sources(decl, suggestion)
        opportunity_sources = [n for n in sources if n.label == "Oportunidade"]
        if any(not opportunities.is_investigable(n) for n in opportunity_sources):
            # Oportunidade não aprovada pelo pesquisador: nunca é investigada (em nenhum modo); o pedido fica pendente.
            for node in opportunity_sources:
                if not opportunities.is_investigable(node):
                    report.oportunidades_pendentes.append(node.id)
                    self._request_opportunity_decision(node.id)
            report.rejeitadas[decl.ref] = "oportunidade_nao_aprovada"
            return
        similar, score = self.find_similar(decl.enunciado, decl.justificativa)
        if similar is not None:
            if similar.properties.get("status") == STATUS_ABANDONADA:
                report.rejeitadas[decl.ref] = "equivalente_a_hipotese_abandonada"
                return
            report.ref_map[decl.ref] = similar.id
            report.reutilizadas.append(similar.id)
            logger.info("Hipótese reutilizada por similaridade", extra={"extra": {"similaridade": round(score, 3)}})
            return
        origem = (
            ORIGEM_OPORTUNIDADE
            if opportunity_sources
            else (ORIGEM_CURATOR if suggestion is not None else ORIGEM_RESEARCHER)
        )
        hypothesis_id = self._create_hypothesis(decl, problem, origem, sources, decl.justificativa)
        report.ref_map[decl.ref] = hypothesis_id
        report.criadas.append(hypothesis_id)
        for node in opportunity_sources:
            self._link_opportunity(node, hypothesis_id)

    def _request_opportunity_decision(self, opportunity_id: str) -> None:
        try:
            default_gate().request(opportunities.DECISION_NAME, opportunity_id)
        except ValueError:  # pragma: no cover - a decisão é constante do próprio módulo
            logger.warning("Decisão reservada desconhecida ao registrar oportunidade pendente")

    def _link_opportunity(self, opportunity: Node, hypothesis_id: str) -> None:
        self._writer._edge(opportunity.id, "GEROU", hypothesis_id, fato=False)
        opportunities.advance_opportunity(self._store, opportunity.id, opportunities.STATUS_EM_INVESTIGACAO)

    def _create_hypothesis(
        self,
        decl: HypothesisDecl | None,
        problem: Node,
        origem: str,
        sources: list[Node],
        justificativa: str,
        *,
        enunciado: str | None = None,
        status: str = STATUS_PROPOSTA,
        motivo_criacao: str = "declarada no plano da sessão",
    ) -> str:
        text = enunciado if enunciado is not None else (decl.enunciado if decl else "")
        consulted = [n.id for n in sources] + [problem.id]
        hypothesis_id = self._store.create_node(
            "Hipotese",
            {
                "projeto_id": self._ctx.project_id,
                "sessao_id": self._ctx.session_id,
                "enunciado": text,
                "justificativa": justificativa or "Sem justificativa declarada no plano.",
                "status": status,
                "origem": origem,
                "justificativa_criacao": f"{motivo_criacao} {self._ctx.session_id}",
                "nos_consultados": consulted[:_MAX_CONSULTED],
            },
            actor=ACTOR_RESEARCHER,
        )
        self._writer._edge(hypothesis_id, "SOBRE", problem.id, fato=False)
        if decl is not None and decl.abordagem:
            approach_id = self._writer.abordagem(decl.abordagem, f"hipotese {decl.ref}")
            if approach_id:
                self._writer._edge(hypothesis_id, "PROPOE", approach_id, fato=False)
        for node in sources:
            self._writer._edge(hypothesis_id, "DERIVADA_DE", node.id, fato=False)
        return hypothesis_id

    def _record_replies(
        self,
        replies: dict[str, SuggestionReply],
        pending: dict[str, PendingSuggestion],
        problem: Node,
        report: RecordReport,
    ) -> None:
        for sid, reply in replies.items():
            suggestion = pending[sid]
            if reply.decisao == "aceita":
                linked = reply.hipotese_ref is not None and reply.hipotese_ref in report.ref_map
                if linked:
                    report.respostas_registradas[sid] = "aceita"
                    continue
                reply = SuggestionReply(sid, "recusada", f"{reply.motivo} (aceita sem hipótese correspondente)", None)
            self._record_refusal(suggestion, reply, problem, report)
            report.respostas_registradas[sid] = "recusada"

    def _record_refusal(
        self, suggestion: PendingSuggestion, reply: SuggestionReply, problem: Node, report: RecordReport
    ) -> None:
        """Sugestão recusada: fica registrada com o motivo (``Decisao-DESCARTOU->Hipotese abandonada``)."""
        sources = [n for n in (self._project_node(i, ("Insumo", "Descoberta", "Oportunidade"))
                               for i in suggestion.fundamento_ids) if n is not None]
        text = _text(suggestion.texto)
        if not text:
            return
        similar, _ = self.find_similar(text, "")
        if similar is not None:
            discarded_id = similar.id  # a mesma sugestão já registrada antes: não duplica o nó
        else:
            discarded_id = self._create_hypothesis(
                None, problem, ORIGEM_CURATOR, sources, f"Sugestão do Curator recusada: {reply.motivo}",
                enunciado=text, status=STATUS_ABANDONADA, motivo_criacao="sugestão do Curator recusada na sessão",
            )
        decision_id = self._create_decision(
            f"Resposta à sugestão do Curator ({suggestion.tipo})",
            f"Recusada pelo Researcher: {reply.motivo}",
            "resposta_a_sugestao",
            [i for i in suggestion.fundamento_ids],
            report,
        )
        self._store.create_edge(
            decision_id, "DESCARTOU", discarded_id, {"motivo": reply.motivo, "origem": "afirmado"},
            actor=ACTOR_ORQUESTRADOR,
        )

    def _create_decision(
        self, contexto: str, justificativa: str, criterio: str | None, informada_por: list[str], report: RecordReport
    ) -> str:
        informed = [n for n in (self._project_node(i, ("Descoberta",)) for i in informada_por) if n is not None]
        props: dict[str, Any] = {
            "projeto_id": self._ctx.project_id,
            "sessao_id": self._ctx.session_id,
            "contexto": contexto,
            "justificativa": justificativa or "Sem justificativa declarada.",
            "justificativa_criacao": f"decisão de caminho registrada no plano da sessão {self._ctx.session_id}",
            "nos_consultados": [n.id for n in informed][:_MAX_CONSULTED],
        }
        if criterio:
            props["criterio"] = criterio
        decision_id = self._store.create_node("Decisao", props, actor=ACTOR_RESEARCHER)
        self._writer._edge(decision_id, "TOMADA_EM", self.session_node(), fato=False)
        for node in informed:
            self._writer._edge(decision_id, "INFORMADA_POR", node.id, fato=False)
        report.decisoes.append(decision_id)
        return decision_id

    def _resolve_target(
        self, tipo: str, node_id: str | None, ref: str | None, nome: str | None, report: RecordReport
    ) -> str | None:
        """Resolve uma alternativa (escolhida ou descartada) para o ``id`` de um nó ``Abordagem``/``Hipotese``.

        Devolve ``None`` quando não há nó correspondente (a decisão decide se cria) ou quando a referência é a uma
        hipótese recusada nesta gravação (ela nunca pode ser a escolhida).
        """
        if ref and ref in report.ref_map:
            node = self._project_node(report.ref_map[ref], ("Hipotese",))
            return node.id if node is not None and node.label == tipo else None
        if ref and ref in report.rejeitadas:
            return None
        if node_id:
            node = self._project_node(node_id, (tipo,))
            return node.id if node is not None else None
        if not nome:
            return None
        if tipo == "Abordagem":
            return self._writer.abordagem({"nome": nome}, "decisao")
        found, _ = self.find_similar(nome, "")
        return found.id if found is not None else None

    def _record_decision(self, decl: DecisionDecl, report: RecordReport) -> None:
        chosen = self._resolve_target(
            decl.escolhido_tipo, decl.escolhido_id, decl.escolhido_ref, decl.escolhido_nome, report
        )
        if chosen is None:
            logger.info("Decisão ignorada: o nó escolhido não existe ou foi recusado")
            return
        decision_id = self._create_decision(decl.contexto, decl.justificativa, decl.criterio,
                                            list(decl.informada_por), report)
        self._store.create_edge(decision_id, "ESCOLHEU", chosen, {"origem": "afirmado"}, actor=ACTOR_ORQUESTRADOR)
        problem = self._problem()
        for alt in decl.descartados:
            target = self._resolve_target(alt.tipo, alt.id, alt.ref, alt.nome, report)
            if target is None and alt.tipo == "Hipotese" and alt.nome:
                # Alternativa que ainda não existe como nó: registra o caminho não seguido como hipótese abandonada.
                target = self._create_hypothesis(
                    None, problem, ORIGEM_RESEARCHER, [], alt.motivo, enunciado=alt.nome,
                    status=STATUS_ABANDONADA, motivo_criacao="alternativa descartada na decisão da sessão",
                )
            if target is None or target == chosen:
                continue
            self._store.create_edge(
                decision_id, "DESCARTOU", target, {"motivo": alt.motivo, "origem": "afirmado"}, actor=ACTOR_ORQUESTRADOR
            )

    # -- resolução de referências das subtarefas ---------------------------------------

    def resolve_ref(self, ref: str, report: RecordReport) -> str | None:
        """``id`` da hipótese a que ``hypothesis_ref`` se refere: declarada no plano ou hipótese existente do projeto.

        Uma referência a hipótese ``abandonada`` ou recusada nunca resolve.
        """
        if not ref:
            return None
        if ref in report.ref_map:
            return report.ref_map[ref]
        if ref in report.rejeitadas:
            return None
        node = self._project_node(_ident(ref), ("Hipotese",))
        if node is not None and node.properties.get("status") != STATUS_ABANDONADA:
            return node.id
        return None
