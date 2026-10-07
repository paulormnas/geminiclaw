"""Oportunidades: decisão do pesquisador e avanço determinístico (v18-hypothesis-loop, design §7).

Uma ``Oportunidade`` nasce ``documentada`` (escrita pelo Curator) e **só o pesquisador** decide sobre ela:
``geminiclaw opportunities approve|reject``. Nenhuma oportunidade é investigada, sugerida ou vira hipótese sem essa
aprovação, em nenhum ``SessionMode``.

Barreiras (em camadas, nenhuma depende do prompt de um LLM):

1. ``HumanGate``: ``decide_opportunity`` só grava com um pedido ``aprovar_oportunidade`` **autorizado** por origem
   humana (``terminal``/``cli``); a resposta de ``ask_researcher`` (inclusive a do Researcher consultor), de um agente
   ou de um documento nunca autoriza (``src.human_gate``);
2. ``GraphStore``: ``validate_human_only`` recusa que agente **ou orquestrador** aprove/rejeite ou grave ``decidido_*``;
   o orquestrador só avança uma oportunidade **já aprovada** (``aprovada`` -> ``em_investigacao`` -> ``concluida``).

O texto da oportunidade vem de um agente (Curator): é dado não confiável e é sanitizado antes de ir ao terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.human_gate import HUMAN_SOURCES, HumanGate, Source, default_gate
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.graph_views import sanitize_text
from src.knowledge.provenance import Actor
from src.logger import get_logger

logger = get_logger(__name__)

PESQUISADOR = Actor(kind="pesquisador")
ORQUESTRADOR = Actor(kind="orquestrador")

DECISION_NAME = "aprovar_oportunidade"
STATUS_DOCUMENTADA = "documentada"
STATUS_APROVADA = "aprovada"
STATUS_REJEITADA = "rejeitada"
STATUS_EM_INVESTIGACAO = "em_investigacao"
STATUS_CONCLUIDA = "concluida"
# Estados em que a oportunidade pode originar hipótese e ser sugerida/investigada (já decididos pelo humano).
INVESTIGABLE_STATUSES = (STATUS_APROVADA, STATUS_EM_INVESTIGACAO)

MAX_MOTIVO_CHARS = 1000
_MAX_LIST = 200


class OpportunityError(GraphStoreError):
    """Decisão de oportunidade impossível (inexistente, de outro projeto, já decidida ou não autorizada)."""


@dataclass(frozen=True)
class OpportunityView:
    """Linha de ``opportunities list`` (texto já sanitizado para o terminal)."""

    id: str
    status: str
    enunciado: str
    justificativa: str
    projeto_id: str


def _clean(value: object, limit: int) -> str:
    """Texto de agente em uma linha, sem controles (terminal e grafo), com tamanho limitado."""
    return sanitize_text(value, limit) if value is not None else ""


def _find(store: GraphStore, opportunity_id: str, project_id: str | None) -> Node:
    node = store.get_node(opportunity_id) if isinstance(opportunity_id, str) and opportunity_id else None
    if node is None or node.label != "Oportunidade":
        raise OpportunityError("Oportunidade não encontrada.")
    if project_id is not None and node.properties.get("projeto_id") != project_id:
        raise OpportunityError("A oportunidade pertence a outro projeto.")
    return node


def list_opportunities(store: GraphStore, project_id: str, status: str | None = None) -> list[OpportunityView]:
    """Oportunidades do projeto (opcionalmente de um status), em ordem estável de ``id``.

    Args:
        store: Grafo.
        project_id: Projeto.
        status: Filtro de status (``documentada``, ``aprovada``...); ``None`` = todas.

    Returns:
        Até ``_MAX_LIST`` oportunidades.
    """
    filters: dict[str, Any] = {"projeto_id": project_id}
    if status is not None:
        filters["status"] = status
    nodes = sorted(store.find_nodes("Oportunidade", filters, limit=_MAX_LIST), key=lambda n: n.id)
    return [
        OpportunityView(
            id=n.id,
            status=str(n.properties.get("status", "")),
            enunciado=_clean(n.properties.get("enunciado"), 300),
            justificativa=_clean(n.properties.get("justificativa"), 300),
            projeto_id=str(n.properties.get("projeto_id", "")),
        )
        for n in nodes
    ]


def _require_authorization(gate: HumanGate, request_id: int, opportunity_id: str) -> None:
    """Exige um pedido ``aprovar_oportunidade`` autorizado por origem humana e referente a esta oportunidade."""
    req = gate.get(request_id)
    if (
        req is None
        or req.decisao != DECISION_NAME
        or not gate.authorized(request_id)
        or req.resolvido_por not in HUMAN_SOURCES
        or req.referencia != opportunity_id[:120]
    ):
        raise OpportunityError(
            "Decisão sobre oportunidade exige a ação explícita do pesquisador (terminal ou CLI); "
            "a resposta de um agente ou do Researcher consultor não vale. Nada foi alterado."
        )


def decide_opportunity(
    store: GraphStore,
    opportunity_id: str,
    *,
    approve: bool,
    motivo: str | None,
    gate: HumanGate,
    request_id: int,
    project_id: str | None = None,
) -> Node:
    """Aprova ou rejeita uma oportunidade ``documentada`` (decisão reservada ao pesquisador).

    Args:
        store: Grafo.
        opportunity_id: ``id`` da oportunidade.
        approve: ``True`` aprova; ``False`` rejeita (exige ``motivo``).
        motivo: Justificativa da decisão (obrigatória na rejeição).
        gate: ``HumanGate`` que registrou a decisão.
        request_id: Pedido ``aprovar_oportunidade`` já autorizado por origem humana.
        project_id: Se informado, a oportunidade deve ser deste projeto.

    Returns:
        O nó atualizado.

    Raises:
        OpportunityError: Sem autorização humana, oportunidade inexistente/de outro projeto/já decidida, ou
            rejeição sem motivo.
    """
    _require_authorization(gate, request_id, opportunity_id)
    node = _find(store, opportunity_id, project_id)
    current = node.properties.get("status")
    if current != STATUS_DOCUMENTADA:
        raise OpportunityError(f"A oportunidade já está '{current}'; só oportunidades documentadas são decididas.")
    reason = _clean(motivo, MAX_MOTIVO_CHARS) if motivo else ""
    if not approve and not reason:
        raise OpportunityError("A rejeição exige --motivo.")
    changes: dict[str, Any] = {
        "status": STATUS_APROVADA if approve else STATUS_REJEITADA,
        "decidido_por": "pesquisador",
        "decidido_em": datetime.now(timezone.utc).isoformat(),
    }
    if reason:
        changes["motivo_decisao"] = reason
    store.update_node(node.id, changes, actor=PESQUISADOR)
    logger.info(
        "Oportunidade decidida pelo pesquisador",
        extra={"extra": {"decisao": "aprovada" if approve else "rejeitada", "id": node.id}},
    )
    updated = store.get_node(node.id)
    return updated if updated is not None else node


def authorize_and_decide(
    store: GraphStore,
    opportunity_id: str,
    *,
    approve: bool,
    motivo: str | None,
    project_id: str | None = None,
    gate: HumanGate | None = None,
) -> Node:
    """Ponto de entrada da **CLI** (``geminiclaw opportunities approve|reject``).

    Só deve ser chamado de dentro do comando disparado pelo pesquisador: registra o pedido no gate, autoriza com a
    origem ``cli`` e decide. Código que processa resposta de agente ou de consultor nunca o chama.
    """
    gate = gate or default_gate()
    req = gate.request(DECISION_NAME, opportunity_id)
    gate.answer(req.id, source=Source.CLI, approved=True)
    return decide_opportunity(
        store, opportunity_id, approve=approve, motivo=motivo, gate=gate, request_id=req.id, project_id=project_id
    )


def advance_opportunity(store: GraphStore, opportunity_id: str, new_status: str) -> bool:
    """Avanço determinístico pelo orquestrador: ``aprovada -> em_investigacao`` e ``em_investigacao -> concluida``.

    Nunca decide: só avança uma oportunidade que o pesquisador já aprovou (``validate_human_only`` também recusa
    qualquer outra transição pelo orquestrador).

    Returns:
        ``True`` se avançou; ``False`` se o estado atual não permite (nada é alterado).
    """
    required = {STATUS_EM_INVESTIGACAO: STATUS_APROVADA, STATUS_CONCLUIDA: STATUS_EM_INVESTIGACAO}.get(new_status)
    node = store.get_node(opportunity_id)
    if required is None or node is None or node.label != "Oportunidade":
        return False
    if node.properties.get("status") != required:
        return False
    store.update_node(node.id, {"status": new_status}, actor=ORQUESTRADOR)
    return True


def is_investigable(node: Node | None) -> bool:
    """A oportunidade já foi aprovada pelo pesquisador (``aprovada`` ou ``em_investigacao``)."""
    return node is not None and node.label == "Oportunidade" and node.properties.get("status") in INVESTIGABLE_STATUSES
