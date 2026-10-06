"""Índice semântico do grafo de conhecimento no Qdrant (ADR 015 §6, ADR 011 §3).

Mantém a coleção ``config.KNOWLEDGE_COLLECTION`` com **um ponto por nó
vetorizável**, usando como ID do ponto o **mesmo ID do nó** no grafo. O grafo é
a fonte da verdade: se a vetorização falha, o nó continua válido com
``estado_vetorizacao="pendente"`` e ``reconcile()`` corrige depois.

Embeddings são sempre locais (``src.embeddings``); nenhum texto ou vetor sai do
computador.

Contém:
    - ``canonical_text``: texto canônico por rótulo.
    - ``SemanticIndex``: ``upsert``/``reconcile``/``similar`` e a consulta
      híbrida ``related_experience``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from src import config
from src.embeddings.base import EmbeddingProvider, embedding_payload, get_embedding_provider, text_hash
from src.knowledge import schema
from src.knowledge.domains import descendant_ids, domain_ancestors, node_domains
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.provenance import Actor
from src.logger import get_logger

logger = get_logger(__name__)

_SYSTEM_ACTOR = Actor(kind="orquestrador")

# Campos concatenados (com rótulo, na ordem) no texto canônico de cada tipo de nó.
_CANONICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "Projeto": ("titulo", "objetivo"),
    "Problema": ("titulo", "resumo", "classe", "caracteristicas_dados", "criterio_sucesso"),
    "Hipotese": ("enunciado", "justificativa"),
    "Abordagem": ("nome", "tipo", "descricao"),
    "Descoberta": ("tipo", "enunciado", "condicoes"),
    "Decisao": ("contexto", "justificativa"),
    "Oportunidade": ("enunciado", "justificativa"),
    "Metrica": ("nome", "sinonimos", "familia"),
}

# Campos de payload com índice ``keyword`` (filtro por subárvore e por nível do ``Dominio``).
_KEYWORD_INDEXES = ("caminho_ids", "nivel")

# Limite de nós lidos por rótulo na reconciliação (``find_nodes`` não pagina).
_RECONCILE_RETRIEVE_BATCH = 64

# Pares/itens com estes ``status`` não participam de buscas nem de candidatos.
IGNORED_STATUSES = frozenset({"substituida", "rejeitado", "rejeitada"})
# Chaves de payload aceitas em ``filters`` (falha cedo em vez de devolver vazio).
FILTERABLE_PAYLOAD_KEYS = frozenset(
    {"tipo_no", "projeto_id", "dominios", "status", "visibilidade", "veredito", "criado_em",
     "embedding_model", "embedding_version"}
)


class ForeignCollectionError(RuntimeError):
    """A coleção alvo não pertence a esta aplicação; recusa explícita de apagá-la/recriá-la."""


class IndexDimensionError(RuntimeError):
    """A coleção existente tem dimensão diferente da do modelo de embedding atual.

    Recriar a coleção é uma operação destrutiva (os vetores são descartados e
    refeitos a partir do grafo): exige confirmação explícita do pesquisador
    (``geminiclaw knowledge reindex``).
    """


def _format_value(value: Any) -> str:
    """Converte um valor de propriedade em texto (listas e mapas viram texto legível)."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(_format_value(v) for v in value if _format_value(v))
    if isinstance(value, dict):
        return ", ".join(f"{k}={_format_value(v)}" for k, v in sorted(value.items()) if _format_value(v))
    return str(value).strip()


# Rótulo de linha por nível dos ancestrais no texto do ``Dominio`` (a própria linha ``Nível`` cobre o termo).
_ANCESTOR_LINE_LABEL = {"grande_area": "Grande área", "area": "Área", "subarea": "Subárea"}
# Níveis do vocabulário, do mais amplo ao mais específico.
DOMAIN_LEVELS: tuple[str, ...] = ("grande_area", "area", "subarea", "especialidade")


def domain_canonical_text(node: Node, ancestors: list[Node]) -> str:
    """Texto canônico hierárquico de um ``Dominio`` (v17-domain-search §1).

    Função pura: não consulta o banco. Campos nomeados e em ordem fixa, de modo que o
    mesmo conteúdo gera sempre o mesmo texto (e o mesmo ``text_hash``). Os sinônimos
    candidatos não entram (ainda não foram aprovados).

    Args:
        node: Nó ``Dominio``.
        ancestors: Ancestrais já resolvidos, da raiz (grande área) ao pai imediato.

    Returns:
        O texto; string vazia se o nó não tem ``termo``.
    """
    termo = _format_value(node.properties.get("termo"))
    if not termo:
        return ""
    nivel = _format_value(node.properties.get("nivel"))
    path = [_format_value(a.properties.get("termo")) for a in ancestors] + [termo]
    lines = [f"Domínio: {termo}", f"Nível: {nivel}", f"Caminho: {' > '.join(path)}"]
    for ancestor in ancestors:
        label = _ANCESTOR_LINE_LABEL.get(str(ancestor.properties.get("nivel")))
        if label:
            lines.append(f"{label}: {_format_value(ancestor.properties.get('termo'))}")
    raw = node.properties.get("sinonimos") or []
    sinonimos = [t for t in (_format_value(item) for item in raw) if t] if isinstance(raw, (list, tuple)) else []
    if sinonimos:
        lines.append(f"Sinônimos: {'; '.join(sinonimos)}")
    return "\n".join(lines)


def canonical_text(label: str, props: dict[str, Any]) -> str | None:
    """Monta o texto canônico de um nó (campos concatenados com rótulos, na ordem).

    Args:
        label: Rótulo do nó.
        props: Propriedades do nó.

    Returns:
        O texto canônico (``"campo: valor"`` por linha), ou ``None`` se o
        rótulo não é vetorizado (``Sessao``, ``Insumo``, ``Experimento``,
        ``Resultado``). String vazia se nenhum campo textual está preenchido.
    """
    if label == "Dominio":
        # Sem o grafo não há ancestrais: serve à detecção de mudança dos campos do próprio nó.
        # O texto indexado de verdade usa os ancestrais (``SemanticIndex.text_for``).
        return domain_canonical_text(Node(id="", label=label, properties=props), [])
    fields = _CANONICAL_FIELDS.get(label)
    if fields is None:
        return None
    lines = []
    for name in fields:
        text = _format_value(props.get(name))
        if text:
            lines.append(f"{name}: {text}")
    return "\n".join(lines)


@dataclass(frozen=True)
class Hit:
    """Resultado de uma busca semântica.

    Attributes:
        node_id: ID do nó (= ID do ponto).
        label: Rótulo do nó (``tipo_no``).
        score: Similaridade cosseno.
        payload: Payload completo do ponto (inclui ``text_hash`` e metadados de embedding).
    """

    node_id: str
    label: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class ExperienceItem:
    """Item da consulta híbrida ``related_experience``.

    Attributes:
        node: Nó recuperado no grafo (``Abordagem``, ``Descoberta`` ou ``Decisao``).
        kind: ``"funcionou"``, ``"falhou"``, ``"descoberta"`` ou ``"decisao"``.
        origem_problema_id: ``Problema`` similar de onde o item foi alcançado.
        similarity: Similaridade do problema de origem com o problema consultado.
        confidence: Confiança usada no ranking (já com piso aplicado).
        recency: Fator de recência (0,5 ^ idade_dias / meia-vida).
        rank: ``similarity × confidence × recency``.
    """

    node: Node
    kind: str
    origem_problema_id: str
    similarity: float
    confidence: float
    recency: float
    rank: float


@dataclass
class ReconcileReport:
    """Resultado de ``SemanticIndex.reconcile``.

    Attributes:
        checked: Nós vetorizáveis examinados.
        reindexed: Nós (re)vetorizados com sucesso.
        payload_refreshed: Nós cujo payload (status, visibilidade, projeto) divergia e foi atualizado.
        failed: Nós cuja vetorização falhou (continuam ``pendente``).
        elapsed_seconds: Duração.
    """

    checked: int = 0
    reindexed: int = 0
    payload_refreshed: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class SemanticIndex:
    """Índice semântico dos nós do grafo (coleção Qdrant ``knowledge_nodes``)."""

    def __init__(
        self,
        store: GraphStore,
        client: QdrantClient,
        *,
        provider: EmbeddingProvider | None = None,
        collection: str | None = None,
    ) -> None:
        """Inicializa o índice.

        Args:
            store: Grafo **sem** o gancho de indexação (o ``GraphStore`` cru),
                usado para ler nós e gravar ``estado_vetorizacao``.
            client: Cliente Qdrant.
            provider: Provedor de embeddings local. Padrão: singleton do processo.
            collection: Nome da coleção. Padrão: ``config.KNOWLEDGE_COLLECTION``.
        """
        self._store = store
        self._client = client
        self._provider_arg = provider  # resolvido sob demanda (não carrega o modelo ao montar o índice)
        self.collection = collection or config.KNOWLEDGE_COLLECTION
        self._ready = False
        self._listeners: list[Callable[[Node], None]] = []

    # -- Infra ---------------------------------------------------------------

    @property
    def _provider(self) -> EmbeddingProvider:
        return self._provider_arg or get_embedding_provider()

    @property
    def embedding_info(self) -> Any:
        """Metadados (modelo, versão, dimensão) do provedor de embeddings em uso."""
        return self._provider.info

    def add_listener(self, listener: Callable[[Node], None]) -> None:
        """Registra um callback chamado após cada nó indexado com sucesso.

        Falhas do callback são registradas em log e não afetam a indexação
        (usado pela geração de candidatos da fila de similaridade).
        """
        self._listeners.append(listener)

    def ensure_collection(self, *, allow_recreate: bool = False) -> None:
        """Garante que a coleção existe com a dimensão do modelo atual.

        Args:
            allow_recreate: Se True e a dimensão difere, recria a coleção vazia
                (os pontos são refeitos a partir do grafo por ``reconcile``).

        Raises:
            IndexDimensionError: Dimensão diferente e ``allow_recreate`` é False.
        """
        dim = self._provider.info.dimension
        names = {c.name for c in self._client.get_collections().collections}
        if self.collection not in names:
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            self._ensure_payload_indexes()
            self._ready = True
            return
        current = self._client.get_collection(self.collection).config.params.vectors.size
        if current != dim:
            self._assert_owned_collection()
            if not allow_recreate:
                raise IndexDimensionError(
                    f"A coleção '{self.collection}' tem dimensão {current}, mas o modelo atual produz {dim}. "
                    "Rode `geminiclaw knowledge reindex` para recriá-la a partir do grafo (exige confirmação)."
                )
            logger.warning(
                "Dimensão do modelo mudou; recriando coleção do índice semântico a partir do grafo",
                extra={"extra": {"collection": self.collection, "old_dim": current, "new_dim": dim}},
            )
            self._client.delete_collection(self.collection)
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
        self._ensure_payload_indexes()
        self._ready = True

    def _ensure_payload_indexes(self) -> None:
        """Cria (idempotente) os índices ``keyword`` usados pela busca de domínio (v17-domain-search §2)."""
        for key in _KEYWORD_INDEXES:
            self._client.create_payload_index(
                collection_name=self.collection, field_name=key, field_schema=PayloadSchemaType.KEYWORD
            )

    def _assert_owned_collection(self) -> None:
        """Recusa apagar uma coleção que não seja desta aplicação.

        Só a coleção ``config.KNOWLEDGE_COLLECTION`` pode ser recriada, e apenas se
        todos os seus pontos têm ``tipo_no`` de um rótulo vetorizável (nenhum ponto
        "estrangeiro", como os de uma coleção de documentos).

        Raises:
            ForeignCollectionError: Nome diferente de ``KNOWLEDGE_COLLECTION`` ou ponto estrangeiro.
        """
        if self.collection != config.KNOWLEDGE_COLLECTION:
            raise ForeignCollectionError(
                f"Recusado: '{self.collection}' não é a coleção do índice semântico "
                f"('{config.KNOWLEDGE_COLLECTION}'); nada foi apagado."
            )
        foreign, _ = self._client.scroll(
            collection_name=self.collection,
            scroll_filter=Filter(
                must_not=[FieldCondition(key="tipo_no", match=MatchAny(any=sorted(schema.VECTORIZABLE_LABELS)))]
            ),
            limit=1,
            with_payload=False,
        )
        if foreign:
            raise ForeignCollectionError(
                f"Recusado: a coleção '{self.collection}' contém pontos que não são nós do grafo "
                "(sem `tipo_no` de rótulo vetorizável); nada foi apagado. Aponte KNOWLEDGE_COLLECTION "
                "para uma coleção própria."
            )

    def _ensure_ready(self) -> None:
        if not self._ready:
            self.ensure_collection()

    def _domain_chain(self, node: Node) -> tuple[list[Node], bool] | None:
        """Ancestrais e completude da cadeia de um ``Dominio`` (``None`` para outros rótulos)."""
        return domain_ancestors(self._store, node) if node.label == "Dominio" else None

    def text_for(self, node: Node, chain: tuple[list[Node], bool] | None = None) -> str | None:
        """Texto canônico efetivo de um nó; para o ``Dominio``, o texto hierárquico com ancestrais.

        Args:
            node: Nó do grafo.
            chain: Ancestrais já resolvidos (evita reconsultar o grafo).
        """
        if node.label != "Dominio":
            return canonical_text(node.label, node.properties)
        ancestors, _ = chain if chain is not None else domain_ancestors(self._store, node)
        return domain_canonical_text(node, ancestors)

    def _payload(
        self, node: Node, text: str, chain: tuple[list[Node], bool] | None = None
    ) -> dict[str, Any]:
        props = node.properties
        payload: dict[str, Any] = {
            "tipo_no": node.label,
            "projeto_id": props.get("projeto_id"),
            "dominios": sorted(node_domains(self._store, node)),
            "status": props.get("status"),
            "visibilidade": props.get("visibilidade"),
            "criado_em": props.get("criado_em"),
        }
        if props.get("veredito") is not None:
            payload["veredito"] = props["veredito"]
        if node.label == "Dominio":
            ancestors, complete = chain if chain is not None else domain_ancestors(self._store, node)
            payload["nivel"] = props.get("nivel")
            payload["caminho_ids"] = [a.id for a in ancestors] + [node.id]
            payload["caminho_termos"] = [str(a.properties.get("termo")) for a in ancestors] + [
                str(props.get("termo"))
            ]
            payload["caminho_completo"] = complete
            payload["codigo_cnpq"] = props.get("codigo_cnpq")
        payload.update(embedding_payload(text, self._provider))
        return payload

    # -- Escrita -------------------------------------------------------------

    def upsert(self, node: Node) -> bool:
        """Vetoriza um nó e grava seu ponto (ID do ponto = ID do nó).

        Marca ``estado_vetorizacao="ok"`` no grafo ao final. Qualquer falha
        (embedding, Qdrant) é propagada: o chamador decide (o gancho
        pós-escrita a registra e deixa o nó ``pendente``).

        Args:
            node: Nó (já gravado no grafo).

        Returns:
            True se o nó foi indexado; False se o rótulo não é vetorizado ou o
            texto canônico está vazio.
        """
        return self.upsert_many([node]) == 1

    def upsert_many(self, nodes: list[Node]) -> int:
        """Vetoriza e grava um lote de nós. Ver ``upsert``.

        Returns:
            Quantidade de nós indexados.
        """
        items: list[tuple[Node, str, tuple[list[Node], bool] | None]] = []
        for node in nodes:
            chain = self._domain_chain(node)
            text = self.text_for(node, chain)
            if text:
                items.append((node, text, chain))
        if not items:
            return 0
        self._ensure_ready()
        vectors = self._provider.embed_documents([text for _, text, _ in items])
        points = [
            PointStruct(id=node.id, vector=vector, payload=self._payload(node, text, chain))
            for (node, text, chain), vector in zip(items, vectors)
        ]
        self._client.upsert(collection_name=self.collection, points=points)
        for node, _, _ in items:
            if node.properties.get("estado_vetorizacao") != schema.ESTADO_VETORIZACAO_OK:
                self._store.update_node(
                    node.id, {"estado_vetorizacao": schema.ESTADO_VETORIZACAO_OK}, actor=_SYSTEM_ACTOR
                )
        for node, _, _ in items:
            self._notify(node)
        return len(items)

    def notify_changed(self, node: Node) -> None:
        """Reaciona a uma mudança que afeta a varredura de candidatos sem mudar o texto.

        Chamado, por exemplo, quando um ``NO_DOMINIO`` é criado: o domínio muda
        a classificação "entre domínios" dos pares do nó. Atualiza o payload
        (``dominios``) e reexecuta os listeners pós-indexação; pares já
        enfileirados não são duplicados pela fila.
        """
        try:
            self.refresh_payload(node)
        except Exception as exc:  # noqa: BLE001 - payload velho não invalida o grafo
            logger.warning(
                "Falha ao atualizar o payload após mudança de domínio",
                extra={"extra": {"node_id": node.id, "error": str(exc)}},
            )
        self._notify(node)

    def mark_descendants_pending(self, node_id: str) -> list[int]:
        """Marca como ``pendente`` os descendentes de um ``Dominio`` cujo texto depende dele.

        Chamado quando termo ou sinônimos de um ancestral mudam (v17-domain-search §3):
        o texto hierárquico dos descendentes muda e a reconciliação os revetoriza. A marcação
        é feita em lotes de ``DOMAIN_REINDEX_BATCH`` e nunca impede a escrita do ancestral:
        falha de um lote é registrada e o ``text_hash`` divergente ainda faz a reconciliação
        revetorizar o nó.

        Args:
            node_id: ID do ancestral que mudou.

        Returns:
            Tamanho de cada lote marcado (vazio se não há descendentes).
        """
        batch_size = max(config.DOMAIN_REINDEX_BATCH, 1)
        ids = descendant_ids(self._store, node_id)
        sizes: list[int] = []
        for start in range(0, len(ids), batch_size):
            batch = ids[start : start + batch_size]
            marked = 0
            for child_id in batch:
                try:
                    self._store.update_node(
                        child_id, {"estado_vetorizacao": schema.ESTADO_VETORIZACAO_PENDENTE}, actor=_SYSTEM_ACTOR
                    )
                    marked += 1
                except Exception as exc:  # noqa: BLE001 - a reconciliação pelo text_hash cobre a falha
                    logger.warning(
                        "Falha ao marcar descendente como pendente",
                        extra={"extra": {"node_id": child_id, "ancestor_id": node_id, "error": str(exc)}},
                    )
            sizes.append(marked)
        if sizes:
            logger.info(
                "Descendentes de domínio marcados como pendentes",
                extra={"extra": {"ancestor_id": node_id, "lotes": sizes}},
            )
        return sizes

    def _notify(self, node: Node) -> None:
        for listener in self._listeners:
            try:
                listener(node)
            except Exception as exc:  # noqa: BLE001 - listener não pode derrubar a indexação
                logger.warning(
                    "Falha em listener pós-indexação; indexação mantida",
                    extra={"extra": {"node_id": node.id, "error": str(exc)}},
                )

    def refresh_payload(self, node: Node) -> None:
        """Atualiza só o payload do ponto (sem revetorizar), quando o texto não mudou.

        Se o ponto ainda não existe, faz o ``upsert`` completo.
        """
        chain = self._domain_chain(node)
        text = self.text_for(node, chain)
        if not text:
            return
        self._ensure_ready()
        if not self._client.retrieve(self.collection, ids=[node.id], with_payload=False):
            self.upsert(node)
            return
        self._client.set_payload(
            collection_name=self.collection, payload=self._payload(node, text, chain), points=[node.id]
        )

    def reconcile(self, *, allow_recreate: bool = False) -> ReconcileReport:
        """Revetoriza nós ``pendente``, com ``text_hash`` divergente ou de outro modelo/versão.

        Roda no início de cada sessão e por ``geminiclaw knowledge reindex``.
        Quando não há pendências, o custo é uma leitura de pontos por lote.

        Args:
            allow_recreate: Permite recriar a coleção se a dimensão mudou.

        Returns:
            ``ReconcileReport`` com contagens.

        Raises:
            IndexDimensionError: Dimensão mudou e ``allow_recreate`` é False.
        """
        start = time.monotonic()
        report = ReconcileReport()
        self.ensure_collection(allow_recreate=allow_recreate)
        info = self._provider.info
        page_size = max(config.SIM_RECONCILE_BATCH_SIZE, 1)
        for label in sorted(schema.VECTORIZABLE_LABELS):
            after_id: str | None = None
            while True:
                # Páginas limitadas por cursor: memória constante, mesmo com milhares de nós.
                batch = self._store.list_nodes(label, after_id=after_id, limit=page_size)
                if not batch:
                    break
                after_id = batch[-1].id
                stale, payload_stale = self._stale_nodes(batch, info)
                report.checked += len(batch)
                for node in payload_stale:
                    try:
                        self.refresh_payload(node)
                        report.payload_refreshed += 1
                    except Exception as exc:  # noqa: BLE001 - payload velho não invalida o grafo
                        logger.warning(
                            "Falha ao atualizar payload na reconciliação",
                            extra={"extra": {"node_id": node.id, "error": str(exc)}},
                        )
                if stale:
                    try:
                        report.reindexed += self.upsert_many(stale)
                    except Exception as exc:  # noqa: BLE001 - lote falho fica pendente
                        report.failed += len(stale)
                        logger.warning(
                            "Falha ao revetorizar lote na reconciliação; nós permanecem pendentes",
                            extra={"extra": {"label": label, "size": len(stale), "error": str(exc)}},
                        )
                if len(batch) < page_size:
                    break
        report.elapsed_seconds = time.monotonic() - start
        logger.info(
            "Reconciliação do índice semântico concluída",
            extra={
                "extra": {
                    "checked": report.checked,
                    "reindexed": report.reindexed,
                    "payload_refreshed": report.payload_refreshed,
                    "failed": report.failed,
                    "elapsed_seconds": round(report.elapsed_seconds, 3),
                }
            },
        )
        return report

    def _stale_nodes(self, batch: list[Node], info: Any) -> tuple[list[Node], list[Node]]:
        """Separa nós a revetorizar (texto/modelo/estado) dos que só têm payload defasado."""
        points = {
            str(p.id): (p.payload or {})
            for p in self._client.retrieve(self.collection, ids=[n.id for n in batch], with_payload=True)
        }
        stale: list[Node] = []
        payload_stale: list[Node] = []
        for node in batch:
            text = self.text_for(node)
            if not text:
                continue
            payload = points.get(node.id)
            if (
                payload is None
                or node.properties.get("estado_vetorizacao") == schema.ESTADO_VETORIZACAO_PENDENTE
                or payload.get("text_hash") != text_hash(text)
                or payload.get("embedding_model") != info.model
                or payload.get("embedding_version") != info.version
            ):
                stale.append(node)
            elif any(
                payload.get(key) != node.properties.get(key) for key in ("status", "visibilidade", "projeto_id")
            ):
                payload_stale.append(node)
        return stale, payload_stale

    # -- Busca ---------------------------------------------------------------

    def _vector_for(self, text: str | None, node_id: str | None) -> list[float]:
        if (text is None) == (node_id is None):
            raise ValueError("Informe exatamente um entre `text` e `node_id`.")
        if text is not None:
            return self._provider.embed_query(text)
        found = self._client.retrieve(self.collection, ids=[node_id], with_vectors=True)
        if not found:
            raise ValueError(f"Nó '{node_id}' não está indexado em '{self.collection}'.")
        vector = found[0].vector
        if isinstance(vector, dict):
            vector = next(iter(vector.values()))
        return list(vector)  # type: ignore[arg-type]

    @staticmethod
    def _filter(
        labels: list[str], filters: dict[str, Any] | None, *, visible_to: str | None = None
    ) -> Filter:
        """Monta o filtro de payload.

        Sempre exclui nós com ``status`` em ``IGNORED_STATUSES``. Com ``visible_to``
        (``projeto_id`` do solicitante), só devolve nós do próprio projeto ou com
        ``visibilidade="compartilhavel"`` (nada de outro projeto privado).

        Raises:
            ValueError: Chave de ``filters`` fora de ``FILTERABLE_PAYLOAD_KEYS``.
        """
        must: list[Any] = [FieldCondition(key="tipo_no", match=MatchAny(any=list(labels)))]
        for key, value in (filters or {}).items():
            if key not in FILTERABLE_PAYLOAD_KEYS:
                raise ValueError(
                    f"Chave de filtro desconhecida: '{key}'. Válidas: {', '.join(sorted(FILTERABLE_PAYLOAD_KEYS))}."
                )
            match = MatchAny(any=list(value)) if isinstance(value, (list, tuple, set)) else MatchValue(value=value)
            must.append(FieldCondition(key=key, match=match))
        if visible_to is not None:
            must.append(
                Filter(
                    should=[
                        FieldCondition(key="projeto_id", match=MatchValue(value=visible_to)),
                        FieldCondition(key="visibilidade", match=MatchValue(value="compartilhavel")),
                    ]
                )
            )
        must_not = [FieldCondition(key="status", match=MatchAny(any=sorted(IGNORED_STATUSES)))]
        return Filter(must=must, must_not=must_not)

    def _query(
        self, vector: list[float], labels: list[str], filters: dict[str, Any] | None, min_score: float,
        limit: int, offset: int, visible_to: str | None = None,
    ) -> list[Hit]:
        self._ensure_ready()
        response = self._client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=self._filter(labels, filters, visible_to=visible_to),
            score_threshold=min_score if min_score > 0 else None,
            limit=limit,
            offset=offset,
            with_payload=True,
        )
        return [
            Hit(node_id=str(p.id), label=(p.payload or {}).get("tipo_no", ""), score=p.score, payload=p.payload or {})
            for p in response.points
        ]

    def similar(
        self,
        *,
        text: str | None = None,
        node_id: str | None = None,
        labels: list[str],
        filters: dict | None = None,
        min_score: float = 0.0,
        limit: int = 20,
        projeto_id: str | None = None,
    ) -> list[Hit]:
        """Busca nós semanticamente próximos (buscar não grava nada).

        Nós com ``status`` ``substituida``/``rejeitado``/``rejeitada`` nunca são devolvidos.

        Args:
            text: Texto de consulta (exclusivo com ``node_id``).
            node_id: Nó já indexado cujo vetor serve de consulta (o próprio nó é excluído).
            labels: Rótulos a considerar.
            filters: Filtros de payload (igualdade; listas viram "qualquer de"); chaves
                restritas a ``FILTERABLE_PAYLOAD_KEYS``.
            min_score: Similaridade mínima.
            limit: Máximo de resultados.
            projeto_id: Se informado, restringe aos nós desse projeto ou
                ``compartilhavel`` (visão de um solicitante sem acesso aos privados de
                outros projetos). Se omitido, é a visão local do pesquisador.

        Returns:
            Hits ordenados por similaridade decrescente.

        Raises:
            ValueError: Chave de ``filters`` desconhecida.
        """
        self._filter(labels, filters)  # valida as chaves antes de gastar embedding
        vector = self._vector_for(text, node_id)
        extra = 1 if node_id else 0
        hits = self._query(vector, labels, filters, min_score, limit + extra, 0, visible_to=projeto_id)
        return [h for h in hits if h.node_id != node_id][:limit]

    def search_domains(
        self,
        query: str,
        *,
        statuses: list[str],
        levels: list[str],
        within: str | None = None,
        limit: int = 15,
    ) -> list[Hit]:
        """Busca somente leitura de pontos ``Dominio`` (v17-domain-search §4).

        Os filtros são objetos tipados do Qdrant (nada é interpolado em texto de consulta)
        e a coleção não é criada nem alterada: se não existe, o erro do Qdrant sobe.

        Args:
            query: Texto já no molde do texto canônico (``Domínio: ...``).
            statuses: ``status`` aceitos (``aprovado``, ``candidato``).
            levels: Níveis aceitos (subconjunto de ``DOMAIN_LEVELS``).
            within: ID de um ``Dominio``; restringe à sua subárvore (``caminho_ids``).
            limit: Máximo de pontos.

        Returns:
            Hits por similaridade decrescente (sem corte de escore mínimo).

        Raises:
            ValueError: Status ou nível fora do conjunto válido.
        """
        if not set(statuses) <= {"aprovado", "candidato"} or not statuses:
            raise ValueError(f"Status de domínio inválido: {statuses!r}.")
        if not set(levels) <= set(DOMAIN_LEVELS) or not levels:
            raise ValueError(f"Nível de domínio inválido: {levels!r}.")
        must: list[Any] = [
            FieldCondition(key="tipo_no", match=MatchValue(value="Dominio")),
            FieldCondition(key="status", match=MatchAny(any=list(statuses))),
            FieldCondition(key="nivel", match=MatchAny(any=list(levels))),
        ]
        if within is not None:
            must.append(FieldCondition(key="caminho_ids", match=MatchValue(value=within)))
        response = self._client.query_points(
            collection_name=self.collection,
            query=self._provider.embed_query(query),
            query_filter=Filter(must=must),
            limit=limit,
            with_payload=True,
        )
        return [
            Hit(node_id=str(p.id), label="Dominio", score=p.score, payload=p.payload or {})
            for p in response.points
        ]

    def iter_neighbors(
        self, node_id: str, labels: list[str], min_score: float, page_size: int
    ) -> Iterator[Hit]:
        """Itera, paginando, todos os vizinhos de um nó com similaridade >= ``min_score``.

        Sem teto de quantidade (o volume é controlado pela fila de revisão).
        """
        vector = self._vector_for(None, node_id)
        offset = 0
        while True:
            page = self._query(vector, labels, None, min_score, page_size, offset)
            for hit in page:
                if hit.node_id != node_id:
                    yield hit
            if len(page) < page_size:
                return
            offset += page_size

    # -- Consulta híbrida ----------------------------------------------------

    def related_experience(
        self,
        problema_id: str,
        limit: int = 10,
        *,
        now: datetime | None = None,
        restrict_to_visible: bool = False,
    ) -> list[ExperienceItem]:
        """"O que já funcionou ou falhou em problemas parecidos?" (Qdrant -> grafo -> ranking).

        1. Busca problemas similares (``SIM_RELATED_MIN_CROSS``).
        2. No grafo, a partir de cada um: ``Abordagem-FUNCIONOU_PARA|FALHOU_PARA->Problema``,
           ``Descoberta-SOBRE->Problema`` (status ``ativa``) e ``Decisao`` do projeto.
        3. ``rank = similaridade × max(confianca, CONFIDENCE_FLOOR) × recencia``, com
           ``recencia = 0,5 ^ (idade_dias / RECENCY_HALF_LIFE_DAYS)``. A data usada é a
           da aresta (``Abordagem``) ou a de criação do nó (``Descoberta``/``Decisao``).

        Args:
            problema_id: ``Problema`` de referência (deve estar indexado).
            limit: Máximo de itens devolvidos.
            now: Instante de referência (injetável em testes).
            restrict_to_visible: Se True, só considera nós do projeto de ``problema_id`` ou
                ``compartilhavel`` (nada de outro projeto privado) — usar quando o
                consumidor não é o pesquisador local (ex.: registros remotos, ADR 013).
                O padrão (False) é a visão local, em que todos os projetos são do mesmo
                pesquisador.

        Nós com ``status`` ``substituida``/``rejeitado``/``rejeitada`` são sempre ignorados.

        Returns:
            Itens ordenados por ``rank`` decrescente; um item por nó (o de maior rank).
        """
        now = now or datetime.now(timezone.utc)
        origin = self._store.get_node(problema_id)
        requester = origin.properties.get("projeto_id") if (origin and restrict_to_visible) else None
        if restrict_to_visible and requester is None:
            raise ValueError(f"Problema '{problema_id}' sem projeto: não é possível restringir a visibilidade.")
        similar = self.similar(
            node_id=problema_id, labels=["Problema"], min_score=config.SIM_RELATED_MIN_CROSS, limit=50,
            projeto_id=requester,
        )

        def _allowed(node: Node) -> bool:
            if node.properties.get("status") in IGNORED_STATUSES:
                return False
            if requester is None:
                return True
            return (
                node.properties.get("projeto_id") == requester
                or node.properties.get("visibilidade") == "compartilhavel"
            )
        best: dict[str, ExperienceItem] = {}

        def _consider(item: ExperienceItem) -> None:
            current = best.get(item.node.id)
            if current is None or item.rank > current.rank:
                best[item.node.id] = item

        for hit in similar:
            problema = self._store.get_node(hit.node_id)
            if problema is None:
                continue
            sub = self._store.neighbors(
                hit.node_id, ["FUNCIONOU_PARA", "FALHOU_PARA", "SOBRE"], direction="in", depth=1
            )
            nodes = {n.id: n for n in sub.nodes}
            for edge in sub.edges:
                if edge.dst_id != hit.node_id or edge.src_id not in nodes:
                    continue
                other = nodes[edge.src_id]
                if not _allowed(other):
                    continue
                if edge.rel_type in ("FUNCIONOU_PARA", "FALHOU_PARA") and other.label == "Abordagem":
                    kind = "funcionou" if edge.rel_type == "FUNCIONOU_PARA" else "falhou"
                    confidence = self._edge_confidence(edge.properties.get("descoberta_id"))
                    stamp = edge.properties.get("criado_em") or other.properties.get("criado_em")
                elif edge.rel_type == "SOBRE" and other.label == "Descoberta":
                    if other.properties.get("status") != "ativa":
                        continue
                    kind = "descoberta"
                    confidence = self._node_confidence(other)
                    stamp = other.properties.get("criado_em")
                else:
                    continue
                _consider(self._item(other, kind, hit, confidence, stamp, now))
            hit_projeto = problema.properties.get("projeto_id")
            if hit_projeto:
                for decisao in self._store.find_nodes("Decisao", {"projeto_id": hit_projeto}, limit=limit):
                    if not _allowed(decisao):
                        continue
                    _consider(
                        self._item(decisao, "decisao", hit, None, decisao.properties.get("criado_em"), now)
                    )
        return sorted(best.values(), key=lambda i: i.rank, reverse=True)[:limit]

    @staticmethod
    def _node_confidence(node: Node) -> float | None:
        confianca = node.properties.get("confianca")
        if confianca is None and node.properties.get("veredito") is not None:
            confianca = abs(float(node.properties["veredito"]))
        return None if confianca is None else float(confianca)

    def _edge_confidence(self, descoberta_id: str | None) -> float | None:
        if not descoberta_id:
            return None
        descoberta = self._store.get_node(descoberta_id)
        return None if descoberta is None else self._node_confidence(descoberta)

    @staticmethod
    def _item(
        node: Node, kind: str, hit: Hit, confidence: float | None, stamp: Any, now: datetime
    ) -> ExperienceItem:
        conf = max(confidence if confidence is not None else 0.0, config.CONFIDENCE_FLOOR)
        created = _parse_ts(stamp)
        age_days = max((now - created).total_seconds() / 86400, 0.0) if created else 0.0
        recency = 0.5 ** (age_days / config.RECENCY_HALF_LIFE_DAYS)
        return ExperienceItem(
            node=node,
            kind=kind,
            origem_problema_id=hit.node_id,
            similarity=hit.score,
            confidence=conf,
            recency=recency,
            rank=hit.score * conf * recency,
        )
