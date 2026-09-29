"""Preenchimento de proveniência (id, timestamps, autoria) para escritas no grafo.

Centraliza a regra de "autoria não forjável" (ADR 015 §4, Requirement
"Proveniência obrigatória"): os campos derivados do ``Actor`` da operação
sempre sobrescrevem qualquer valor enviado pelo chamador.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from src.knowledge import schema
from src.knowledge.ids import generate_node_id


def _now_iso() -> str:
    """Retorna o instante atual em ISO-8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


ActorKind = Literal["orquestrador", "pesquisador", "agente"]


class Actor:
    """Identidade de quem executa uma escrita no grafo (ADR 015 §4).

    Attributes:
        kind: ``"orquestrador"``, ``"pesquisador"`` ou ``"agente"``.
        role: Papel do agente (ex.: ``"curator"``) — obrigatório quando ``kind == "agente"``.
        model: Modelo usado pelo agente (ex.: ``"qwen3:8b"``), opcional.
    """

    __slots__ = ("kind", "role", "model")

    def __init__(self, kind: ActorKind, role: str | None = None, model: str | None = None) -> None:
        if kind == "agente" and not role:
            raise ValueError("Actor do tipo 'agente' requer 'role' (ex.: 'curator').")
        self.kind = kind
        self.role = role
        self.model = model

    @property
    def criado_por(self) -> str:
        """Valor derivado para a propriedade ``criado_por`` — nunca forjável pelo chamador.

        Returns:
            ``"orquestrador"``/``"pesquisador"`` para atores humanos/host, ou
            ``"<role>/<model>"`` (ou só ``"<role>"`` sem modelo) para agentes.
        """
        if self.kind in ("orquestrador", "pesquisador"):
            return self.kind
        assert self.role is not None  # garantido pelo __init__
        return f"{self.role}/{self.model}" if self.model else self.role

    @property
    def requires_provenance_justification(self) -> bool:
        """True quando a escrita exige ``justificativa_criacao`` e ``nos_consultados``."""
        return self.kind == "agente"

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return f"Actor(kind={self.kind!r}, role={self.role!r}, model={self.model!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Actor):
            return NotImplemented
        return (self.kind, self.role, self.model) == (other.kind, other.role, other.model)


def prepare_node_properties(caller_props: dict[str, object], actor: Actor) -> dict[str, object]:
    """Mescla as propriedades enviadas pelo chamador com a proveniência derivada do ``Actor``.

    Args:
        caller_props: Propriedades específicas do rótulo mais as comuns que o
            chamador pode informar (``projeto_id``, ``sessao_id`` e,
            opcionalmente, ``visibilidade``/``origem_no``/``versao_schema``).
        actor: Quem está realizando a escrita.

    Returns:
        Dicionário completo pronto para validação: ``id``, ``criado_em``,
        ``atualizado_em`` e ``criado_por`` são sempre sobrescritos com os
        valores derivados (nunca aceitos do chamador).
    """
    full_props = dict(caller_props)
    full_props["id"] = generate_node_id()
    now = _now_iso()
    full_props["criado_em"] = now
    full_props["atualizado_em"] = now
    full_props["criado_por"] = actor.criado_por
    full_props.setdefault("visibilidade", schema.DEFAULT_VISIBILIDADE)
    full_props.setdefault("origem_no", schema.DEFAULT_ORIGEM_NO)
    full_props.setdefault("versao_schema", schema.DEFAULT_VERSAO_SCHEMA)
    return full_props


def prepare_node_update(changes: dict[str, object]) -> dict[str, object]:
    """Adiciona ``atualizado_em`` a um conjunto de mudanças de ``update_node``.

    Args:
        changes: Mudanças solicitadas pelo chamador (já validadas contra
            campos imutáveis e schema antes desta chamada).

    Returns:
        Cópia de ``changes`` com ``atualizado_em`` definido para agora.
    """
    full_changes = dict(changes)
    full_changes["atualizado_em"] = _now_iso()
    return full_changes


def prepare_edge_properties(caller_props: dict[str, object], actor: Actor) -> dict[str, object]:
    """Mescla as propriedades de uma aresta com a proveniência derivada do ``Actor``.

    Args:
        caller_props: Propriedades específicas da relação enviadas pelo chamador.
        actor: Quem está criando a aresta.

    Returns:
        Dicionário completo: ``criado_em`` e ``criado_por`` sempre
        sobrescritos; ``origem``, ``status`` e ``evidencias`` recebem
        default quando ausentes.
    """
    full_props = dict(caller_props)
    full_props["criado_em"] = _now_iso()
    full_props["criado_por"] = actor.criado_por
    full_props.setdefault("origem", schema.DEFAULT_EDGE_ORIGEM)
    full_props.setdefault("status", schema.DEFAULT_EDGE_STATUS)
    full_props.setdefault("evidencias", [])
    return full_props
