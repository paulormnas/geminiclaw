"""Reversão humana de fusão de abordagens e de substituição de descoberta (``v17-curator-agent`` 8.5).

As ferramentas do Curator não desfazem fusões nem substituições (decisões duráveis, ADR 015 §10): reverter é decisão do
pesquisador. Nada é apagado: a aresta ``FUNDIDA_EM``/``SUBSTITUI`` passa a ``contestada`` (o serviço de conhecimento
ignora arestas contestadas ao resolver a canônica) e o ``status`` do nó volta a ``ativa``, com autoria ``pesquisador``
e trilha em ``knowledge_audit``.
"""

from __future__ import annotations

from typing import Any

from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore
from src.knowledge.projects import PESQUISADOR
from src.knowledge.provenance import Actor


class ReversalError(GraphStoreError):
    """A reversão não se aplica (nó inexistente, de outro projeto ou fora do estado revertível)."""


def _node_of_project(store: GraphStore, node_id: str, label: str, project_id: str) -> Any:
    node = store.get_node(node_id)
    if node is None or node.label != label:
        raise ReversalError(f"{label} '{node_id}' não encontrada.")
    if node.properties.get("projeto_id") not in (None, project_id):
        raise ReversalError(f"{label} '{node_id}' é de outro projeto.")
    return node


def revert_merge(
    store: GraphStore, duplicada_id: str, project_id: str, *, actor: Actor = PESQUISADOR
) -> dict[str, Any]:
    """Desfaz a fusão de uma ``Abordagem``: volta a ``ativa`` e contesta a aresta ``FUNDIDA_EM``.

    Raises:
        ReversalError: A abordagem não existe, é de outro projeto ou não está ``fundida``.
    """
    if actor.kind != "pesquisador":
        raise ReversalError("Só o pesquisador reverte uma fusão.")
    node = _node_of_project(store, duplicada_id, "Abordagem", project_id)
    if node.properties.get("status") != "fundida":
        raise ReversalError(f"A abordagem '{duplicada_id}' não está fundida.")
    edges = [
        e for e in store.neighbors(node.id, ["FUNDIDA_EM"], direction="out", depth=1).edges
        if e.src_id == node.id and e.rel_type == "FUNDIDA_EM" and e.properties.get("status") != "contestada"
    ]
    for edge in edges:
        store.set_edge_status(node.id, "FUNDIDA_EM", edge.dst_id, "contestada", actor=actor)
    store.update_node(node.id, {"status": "ativa"}, actor=actor)
    return {"ok": True, "abordagem": node.id, "arestas_contestadas": [e.dst_id for e in edges]}


def revert_substitution(
    store: GraphStore, descoberta_id: str, project_id: str, *, actor: Actor = PESQUISADOR
) -> dict[str, Any]:
    """Reativa uma ``Descoberta`` ``substituida`` e contesta a(s) aresta(s) ``SUBSTITUI`` que apontam para ela.

    Raises:
        ReversalError: A descoberta não existe, é de outro projeto ou não está ``substituida``.
    """
    if actor.kind != "pesquisador":
        raise ReversalError("Só o pesquisador reverte uma substituição.")
    node = _node_of_project(store, descoberta_id, "Descoberta", project_id)
    if node.properties.get("status") != "substituida":
        raise ReversalError(f"A descoberta '{descoberta_id}' não está substituída.")
    edges = [
        e for e in store.neighbors(node.id, ["SUBSTITUI"], direction="in", depth=1).edges
        if e.dst_id == node.id and e.rel_type == "SUBSTITUI" and e.properties.get("status") != "contestada"
    ]
    for edge in edges:
        store.set_edge_status(edge.src_id, "SUBSTITUI", node.id, "contestada", actor=actor)
    store.update_node(node.id, {"status": "ativa"}, actor=actor)
    return {"ok": True, "descoberta": node.id, "arestas_contestadas": [e.src_id for e in edges]}
