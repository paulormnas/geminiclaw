"""Restrições de direção de pesquisa (v18.7-exploration-limits, design §8; ADR 021 §5.5).

Uma ``Restricao`` veda uma direção (texto e, opcionalmente, abordagens canônicas) para um ``Problema`` ou para o
``Projeto`` inteiro. Só o pesquisador a cria e a revoga: no terminal (``Actor`` pesquisador, comandos
``project restrict|unrestrict``) ou na sessão, depois que o pedido ``restringir_direcao`` foi autorizado e consumido
(``Actor.under_request``, ``pedido_id`` obrigatório). A revogação muda ``status`` e nunca apaga o nó.

A aplicação ao plano retira a hipótese cuja abordagem consta da restrição ou cujo texto é semanticamente próximo da
direção, gravando o abandono com o ``Actor`` derivado da própria restrição (``Actor.under_restriction``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from src import config
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.projects import ProjectError, _find_project_node, get_active_problem
from src.knowledge.provenance import Actor
from src.knowledge.schema import CATEGORIAS_RESTRICAO
from src.logger import get_logger
from src.utils.normalization import clean_free_text, normalize_domain_term

logger = get_logger(__name__)

CLI_SESSION = "__cli__"
STATUS_ATIVA = "ativa"
STATUS_REVOGADA = "revogada"
MAX_DIRECTION_CHARS = 500
MAX_APPROACHES = 20
_MAX_SCAN = 500
DECISION = "restringir_direcao"

PESQUISADOR = Actor(kind="pesquisador")


class RestrictionError(ProjectError):
    """Pedido de restrição inválido (campo, escopo ou autoridade)."""


@dataclass(frozen=True)
class Restriction:
    """Restrição lida do grafo (texto já saneado na criação)."""

    id: str
    direcao: str
    categoria: str
    abordagens: tuple[str, ...]
    status: str
    escopo: str  # ``problema`` ou ``projeto``
    pedido_id: int | None = None


@dataclass(frozen=True)
class RestrictionMatch:
    """Por que uma hipótese cai numa restrição (evento ``restricao_retirada``)."""

    restricao_id: str
    criterio: str  # ``abordagem`` ou ``similaridade``
    similaridade: float | None = None


def _clean_approaches(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        name = normalize_domain_term(str(raw))
        if name and name not in out:
            out.append(name)
    if len(out) > MAX_APPROACHES:
        raise RestrictionError(f"Abordagens demais: no máximo {MAX_APPROACHES}.")
    return out


def create_restriction(
    store: GraphStore,
    projeto_id: str,
    *,
    direcao: str,
    categoria: str,
    abordagens: Iterable[str] = (),
    problema: bool = False,
    request_id: int | None = None,
) -> str:
    """Cria a restrição (``ativa``) ligada ao projeto ou, com ``problema``, ao ``Problema`` confirmado.

    Args:
        store: Grafo.
        projeto_id: Projeto.
        direcao: Texto da direção vedada (dado do pesquisador; saneado e limitado).
        categoria: ``seguranca``, ``etica`` ou ``recurso``.
        abordagens: Nomes de abordagens vedadas (normalizados como termos de domínio).
        problema: Liga ao ``Problema`` ativo em vez do ``Projeto``.
        request_id: Pedido ``restringir_direcao`` autorizado e consumido, quando a sessão cria a restrição; vazio no
            terminal.

    Returns:
        O id do nó ``Restricao``.

    Raises:
        RestrictionError: Campo inválido ou projeto sem ``Problema`` confirmado (com ``problema``).
    """
    if categoria not in CATEGORIAS_RESTRICAO:
        raise RestrictionError(f"Categoria inválida '{categoria}': use uma de {', '.join(CATEGORIAS_RESTRICAO)}.")
    text = clean_free_text(direcao)[:MAX_DIRECTION_CHARS]
    if not text:
        raise RestrictionError("A direção vedada não pode ser vazia.")
    project = _find_project_node(store, projeto_id)
    pid = str(project.properties["projeto_id"])
    target = project
    if problema:
        found = get_active_problem(store, pid)
        if found is None:
            raise RestrictionError(f"O projeto {pid} não tem Problema confirmado.")
        target = found
    actor = Actor.under_request(request_id) if request_id is not None else PESQUISADOR
    props: dict[str, Any] = {
        "direcao": text, "categoria": categoria, "abordagens": _clean_approaches(abordagens), "status": STATUS_ATIVA,
        "decidida_por": "pesquisador", "decidida_em": datetime.now(timezone.utc).isoformat(), "projeto_id": pid,
        "sessao_id": CLI_SESSION,
    }
    if request_id is not None:
        props["pedido_id"] = request_id
    node_id = store.create_node("Restricao", props, actor=actor)
    store.create_edge(node_id, "RESTRINGE", target.id, {}, actor=actor)
    logger.info("Restrição criada", extra={"extra": {"restricao_id": node_id, "escopo": target.label}})
    return node_id


def create_from_request(
    store: GraphStore, gate: Any, session_chain: Iterable[str], reference: str, projeto_id: str, *, direcao: str,
    categoria: str, abordagens: Iterable[str] = (), problema: bool = True,
) -> str:
    """Cria a restrição pela sessão, depois de consumir o pedido ``restringir_direcao`` autorizado.

    Raises:
        GateAuthorizationRefused: Pedido inexistente, de outra sessão, já consumido ou não autorizado (nada é criado).
        RestrictionError: A resposta do pesquisador não foi ``restringir``.
    """
    request = gate.consume_authorized(DECISION, reference, list(session_chain))
    if (request.resposta or {}).get("acao") != "restringir":
        raise RestrictionError("O pedido foi respondido sem 'restringir': nenhuma restrição é criada.")
    return create_restriction(
        store, projeto_id, direcao=direcao, categoria=categoria, abordagens=abordagens, problema=problema,
        request_id=request.id,
    )


def revoke_restriction(store: GraphStore, restriction_id: str) -> str:
    """Revoga (``status = revogada``); o nó continua existindo. Devolve o ``projeto_id``.

    Raises:
        RestrictionError: Restrição inexistente.
    """
    node = store.get_node(restriction_id)
    if node is None or node.label != "Restricao":
        raise RestrictionError(f"Restrição '{restriction_id}' não encontrada.")
    store.update_node(restriction_id, {"status": STATUS_REVOGADA}, actor=PESQUISADOR)
    return str(node.properties.get("projeto_id", ""))


def _scope(store: GraphStore, node: Node) -> str | None:
    sub = store.neighbors(node.id, ["RESTRINGE"], direction="out", depth=1)
    for edge in sub.edges:
        if edge.src_id == node.id and edge.rel_type == "RESTRINGE":
            target = store.get_node(edge.dst_id)
            if target is not None:
                return "problema" if target.label == "Problema" else "projeto"
    return None


def _to_restriction(store: GraphStore, node: Node) -> Restriction | None:
    scope = _scope(store, node)
    if scope is None:
        return None
    props = node.properties
    approaches = props.get("abordagens")
    pedido = props.get("pedido_id")
    return Restriction(
        id=node.id, direcao=str(props.get("direcao", "")), categoria=str(props.get("categoria", "")),
        abordagens=tuple(str(a) for a in approaches) if isinstance(approaches, list) else (),
        status=str(props.get("status", "")), escopo=scope, pedido_id=pedido if isinstance(pedido, int) else None,
    )


def list_restrictions(store: GraphStore, projeto_id: str, *, only_active: bool = False) -> list[Restriction]:
    """Restrições do projeto (todas ou só as ``ativas``), em ordem de criação."""
    pid = str(_find_project_node(store, projeto_id).properties["projeto_id"])
    nodes = sorted(
        store.find_nodes("Restricao", {"projeto_id": pid}, limit=_MAX_SCAN),
        key=lambda n: str(n.properties.get("criado_em", "")),
    )
    found = [r for r in (_to_restriction(store, n) for n in nodes) if r is not None]
    return [r for r in found if r.status == STATUS_ATIVA] if only_active else found


def active_restrictions(store: GraphStore, projeto_id: str) -> list[Restriction]:
    """Restrições ``ativas`` do ``Problema`` e do ``Projeto``."""
    return list_restrictions(store, projeto_id, only_active=True)


def hypothesis_approaches(store: GraphStore, service: Any, hypothesis_id: str) -> list[str]:
    """Nomes normalizados das abordagens canônicas que a hipótese propõe (``PROPOE``)."""
    names: list[str] = []
    sub = store.neighbors(hypothesis_id, ["PROPOE"], direction="out", depth=1)
    for edge in sub.edges:
        if edge.src_id != hypothesis_id or edge.rel_type != "PROPOE":
            continue
        canonical = service.canonical_approach(edge.dst_id) if service is not None else edge.dst_id
        node = store.get_node(canonical)
        name = normalize_domain_term(str(node.properties.get("nome", ""))) if node is not None else ""
        if name and name not in names:
            names.append(name)
    return names


def match_hypothesis(
    store: GraphStore, service: Any, index: Any | None, hypothesis: Node, restrictions: Iterable[Restriction]
) -> RestrictionMatch | None:
    """Primeira restrição que atinge a hipótese: por abordagem canônica ou por similaridade semântica.

    Sem índice semântico só vale a abordagem (a similaridade fica de fora, sem inventar um valor).
    """
    rules = list(restrictions)
    if not rules:
        return None
    approaches = hypothesis_approaches(store, service, hypothesis.id)
    for rule in rules:
        if rule.abordagens and set(rule.abordagens) & set(approaches):
            return RestrictionMatch(rule.id, "abordagem")
    if index is None:
        return None
    text = f"{hypothesis.properties.get('enunciado', '')} {' '.join(approaches)}".strip()
    for rule in rules:
        try:
            similarity = float(index.text_similarity(text, rule.direcao))
        except Exception as exc:  # noqa: BLE001 - sem o índice a similaridade não é avaliada
            logger.warning("Similaridade da restrição indisponível", extra={"extra": {"erro": type(exc).__name__}})
            return None
        if similarity >= config.RESTRICTION_SIMILARITY:
            return RestrictionMatch(rule.id, "similaridade", round(similarity, 4))
    return None


def withdraw_hypothesis(store: GraphStore, hypothesis_id: str, restriction_id: str) -> None:
    """Abandona a hipótese pela restrição (``abandonada_por = pesquisador``, motivo com o id da restrição).

    A escrita usa o ``Actor`` derivado da restrição: a porta do grafo só a aceita com a ``Restricao`` ativa. Revogar a
    restrição depois não reabre a hipótese; isso é do pesquisador (``graph edit``).

    Raises:
        GraphStoreError: A restrição não está ativa ou a escrita não cabe na derivação.
    """
    store.update_node(
        hypothesis_id,
        {
            "status": "abandonada", "abandonada_por": "pesquisador",
            "motivo_abandono": f"direcao_restrita:{restriction_id}",
        },
        actor=Actor.under_restriction(restriction_id),
    )


__all__ = [
    "Restriction", "RestrictionError", "RestrictionMatch", "GraphStoreError", "active_restrictions",
    "create_from_request", "create_restriction", "hypothesis_approaches", "list_restrictions", "match_hypothesis",
    "revoke_restriction", "withdraw_hypothesis",
]
