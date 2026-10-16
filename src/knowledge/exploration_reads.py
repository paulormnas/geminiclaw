"""Leituras compatíveis do grafo para a exploração rastreável (v18.7-graph-exploration-relations, ADR 021 §9).

Só leitura: nunca reescrevem o nó. Nós anteriores à V18.7 não têm ``Experimento.papel`` nem
``Hipotese.abandonada_por``; estas funções dão o significado que eles tinham.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.knowledge import schema
from src.knowledge.graph_store import Node
from src.logger import get_logger

logger = get_logger(__name__)

PAPEL_PADRAO = "teste"
STATUS_ABANDONADA = "abandonada"
DECISAO_REJEITADA = "rejeitada"


def experiment_role(node: Node) -> str:
    """Papel do experimento; ``teste`` quando o nó não tem a propriedade (nó antigo)."""
    return str(node.properties.get("papel") or PAPEL_PADRAO)


def structured_key(problem_id: str, approach_id: str, metric_id: str) -> str:
    """``"<problema_id>|<abordagem_id>|<metrica_id>"`` da hipótese do sistema.

    Raises:
        ValueError: Algum componente não é um identificador conferido no grafo.
    """
    parts = (problem_id, approach_id, metric_id)
    for part in parts:
        if not schema.IDENTIFIER_RE.fullmatch(part):
            raise ValueError(f"componente inválido para a chave estruturada: {part!r}")
    return "|".join(parts)


def _has_researcher_rejection(audit_history: Sequence[dict[str, Any]]) -> bool:
    """Há nota do ``Actor`` pesquisador com ``decisao = "rejeitada"`` na trilha de auditoria."""
    return any(
        entry.get("actor") == "pesquisador" and (entry.get("changes") or {}).get("decisao") == DECISAO_REJEITADA
        for entry in audit_history
    )


def abandoned_by(node: Node, audit_history: Sequence[dict[str, Any]]) -> str | None:
    """Quem abandonou a hipótese: ``pesquisador``, ``sistema`` ou ``agente``; ``None`` se ela não está abandonada.

    Valor gravado em ``abandonada_por`` vale. Sem ele (nó antigo), só a nota de rejeição do pesquisador na trilha de
    auditoria (``audit_history(node.id)``, lida inteira pelo chamador) faz da hipótese uma abandonada pelo
    pesquisador; senão foi o agente (decisão do pesquisador, 2026-10-15). Inconsistências vão a ``WARNING`` e
    mantêm o valor gravado.
    """
    if node.properties.get("status") != STATUS_ABANDONADA:
        return None
    stored = node.properties.get("abandonada_por")
    rejected = _has_researcher_rejection(audit_history)
    if stored is None:
        return "pesquisador" if rejected else "agente"
    if rejected and stored in ("agente", "sistema"):
        logger.warning(
            "Hipótese abandonada com nota de rejeição do pesquisador, mas abandonada_por diferente",
            extra={"hipotese_id": node.id, "abandonada_por": stored},
        )
    return str(stored)
