"""Exceções da camada de conhecimento (``src.knowledge``).

Todas derivam de ``GraphStoreError`` para permitir captura genérica pelos
chamadores, mas cada uma carrega informação suficiente para uma mensagem
acionável (Princípio 6, AGENTS.md — falhar de forma explícita).
"""

from __future__ import annotations


class GraphStoreError(Exception):
    """Erro base de qualquer operação em ``GraphStore``."""


class UnknownLabelError(GraphStoreError):
    """Rótulo de nó não definido em ``src.knowledge.schema``."""

    def __init__(self, label: str) -> None:
        super().__init__(f"Rótulo de nó desconhecido: '{label}'.")
        self.label = label


class UnknownPropertyError(GraphStoreError):
    """Propriedade enviada não existe no schema do rótulo."""

    def __init__(self, label: str, prop: str) -> None:
        super().__init__(f"Propriedade '{prop}' desconhecida para o rótulo '{label}'.")
        self.label = label
        self.prop = prop


class MissingRequiredPropertyError(GraphStoreError):
    """Propriedade obrigatória ausente na escrita."""

    def __init__(self, label: str, prop: str) -> None:
        super().__init__(f"Propriedade obrigatória '{prop}' ausente para o rótulo '{label}'.")
        self.label = label
        self.prop = prop


class InvalidEnumValueError(GraphStoreError):
    """Valor fora da enumeração permitida para a propriedade."""

    def __init__(self, label: str, prop: str, value: object, allowed: tuple[str, ...]) -> None:
        super().__init__(
            f"Valor inválido '{value}' para '{label}.{prop}'. Valores permitidos: {', '.join(allowed)}."
        )
        self.label = label
        self.prop = prop
        self.value = value
        self.allowed = allowed


class MissingJustificationError(GraphStoreError):
    """Nó criado por agente sem 'justificativa_criacao' (proveniência obrigatória)."""

    def __init__(self, label: str) -> None:
        super().__init__(
            f"Nó '{label}' criado por agente requer 'justificativa_criacao' não vazia e 'nos_consultados'."
        )
        self.label = label


class DisallowedRelationError(GraphStoreError):
    """Aresta cujo par (rótulo origem, tipo, rótulo destino) não está na whitelist."""

    def __init__(self, src_label: str, rel: str, dst_label: str) -> None:
        super().__init__(
            f"Relação '{rel}' não permitida de '{src_label}' para '{dst_label}'."
        )
        self.src_label = src_label
        self.rel = rel
        self.dst_label = dst_label


class ImmutableFieldError(GraphStoreError):
    """Tentativa de alterar campo imutável via ``update_node``."""

    def __init__(self, field: str) -> None:
        super().__init__(f"Campo '{field}' é imutável e não pode ser alterado por update_node.")
        self.field = field


class NodeNotFoundError(GraphStoreError):
    """Nó referenciado não existe no grafo."""

    def __init__(self, node_id: str) -> None:
        super().__init__(f"Nó '{node_id}' não encontrado.")
        self.node_id = node_id


class ReadOnlyQueryViolation(GraphStoreError):
    """Consulta livre (``read_query``) contém operação de escrita ou token proibido."""

    def __init__(self, keyword: str) -> None:
        super().__init__(
            f"Consulta livre recusada: contém token proibido '{keyword}'. "
            "read_query aceita apenas leitura e não permite o literal '$$' (fecharia o "
            "dollar-quote SQL usado para encapsular a consulta)."
        )
        self.keyword = keyword


class GraphQueryTimeoutError(GraphStoreError):
    """Consulta excedeu ``KNOWLEDGE_READ_TIMEOUT_MS``."""

    def __init__(self, timeout_ms: int) -> None:
        super().__init__(f"Consulta cancelada: excedeu o timeout de {timeout_ms}ms.")
        self.timeout_ms = timeout_ms


class HumanConfirmationRequiredError(GraphStoreError):
    """Escrita que cria ou altera um estado reservado ao pesquisador foi feita por outro ator."""

    def __init__(self, label: str, field: str, actor_kind: str) -> None:
        super().__init__(
            f"Somente o pesquisador pode criar, confirmar ou rebaixar '{label}.{field}'; "
            f"ator '{actor_kind}' recusado (ADR 015, confirmação humana do Problema)."
        )
        self.label = label
        self.field = field
        self.actor_kind = actor_kind


class FactWriteNotAllowedError(GraphStoreError):
    """Agente tentou criar ou alterar um fato estrutural (escrito só pela ingestão determinística do orquestrador)."""

    def __init__(self, label: str, actor_kind: str) -> None:
        super().__init__(
            f"'{label}' é um fato estrutural, escrito só pela ingestão do orquestrador; ator '{actor_kind}' recusado."
        )
        self.label = label


class EdgeUpdateNotAllowedError(GraphStoreError):
    """``update_edge`` fora da política: ator não autorizado ou relação protegida."""

    def __init__(self, rel: str, actor_kind: str, reason: str) -> None:
        super().__init__(f"update_edge recusado em '{rel}' (ator '{actor_kind}'): {reason}.")
        self.rel = rel
        self.actor_kind = actor_kind
