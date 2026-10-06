"""Geração de candidatos de similaridade para a fila de revisão (ADR 015 §6, design §5).

Depois que um nó é (re)indexado, busca-se seus vizinhos semânticos — **sem limite
de quantidade** (a varredura pagina em páginas de ``SIM_CANDIDATE_SCAN_LIMIT``) —
e os pares que passam nas regras de faixa, domínio e confiança entram na
``SimilarityQueue``. Nada é gravado no grafo: só pares confirmados pelo Curator
viram aresta ``SEMELHANTE_A``.
"""

from __future__ import annotations

from dataclasses import dataclass

from src import config
from src.embeddings.base import text_hash
from src.knowledge import domains
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.semantic_index import IGNORED_STATUSES, SemanticIndex, canonical_text
from src.knowledge.similarity_queue import (
    TIPO_DUPLICATA,
    TIPO_RELACIONADO,
    Candidate,
    SimilarityQueue,
)
from src.logger import get_logger

logger = get_logger(__name__)

# Rótulos cujos pares do mesmo rótulo geram candidatos.
SAME_LABEL_CANDIDATE_LABELS = frozenset({"Projeto", "Problema", "Abordagem", "Descoberta", "Oportunidade"})
# ``IGNORED_STATUSES`` (importado de ``semantic_index``): pares com estes ``status`` são ignorados.
# Peso de evidência quando nenhum dos nós tem veredito.
NO_EVIDENCE_WEIGHT = 0.5


@dataclass(frozen=True)
class SimilarityThresholds:
    """Limiares das faixas de similaridade (dependem do modelo de embedding).

    Attributes:
        duplicate_min: A partir daqui o par é ``duplicata``.
        related_same_domain: Início da faixa ``relacionado`` quando o par não cruza domínios.
        related_cross: Início da faixa ``relacionado`` para pares entre domínios.
        cross_project_min_confidence: ``|veredito|`` mínimo da ``Descoberta`` em
            pares ``Descoberta->Problema`` de outro projeto.
        cross_domain_boost: Multiplicador de prioridade para pares entre domínios.
    """

    duplicate_min: float
    related_same_domain: float
    related_cross: float
    cross_project_min_confidence: float
    cross_domain_boost: float

    @classmethod
    def from_config(cls) -> SimilarityThresholds:
        """Lê os limiares de ``src.config`` (variáveis ``SIM_*``)."""
        return cls(
            duplicate_min=config.SIM_DUPLICATE_MIN,
            related_same_domain=config.SIM_RELATED_MIN_SAME_DOMAIN,
            related_cross=config.SIM_RELATED_MIN_CROSS,
            cross_project_min_confidence=config.SIM_CROSS_PROJECT_MIN_CONFIDENCE,
            cross_domain_boost=config.SIM_CROSS_DOMAIN_BOOST,
        )


def _evidence(node: Node) -> float | None:
    confianca = node.properties.get("confianca")
    if confianca is None and node.properties.get("veredito") is not None:
        confianca = abs(float(node.properties["veredito"]))
    return None if confianca is None else float(confianca)


def classify_pair(
    node_a: Node,
    node_b: Node,
    score: float,
    *,
    entre_dominios: bool,
    entre_projetos: bool,
    thresholds: SimilarityThresholds,
) -> str | None:
    """Decide se o par entra na fila e com que tipo.

    Regras (design §5):

    - Mesmo rótulo em {Projeto, Problema, Abordagem, Descoberta, Oportunidade}:
      ``score >= duplicate_min`` -> ``duplicata``; ``related_same_domain <= score < duplicate_min``
      -> ``relacionado``; ``related_cross <= score < related_same_domain`` -> ``relacionado``
      **somente** se o par é entre domínios.
    - ``Descoberta`` x ``Problema`` de **outro projeto**: ``relacionado`` com
      ``score >= related_cross`` (mesma regra de domínio na faixa baixa) e
      ``|veredito|`` da descoberta >= ``cross_project_min_confidence``.
    - Nós com ``status`` ``substituida``/``rejeitado``/``rejeitada`` são ignorados.

    Returns:
        ``"duplicata"``, ``"relacionado"`` ou ``None`` (ignorado).
    """
    for node in (node_a, node_b):
        if node.properties.get("status") in IGNORED_STATUSES:
            return None

    if node_a.label == node_b.label:
        if node_a.label not in SAME_LABEL_CANDIDATE_LABELS:
            return None
        if score >= thresholds.duplicate_min:
            return TIPO_DUPLICATA
        if score >= thresholds.related_same_domain:
            return TIPO_RELACIONADO
        if score >= thresholds.related_cross and entre_dominios:
            return TIPO_RELACIONADO
        return None

    labels = {node_a.label, node_b.label}
    if labels == {"Descoberta", "Problema"}:
        if not entre_projetos:
            return None
        descoberta = node_a if node_a.label == "Descoberta" else node_b
        veredito = descoberta.properties.get("veredito")
        if veredito is None or abs(float(veredito)) < thresholds.cross_project_min_confidence:
            return None
        if score >= thresholds.related_same_domain:
            return TIPO_RELACIONADO
        if score >= thresholds.related_cross and entre_dominios:
            return TIPO_RELACIONADO
    return None


class CandidateGenerator:
    """Varre os vizinhos semânticos de um nó indexado e enfileira os pares candidatos."""

    def __init__(
        self,
        store: GraphStore,
        index: SemanticIndex,
        queue: SimilarityQueue,
        *,
        thresholds: SimilarityThresholds | None = None,
        scan_limit: int | None = None,
    ) -> None:
        """Inicializa o gerador.

        Args:
            store: Grafo (sem gancho de indexação).
            index: Índice semântico.
            queue: Fila de similaridade.
            thresholds: Limiares (padrão: ``SimilarityThresholds.from_config()``).
            scan_limit: Tamanho da página de varredura (padrão: ``SIM_CANDIDATE_SCAN_LIMIT``).
        """
        self._store = store
        self._index = index
        self._queue = queue
        self._thresholds = thresholds or SimilarityThresholds.from_config()
        self._scan_limit = scan_limit or config.SIM_CANDIDATE_SCAN_LIMIT

    def attach(self) -> None:
        """Registra a varredura como listener pós-indexação do índice."""
        self._index.add_listener(self.scan)

    def scan(self, node: Node) -> int:
        """Varre os vizinhos de ``node`` e enfileira os pares que passam nas regras.

        Args:
            node: Nó recém-indexado.

        Returns:
            Quantidade de pares **novos** inseridos na fila.
        """
        if node.label not in SAME_LABEL_CANDIDATE_LABELS or node.properties.get("status") in IGNORED_STATUSES:
            return 0
        labels = [node.label]
        if node.label == "Descoberta":
            labels.append("Problema")
        elif node.label == "Problema":
            labels.append("Descoberta")

        text = canonical_text(node.label, node.properties) or ""
        info = self._index.embedding_info
        domain_cache: dict[str, frozenset[str]] = {}

        def _domains(n: Node) -> frozenset[str]:
            if n.id not in domain_cache:
                domain_cache[n.id] = domains.node_domains(self._store, n)
            return domain_cache[n.id]

        inserted = 0
        for hit in self._index.iter_neighbors(
            node.id, labels, self._thresholds.related_cross, self._scan_limit
        ):
            other = self._store.get_node(hit.node_id)
            if other is None:
                continue
            entre_projetos = domains.between_projects(node, other)
            entre_dominios = domains.between_domains(_domains(node), _domains(other))
            tipo = classify_pair(
                node, other, hit.score,
                entre_dominios=entre_dominios, entre_projetos=entre_projetos, thresholds=self._thresholds,
            )
            if tipo is None:
                continue
            candidate = self._build(node, text_hash(text), other, hit.payload.get("text_hash", ""), hit.score,
                                    tipo, entre_dominios, entre_projetos, info.model, info.version)
            if self._queue.enqueue(candidate):
                inserted += 1
        if inserted:
            logger.info(
                "Candidatos de similaridade enfileirados",
                extra={"extra": {"node_id": node.id, "label": node.label, "inseridos": inserted}},
            )
        return inserted

    def _build(
        self, node: Node, hash_node: str, other: Node, hash_other: str, score: float, tipo: str,
        entre_dominios: bool, entre_projetos: bool, model: str, version: str,
    ) -> Candidate:
        evidences = [e for e in (_evidence(node), _evidence(other)) if e is not None]
        peso = max(evidences) if evidences else NO_EVIDENCE_WEIGHT
        prioridade = score * peso * (self._thresholds.cross_domain_boost if entre_dominios else 1.0)
        if node.id <= other.id:
            a, b, ha, hb = node, other, hash_node, hash_other
        else:
            a, b, ha, hb = other, node, hash_other, hash_node
        return Candidate(
            node_a=a.id, node_b=b.id, label_a=a.label, label_b=b.label, tipo=tipo, score=float(score),
            entre_dominios=entre_dominios, entre_projetos=entre_projetos, prioridade=prioridade,
            text_hash_a=ha, text_hash_b=hb, embedding_model=model, embedding_version=version,
        )
