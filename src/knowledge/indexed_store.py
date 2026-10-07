"""``GraphStore`` com gancho pós-escrita do índice semântico (ADR 015 §6, fluxo de escrita).

``IndexedGraphStore`` envolve um ``GraphStore`` (AGE ou em memória) sem alterar
a sua implementação:

1. ``create_node``/``update_node`` gravam o nó no grafo (fonte da verdade) com
   ``estado_vetorizacao="pendente"`` quando o texto canônico é novo ou mudou.
2. Em seguida chamam ``SemanticIndex.upsert`` (embedding local -> Qdrant ->
   ``estado_vetorizacao="ok"``).
3. Falha no passo 2 **não desfaz o nó**: ele permanece ``pendente`` e
   ``SemanticIndex.reconcile`` o corrige depois.

Alterar só campos fora do texto canônico (ex.: ``status``) não revetoriza; apenas
o payload do ponto é atualizado.
"""

from __future__ import annotations

from typing import Any

from src.knowledge import schema
from src.knowledge.errors import ImmutableFieldError
from src.knowledge.graph_store import GraphStore, Node, Subgraph
from src.knowledge.provenance import Actor
from src.knowledge.semantic_index import SemanticIndex, canonical_text
from src.logger import get_logger

logger = get_logger(__name__)

_ESTADO = "estado_vetorizacao"


class IndexedGraphStore(GraphStore):
    """Decorator de ``GraphStore`` que mantém o índice semântico em dia."""

    def __init__(self, inner: GraphStore, index: SemanticIndex) -> None:
        """Inicializa o decorator.

        Args:
            inner: Store real. O mesmo objeto deve ser o ``store`` do ``index``
                (sem este gancho), para não haver recursão.
            index: Índice semântico.
        """
        self._inner = inner
        self._index = index

    # -- Escrita -------------------------------------------------------------

    def create_node(self, label: str, props: dict[str, Any], *, actor: Actor) -> str:
        if _ESTADO in props:
            raise ImmutableFieldError(_ESTADO)
        vectorizable = label in schema.VECTORIZABLE_LABELS
        if vectorizable:
            props = {**props, _ESTADO: schema.ESTADO_VETORIZACAO_PENDENTE}
        node_id = self._inner.create_node(label, props, actor=actor)
        if vectorizable:
            node = self._inner.get_node(node_id)
            if node is not None:
                self._index_node(node)
        return node_id

    def update_node(self, node_id: str, changes: dict[str, Any], *, actor: Actor) -> None:
        if _ESTADO in changes:
            raise ImmutableFieldError(_ESTADO)
        old = self._inner.get_node(node_id)
        if old is None or old.label not in schema.VECTORIZABLE_LABELS:
            self._inner.update_node(node_id, changes, actor=actor)
            return

        merged = {**old.properties, **changes}
        text_changed = canonical_text(old.label, old.properties) != canonical_text(old.label, merged)
        was_pending = old.properties.get(_ESTADO) == schema.ESTADO_VETORIZACAO_PENDENTE
        effective = dict(changes)
        if text_changed:
            effective[_ESTADO] = schema.ESTADO_VETORIZACAO_PENDENTE
        self._inner.update_node(node_id, effective, actor=actor)

        new = self._inner.get_node(node_id)
        if new is None:
            return
        if text_changed or was_pending:
            self._index_node(new)
            if text_changed and old.label == "Dominio":
                self._mark_descendants(node_id)
        else:
            try:
                self._index.refresh_payload(new)
            except Exception as exc:  # noqa: BLE001 - payload velho não invalida o nó
                logger.warning(
                    "Falha ao atualizar o payload do índice semântico",
                    extra={"extra": {"node_id": node_id, "error": str(exc)}},
                )

    def _mark_descendants(self, node_id: str) -> None:
        """Termo ou sinônimos de um ancestral mudaram: descendentes ficam pendentes (v17-domain-search §3)."""
        try:
            self._index.mark_descendants_pending(node_id)
        except Exception as exc:  # noqa: BLE001 - a reconciliação pelo text_hash cobre a falha
            logger.warning(
                "Falha ao marcar os descendentes do domínio como pendentes",
                extra={"extra": {"node_id": node_id, "error": str(exc)}},
            )

    def _index_node(self, node: Node) -> None:
        """Gancho pós-escrita: falha deixa o nó ``pendente`` (reconciliação corrige)."""
        try:
            self._index.upsert(node)
        except Exception as exc:  # noqa: BLE001 - o grafo é a fonte da verdade
            logger.warning(
                "Vetorização falhou; nó permanece pendente até a reconciliação",
                extra={"extra": {"node_id": node.id, "label": node.label, "error": str(exc)}},
            )

    def create_edge(self, src_id: str, rel: str, dst_id: str, props: dict[str, Any], *, actor: Actor) -> None:
        self._inner.create_edge(src_id, rel, dst_id, props, actor=actor)
        if rel == "NO_DOMINIO":
            # O domínio só é atribuído depois da criação do nó: reavalia os pares dele.
            node = self._inner.get_node(src_id)
            if node is not None and node.label in schema.VECTORIZABLE_LABELS:
                self._index.notify_changed(node)

    def set_edge_status(self, src_id: str, rel: str, dst_id: str, status: str, *, actor: Actor) -> None:
        self._inner.set_edge_status(src_id, rel, dst_id, status, actor=actor)

    def update_edge(self, src_id: str, rel: str, dst_id: str, changes: dict[str, Any], *, actor: Actor) -> None:
        self._inner.update_edge(src_id, rel, dst_id, changes, actor=actor)

    def record_audit_note(self, node_id: str, actor: Actor, note: dict[str, Any]) -> None:
        self._inner.record_audit_note(node_id, actor, note)

    # -- Leitura (delegada) --------------------------------------------------

    def audit_history(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._inner.audit_history(node_id, limit)

    def get_node(self, node_id: str) -> Node | None:
        return self._inner.get_node(node_id)

    def find_nodes(self, label: str, filters: dict[str, Any], limit: int = 50) -> list[Node]:
        return self._inner.find_nodes(label, filters, limit)

    def list_nodes(self, label: str, *, after_id: str | None = None, limit: int = 200) -> list[Node]:
        return self._inner.list_nodes(label, after_id=after_id, limit=limit)

    def neighbors(
        self, node_id: str, rels: list[str] | None, direction: str = "both", depth: int = 1
    ) -> Subgraph:
        return self._inner.neighbors(node_id, rels, direction, depth)

    def project_subgraph(self, projeto_id: str, labels: list[str] | None = None) -> Subgraph:
        return self._inner.project_subgraph(projeto_id, labels)

    def read_query(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return self._inner.read_query(cypher, params)
