"""Domínio de um nó e predicados "entre domínios" / "entre projetos" (v17-knowledge-semantic-index §4).

Cada domínio de um nó é levado ao seu ancestral de nível ``area`` (ou mantido, se
já for ``grande_area``/``area``), de modo que "Química Orgânica" e "Química
Inorgânica" contam como o mesmo domínio ``Química``.

- ``Projeto``/``Problema``: domínios pelas arestas ``NO_DOMINIO``.
- Demais rótulos: domínios dos ``Problema``s do seu projeto.
"""

from __future__ import annotations

from src.knowledge.graph_store import GraphStore, Node

# Níveis que já estão em (ou acima de) ``area``: não sobem mais.
_TOP_LEVELS = frozenset({"grande_area", "area"})
# Teto de saltos ao subir a hierarquia (grande_area > area > subarea > especialidade).
_MAX_CLIMB = 4


def area_ancestor(store: GraphStore, dominio_id: str) -> str | None:
    """Leva um ``Dominio`` ao seu ancestral de nível ``area``.

    Args:
        store: Grafo de conhecimento.
        dominio_id: ID de um nó ``Dominio``.

    Returns:
        O ID do ancestral em nível ``area`` (ou o próprio ID se já for
        ``grande_area``/``area``). Se a hierarquia estiver incompleta (sem
        ``SUBAREA_DE`` até uma ``area``), devolve o ID do ancestral mais alto
        alcançado. ``None`` se o nó não existe ou não é um ``Dominio``.
    """
    current = store.get_node(dominio_id)
    if current is None or current.label != "Dominio":
        return None
    for _ in range(_MAX_CLIMB):
        if current.properties.get("nivel") in _TOP_LEVELS:
            break
        parents = [
            n
            for n in store.neighbors(current.id, ["SUBAREA_DE"], direction="out", depth=1).nodes
            if n.label == "Dominio" and n.id != current.id
        ]
        if not parents:
            break
        current = parents[0]
    return current.id


def _direct_domains(store: GraphStore, node_id: str) -> set[str]:
    sub = store.neighbors(node_id, ["NO_DOMINIO"], direction="out", depth=1)
    return {n.id for n in sub.nodes if n.label == "Dominio"}


def node_domains(store: GraphStore, node: Node) -> frozenset[str]:
    """Domínios de um nó, em nível ``area``.

    Args:
        store: Grafo de conhecimento.
        node: Nó cujos domínios se deseja.

    Returns:
        Conjunto de IDs de ``Dominio`` em nível ``area`` (vazio se o nó, ou o
        seu projeto, ainda não tem domínio atribuído).
    """
    if node.label == "Dominio":
        anc = area_ancestor(store, node.id)
        return frozenset({anc}) if anc else frozenset()
    if node.label in ("Projeto", "Problema"):
        raw = _direct_domains(store, node.id)
    else:
        raw = set()
        projeto_id = node.properties.get("projeto_id")
        if projeto_id:
            for problema in store.find_nodes("Problema", {"projeto_id": projeto_id}, limit=1000):
                raw |= _direct_domains(store, problema.id)
    areas = {area_ancestor(store, d) for d in raw}
    return frozenset(a for a in areas if a)


def between_domains(domains_a: frozenset[str], domains_b: frozenset[str]) -> bool:
    """Par entre domínios = conjuntos de domínios (nível ``area``) disjuntos.

    Se algum dos lados não tem domínio atribuído, o par **não** é considerado
    "entre domínios": sem informação não se pode afirmar que cruza áreas, e a
    faixa baixa (0,60–0,70) é exclusiva de pares que comprovadamente cruzam.
    """
    if not domains_a or not domains_b:
        return False
    return domains_a.isdisjoint(domains_b)


def between_projects(node_a: Node, node_b: Node) -> bool:
    """Par entre projetos = ``projeto_id`` diferentes."""
    return node_a.properties.get("projeto_id") != node_b.properties.get("projeto_id")
