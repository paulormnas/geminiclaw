"""Nós ``Afirmacao`` no grafo, para as afirmações de ``Descoberta`` (v18.5-claim-verification, design §2).

Escrita pelo orquestrador (``Actor(kind="orquestrador")``) ou pelo pesquisador na revisão (por isso sem a marca
``tainted``, que o schema reserva a nós criados por agente); o status da afirmação não
altera ``Resultado``, as arestas ``SUSTENTA``/``REFUTA`` nem ``Descoberta.status``. Afirmações do relatório ficam só no
arquivo da sessão.
"""

from __future__ import annotations

from typing import Any

from src.claims.model import Afirmacao
from src.knowledge.graph_store import GraphStore
from src.knowledge.provenance import Actor
from src.logger import get_logger

logger = get_logger(__name__)

_EVIDENCE_LABELS = {"resultado": "Resultado", "experimento": "Experimento", "insumo": "Insumo"}


def node_properties(claim: Afirmacao, project_id: str, session_id: str) -> dict[str, Any]:
    props: dict[str, Any] = {
        "projeto_id": project_id,
        "sessao_id": session_id,
        "texto": claim.texto,
        "status_afirmacao": claim.status_afirmacao,
        "codigo_arquivo": claim.codigo,
    }
    optional = {
        "metodo": claim.metodo,
        "parte_nao_suportada": claim.parte_nao_suportada,
        "justificativa": claim.justificativa or None,
        "verificador": claim.verificador,
        "motivo_pendencia": claim.motivo_pendencia,
        "revisao_pesquisador": claim.revisao_pesquisador,
    }
    props.update({k: v for k, v in optional.items() if v})
    return props


def write_discovery_claim(store: GraphStore, claim: Afirmacao, *, project_id: str, session_id: str) -> str:
    """Cria o nó ``Afirmacao`` de uma ``Descoberta`` e as arestas ``EXTRAIDA_DE`` e ``CONFERIDA_CONTRA``.

    Returns:
        O id do nó criado.
    """
    discovery_id = claim.conclusao_id.removeprefix("desc:")
    actor = Actor("orquestrador")
    node_id = store.create_node("Afirmacao", node_properties(claim, project_id, session_id), actor=actor)
    store.create_edge(node_id, "EXTRAIDA_DE", discovery_id, {"origem": "derivado", "evidencias": []}, actor=actor)
    for ref in claim.evidencias:
        kind, _, target = ref.partition(":")
        label = _EVIDENCE_LABELS.get(kind)
        if label is None or not target:
            continue
        try:
            node = store.get_node(target)
            if node is not None and node.label == label:
                store.create_edge(
                    node_id, "CONFERIDA_CONTRA", target, {"origem": "derivado", "evidencias": [target]}, actor=actor
                )
        except Exception as exc:  # noqa: BLE001 - a aresta de evidência é complementar; o nó já foi gravado
            logger.warning("Aresta CONFERIDA_CONTRA não gravada", extra={"erro": type(exc).__name__})
    return node_id


def update_discovery_claim(store: GraphStore, node_id: str, claim: Afirmacao, *, actor: Actor | None = None) -> None:
    """Atualiza status e revisão do nó (mudança de status, reverificação ou decisão do pesquisador)."""
    changes: dict[str, Any] = {"status_afirmacao": claim.status_afirmacao}
    if claim.revisao_pesquisador:
        changes["revisao_pesquisador"] = claim.revisao_pesquisador
    if claim.motivo_pendencia:
        changes["motivo_pendencia"] = claim.motivo_pendencia
    store.update_node(node_id, changes, actor=actor or Actor("orquestrador"))
