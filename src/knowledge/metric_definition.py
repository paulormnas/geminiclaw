"""Métricas definidas pelo agente no modo ``auto`` (``v18.6-auto-metrics-and-stop-reasons``).

Quando o ``Problema`` não tem ``Metrica`` aprovada, o Researcher define no plano a métrica (ou o conjunto de métricas) a
alcançar (``metricas``), o Validator a valida na validação do plano e só então este módulo a grava como ``Metrica``
aprovada (``origem_definicao="agente"``, ``aprovada_por="validator"``) e a liga ao ``criterio_sucesso`` do ``Problema``.

Governança:

- tudo o que vem do plano é dado não confiável (texto limpo e limitado, números finitos, enumerações fechadas);
- a aprovação é escrita pelo **orquestrador**, depois do parecer do Validator: a barreira ``AGENT_ALLOWED_VALUES`` que
  impede qualquer agente de aprovar ``Metrica`` continua valendo para todos os agentes;
- ``Metrica`` aprovada pelo pesquisador tem precedência total (não é alterada); ``Metrica`` rejeitada por ele nunca é
  aprovada por este caminho; o ``criterio_sucesso`` do ``Problema`` só muda quando a métrica atual não está aprovada.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from src import config
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.ingestion import ACTOR_ORQUESTRADOR, ACTOR_RESEARCHER
from src.knowledge.projects import get_active_problem
from src.knowledge.vocabulary import SemanticSearch, VocabularyError, find_rejected_metric, resolve_metric
from src.logger import get_logger
from src.utils.normalization import clean_free_text, normalize_metric_name

logger = get_logger(__name__)

SENTIDOS = ("maior_melhor", "menor_melhor")
ORIGEM_AGENTE = "agente"
APROVADA_POR_VALIDATOR = "validator"

# Estados do resultado por métrica (campo ``estado`` de ``MetricOutcome``).
APLICADA = "aplicada"
PRECEDENCIA_PESQUISADOR = "precedencia_pesquisador"
JA_APROVADA_PELO_VALIDATOR = "ja_aprovada_pelo_validator"
DESCARTADA = "descartada"

# Motivos de descarte.
REJEITADA_PELO_PESQUISADOR = "rejeitada_pelo_pesquisador"
SENTIDO_DIVERGENTE = "sentido_divergente"
RESOLUCAO_FALHOU = "resolucao_falhou"

_MAX_JUSTIFICATIVA = 1000


@dataclass(frozen=True)
class MetricDecl:
    """Métrica definida no plano.

    Attributes:
        nome: Nome da métrica em texto livre (resolvido no vocabulário).
        sentido: ``maior_melhor`` ou ``menor_melhor``.
        limiar: Valor a alcançar (vira o ``alvo`` do ``Problema`` quando for a principal).
        justificativa: Por que a métrica e o limiar servem a este problema.
        delta_min: Menor melhoria relevante, ou ``None``.
    """

    nome: str
    sentido: str
    limiar: float
    justificativa: str
    delta_min: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Forma entregue ao Validator (todos os campos já saneados)."""
        return {
            "nome": self.nome, "sentido": self.sentido, "limiar": self.limiar,
            "delta_min": self.delta_min, "justificativa": self.justificativa,
        }


def _number(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value.replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def parse_metrics(raw: Any) -> tuple[list[MetricDecl], int]:
    """Valida a chave ``metricas`` do plano (dado não confiável).

    Entradas inválidas (tipo, nome, sentido, limiar ou justificativa fora do contrato, nome repetido) são descartadas e
    contadas; nunca são corrigidas em silêncio. Mais que ``METRICS_MAX_PER_PLAN`` entradas: o excedente é descartado.

    Returns:
        ``(métricas válidas na ordem do plano, quantidade descartada)``.
    """
    items = raw if isinstance(raw, list) else []
    out: list[MetricDecl] = []
    dropped = 0 if isinstance(raw, list) or raw is None else 1
    seen: set[str] = set()
    for index, item in enumerate(items):
        if index >= config.METRICS_MAX_PER_PLAN or not isinstance(item, dict):
            dropped += 1
            continue
        nome = clean_free_text(item["nome"]) if isinstance(item.get("nome"), str) else ""
        justificativa = clean_free_text(item["justificativa"]) if isinstance(item.get("justificativa"), str) else ""
        limiar = _number(item.get("limiar"))
        delta = _number(item.get("delta_min"), positive=True) if item.get("delta_min") is not None else None
        key = normalize_metric_name(nome) if nome else ""
        if (
            not key or len(nome) > config.VOCAB_TERM_MAX_CHARS or key in seen or item.get("sentido") not in SENTIDOS
            or limiar is None or not justificativa or (item.get("delta_min") is not None and delta is None)
        ):
            dropped += 1
            continue
        seen.add(key)
        out.append(
            MetricDecl(
                nome=nome, sentido=item["sentido"], limiar=limiar, justificativa=justificativa[:_MAX_JUSTIFICATIVA],
                delta_min=delta,
            )
        )
    return out, dropped


@dataclass(frozen=True)
class MetricOutcome:
    """O que aconteceu com cada métrica definida no plano."""

    nome: str
    estado: str
    motivo: str | None = None
    metric_id: str | None = None


@dataclass
class AppliedMetrics:
    """Resultado de :func:`apply_validated_metrics`."""

    outcomes: list[MetricOutcome] = field(default_factory=list)
    principal_id: str | None = None
    problema_atualizado: bool = False

    @property
    def aplicadas(self) -> list[MetricOutcome]:
        return [o for o in self.outcomes if o.estado != DESCARTADA]

    @property
    def descartadas(self) -> list[MetricOutcome]:
        return [o for o in self.outcomes if o.estado == DESCARTADA]


def _is_researcher_approved(node: Node) -> bool:
    return node.properties.get("status") == "aprovado" and node.properties.get("aprovada_por") != APROVADA_POR_VALIDATOR


def _apply_one(store: GraphStore, decl: MetricDecl, *, sessao_id: str,
               semantic_search: SemanticSearch | None) -> MetricOutcome:
    if find_rejected_metric(store, decl.nome) is not None:
        return MetricOutcome(decl.nome, DESCARTADA, REJEITADA_PELO_PESQUISADOR)
    try:
        resolution = resolve_metric(
            store, decl.nome, actor=ACTOR_RESEARCHER, sessao_id=sessao_id, sentido=decl.sentido,
            semantic_search=semantic_search,
        )
    except VocabularyError as exc:
        logger.warning("Métrica definida pelo agente não resolvida", extra={"extra": {"erro": str(exc)[:160]}})
        return MetricOutcome(decl.nome, DESCARTADA, RESOLUCAO_FALHOU)
    node = store.get_node(resolution.node_id) if resolution.node_id else None
    if node is None:
        return MetricOutcome(decl.nome, DESCARTADA, RESOLUCAO_FALHOU)
    if node.properties.get("sentido") != decl.sentido:
        return MetricOutcome(decl.nome, DESCARTADA, SENTIDO_DIVERGENTE, node.id)
    if _is_researcher_approved(node):
        return MetricOutcome(decl.nome, PRECEDENCIA_PESQUISADOR, None, node.id)
    if node.properties.get("status") == "aprovado":
        return MetricOutcome(decl.nome, JA_APROVADA_PELO_VALIDATOR, None, node.id)
    # Candidata (nova ou existente): aprovação escrita pelo orquestrador, depois do parecer do Validator.
    store.update_node(
        node.id,
        {
            "status": "aprovado",
            "origem_definicao": ORIGEM_AGENTE,
            "aprovada_por": APROVADA_POR_VALIDATOR,
            "justificativa_definicao": decl.justificativa,
        },
        actor=ACTOR_ORQUESTRADOR,
    )
    return MetricOutcome(decl.nome, APLICADA, None, node.id)


def apply_validated_metrics(
    store: GraphStore,
    projeto_id: str,
    sessao_id: str,
    decls: list[MetricDecl],
    *,
    semantic_search: SemanticSearch | None = None,
) -> AppliedMetrics:
    """Grava as métricas já validadas pelo Validator e liga a principal ao ``Problema``.

    Só chamar depois de ``ValidationResult.metrics_approved``. A primeira métrica aplicável (aprovada agora, antes pelo
    Validator ou pelo pesquisador) é a principal.

    Raises:
        GraphStoreError: Falha de escrita no grafo (propaga ao chamador).
    """
    result = AppliedMetrics()
    # A métrica atual do Problema é lida ANTES de aplicar: a aprovação de agora não pode contar como "já aprovada".
    problema = get_active_problem(store, projeto_id)
    criterio = dict((problema.properties.get("criterio_sucesso") if problema is not None else None) or {})
    current = store.get_node(str(criterio["metrica_id"])) if criterio.get("metrica_id") else None
    current_approved = current is not None and current.properties.get("status") == "aprovado"
    for decl in decls:
        result.outcomes.append(_apply_one(store, decl, sessao_id=sessao_id, semantic_search=semantic_search))
    principal = next((o for o in result.outcomes if o.estado != DESCARTADA), None)
    if principal is None or principal.metric_id is None:
        return result
    result.principal_id = principal.metric_id
    if problema is None or current_approved or criterio.get("definido_por") == "pesquisador":
        # A métrica do Problema já valia (pesquisador ou Validator): nada a mudar. O objetivo do pesquisador é
        # protegido no grafo (ADR 021 §5.2); o orquestrador não o reescreve.
        return result
    principal_decl = next(d for d, o in zip(decls, result.outcomes) if o is principal)
    same_metric = current is not None and current.id == principal.metric_id
    node = store.get_node(principal.metric_id)
    criterio["metrica"] = str(node.properties.get("nome", principal_decl.nome)) if node else principal_decl.nome
    criterio["metrica_id"] = principal.metric_id
    existing_alvo = _number(criterio.get("alvo"))
    if not (same_metric and existing_alvo is not None):  # o alvo do pesquisador na mesma métrica prevalece
        criterio["alvo"] = principal_decl.limiar
    if _number(criterio.get("delta_min"), positive=True) is None and principal_decl.delta_min is not None:
        criterio["delta_min"] = principal_decl.delta_min
    criterio["metricas_adicionais"] = [
        {"metrica_id": o.metric_id, "nome": o.nome, "limiar": d.limiar}
        for d, o in zip(decls, result.outcomes)
        if o is not principal and o.estado != DESCARTADA and o.metric_id
    ]
    criterio["definido_por"] = ORIGEM_AGENTE
    try:
        store.update_node(problema.id, {"criterio_sucesso": criterio}, actor=ACTOR_ORQUESTRADOR)
    except GraphStoreError:
        logger.error("criterio_sucesso do Problema não atualizado", extra={"extra": {"problema_id": problema.id}})
        raise
    result.problema_atualizado = True
    return result
