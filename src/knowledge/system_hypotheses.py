"""Hipótese do sistema para um teste sem hipótese aceita (v18.7-hypothesis-linking, design §4; ADR 021 §3.3-§3.5).

Quando uma subtarefa ``teste`` não traz hipótese aceita, o orquestrador deriva uma ``Hipotese`` de
``origem = "sistema"``: "a abordagem A melhora a métrica M do Problema P em relação à referência R". A chave estruturada
``(problema, abordagem canônica, métrica)`` evita duplicata: o mesmo par vira um novo teste da mesma hipótese
(variação, réplica). A referência R é fixada na criação e não muda depois.

Segurança: o texto do plano (``hypothesis``, nomes de subtarefa e de abordagem) é dado não confiável, saneado e
limitado antes de virar enunciado; nenhum ``id`` do plano é usado sem conferência no grafo; hipótese rejeitada ou
abandonada pelo pesquisador nunca volta por chave; a trilha de auditoria nunca prova uma aprovação.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src import config
from src.knowledge.exploration_reads import structured_key
from src.knowledge.graph_store import Node
from src.knowledge.hypotheses import (
    STATUS_ABANDONADA,
    STATUS_PROPOSTA,
    HypothesisBook,
)
from src.knowledge.ingestion import ACTOR_ORQUESTRADOR
from src.knowledge.schema import ORIGEM_SISTEMA
from src.logger import get_logger
from src.utils.normalization import clean_free_text, normalize_domain_term, normalize_metric_name

logger = get_logger(__name__)

MOTIVO_SEM_HYPOTHESIS_REF = "sem_hypothesis_ref"
MOTIVO_REF_ID_INEXISTENTE = "ref_id_inexistente"
MOTIVO_REF_SEM_ENUNCIADO = "ref_sem_enunciado"
MOTIVO_PAPEL_TESTE_DECLARADO = "papel_teste_declarado"

FONTE_TEXTO_LIVRE = "texto_livre"
FONTE_MODELO = "modelo"

BLOCKED_EQUIVALENT = "hipotese_equivalente_a_hipotese_abandonada"
_MAX_SCAN = 1000
_MIN_METRIC_NAME_CHARS = 3
_UNDECLARED_APPROACH = "abordagem não declarada no plano"


@dataclass(frozen=True)
class MetricRef:
    """Métrica principal M do Problema: ``id``, ``nome`` e ``sinonimos`` da ``Metrica`` aprovada."""

    id: str
    nome: str
    sinonimos: tuple[str, ...] = ()
    sentido: str = "maior_melhor"


@dataclass(frozen=True)
class SystemHypothesisOutcome:
    """Resultado de ``derive``: a hipótese a usar (ou o motivo de bloqueio) e o que aconteceu com ela."""

    hypothesis_id: str | None
    motivo: str
    created: bool = False
    reused: bool = False
    reopened: bool = False
    blocked: str | None = None
    enunciado_fonte: str = FONTE_MODELO
    abordagem_declarada: bool = True


def metric_ref(metric: Node) -> MetricRef:
    """``MetricRef`` de um nó ``Metrica``."""
    sinonimos = tuple(str(s) for s in (metric.properties.get("sinonimos") or []) if isinstance(s, str))
    return MetricRef(
        id=metric.id,
        nome=str(metric.properties.get("nome", "")),
        sinonimos=sinonimos,
        sentido=str(metric.properties.get("sentido") or "maior_melhor"),
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _cites_metric(text: str, metric: MetricRef) -> bool:
    plain = normalize_metric_name(text)
    for name in (metric.nome, *metric.sinonimos):
        key = normalize_metric_name(name)
        if len(key) >= _MIN_METRIC_NAME_CHARS and key in plain:
            return True
    return False


def free_text_statement(text: str, metric: MetricRef) -> str | None:
    """Texto livre ``hypothesis`` como enunciado, ou ``None``: precisa ser afirmativo e citar M (design §9.3).

    "Afirmativo": a primeira palavra normalizada não está em ``HYPOTHESIS_TEXT_NEGATION_PREFIXES``.
    """
    cleaned = clean_free_text(text or "")[: config.HYPOTHESIS_TEXT_MAX_CHARS].strip()
    if not cleaned:
        return None
    first = normalize_domain_term(cleaned.split(" ", 1)[0])
    if first in config.HYPOTHESIS_TEXT_NEGATION_PREFIXES or not _cites_metric(cleaned, metric):
        return None
    return cleaned


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SystemHypotheses:
    """Deriva, reutiliza e reabre hipóteses do sistema sobre um ``HypothesisBook``."""

    def __init__(self, book: HypothesisBook) -> None:
        self._book = book
        self._store = book.store
        self._ctx = book.ctx

    # ------------------------------------------------------------------ derivação

    def derive(
        self,
        *,
        task_name: str,
        approach: dict[str, str] | None,
        text: str,
        metric: MetricRef,
        motivo: str,
    ) -> SystemHypothesisOutcome:
        """Hipótese do sistema do teste: a existente com a mesma chave, reaberta se preciso, ou uma nova.

        Args:
            task_name: Subtarefa de origem (nome do plano; dado não confiável, limitado).
            approach: ``approach`` declarado na subtarefa, ou ``None``.
            text: Campo livre ``hypothesis`` da subtarefa (pode virar o enunciado).
            metric: Métrica M do Problema.
            motivo: Por que a hipótese foi derivada (``sem_hypothesis_ref`` etc.).

        Raises:
            HypothesisError / GraphStoreError: O grafo não aceitou a escrita (propaga ao chamador).
        """
        problem = self._book.problem()
        declared = bool(approach and approach.get("nome"))
        chosen = approach if declared and approach is not None else {
            "nome": clean_free_text(task_name)[:200] or "subtarefa", "tipo": "outro", "descricao": _UNDECLARED_APPROACH,
        }
        approach_id = self._book.writer.abordagem(chosen, task_name)
        if approach_id is None:
            logger.warning("Abordagem da hipótese do sistema não resolvida; a subtarefa segue sem hipótese")
            return SystemHypothesisOutcome(None, motivo, abordagem_declarada=declared)
        key = structured_key(problem.id, approach_id, metric.id)
        existing = self._by_key(key)
        if existing is None:
            return self._create(task_name, problem, approach_id, metric, motivo, text, declared, key)
        if existing.properties.get("status") != STATUS_ABANDONADA:
            return SystemHypothesisOutcome(existing.id, motivo, reused=True, abordagem_declarada=declared)
        author = self._book.abandoned_author(existing)
        if author == "pesquisador":
            return SystemHypothesisOutcome(
                existing.id, motivo, blocked=BLOCKED_EQUIVALENT, abordagem_declarada=declared
            )
        self._book.reopen(existing, author or "agente", task_name)
        return SystemHypothesisOutcome(existing.id, motivo, reused=True, reopened=True, abordagem_declarada=declared)

    def _by_key(self, key: str) -> Node | None:
        """Hipótese do projeto com a chave; prefere a não abandonada."""
        found = self._store.find_nodes(
            "Hipotese", {"projeto_id": self._ctx.project_id, "chave_estruturada": key}, limit=_MAX_SCAN
        )
        live = [n for n in found if n.properties.get("status") != STATUS_ABANDONADA]
        pool = live or found
        return pool[0] if pool else None

    # ------------------------------------------------------------------ criação

    def _create(
        self,
        task_name: str,
        problem: Node,
        approach_id: str,
        metric: MetricRef,
        motivo: str,
        text: str,
        declared: bool,
        key: str,
    ) -> SystemHypothesisOutcome:
        reference = self._fix_reference(problem, metric)
        approach_node = self._store.get_node(approach_id)
        approach_name = clean_free_text(str(approach_node.properties.get("nome", "")) if approach_node else "")
        statement = free_text_statement(text, metric)
        source = FONTE_TEXTO_LIVRE if statement else FONTE_MODELO
        if statement is None:
            title = clean_free_text(str(problem.properties.get("titulo", "")))[:200]
            shown = f"{reference['valor']:g} ({reference['origem_referencia']})" if reference["valor"] is not None \
                else "não disponível"
            statement = (
                f'A abordagem "{approach_name[:200]}" melhora a métrica "{clean_free_text(metric.nome)[:120]}" do '
                f'Problema "{title}" em relação à referência {shown}.'
            )[: config.HYPOTHESIS_TEXT_MAX_CHARS]
        label = clean_free_text(task_name)[:128]
        hypothesis_id = self._store.create_node(
            "Hipotese",
            {
                "projeto_id": self._ctx.project_id,
                "sessao_id": self._ctx.session_id,
                "enunciado": statement,
                "justificativa": f"Derivada pelo sistema da subtarefa {label} ({motivo}), sem hipótese no plano.",
                "status": STATUS_PROPOSTA,
                "origem": ORIGEM_SISTEMA,
                "chave_estruturada": key,
                "referencia_fixada": reference,
            },
            actor=ACTOR_ORQUESTRADOR,
        )
        self._book.writer._edge(hypothesis_id, "SOBRE", problem.id, fato=False)  # noqa: SLF001
        self._book.writer._edge(hypothesis_id, "PROPOE", approach_id, fato=False)  # noqa: SLF001
        note: dict[str, Any] = {
            "criacao": "derivada_pelo_sistema", "subtarefa": label, "motivo": motivo, "enunciado_fonte": source,
        }
        best = self._best_so_far(metric)
        if best is not None:
            note["melhor_ate_entao"] = best
        self._store.record_audit_note(hypothesis_id, ACTOR_ORQUESTRADOR, note)
        return SystemHypothesisOutcome(
            hypothesis_id, motivo, created=True, enunciado_fonte=source, abordagem_declarada=declared
        )

    def _results_of(self, metric: MetricRef) -> list[Node]:
        """``Resultado`` validados do projeto que medem M."""
        sub = self._store.neighbors(metric.id, ["MEDE"], direction="in", depth=1)
        return [
            n for n in sub.nodes
            if n.label == "Resultado"
            and n.properties.get("projeto_id") == self._ctx.project_id
            and n.properties.get("status_validacao") == "validado"
            and _is_number(n.properties.get("valor"))
        ]

    def _fix_reference(self, problem: Node, metric: MetricRef) -> dict[str, Any]:
        """Referência R fixada na criação: medida, baseline numérico do critério ou indisponível."""
        referenced = {
            n.id for n in self._store.neighbors(problem.id, ["REFERENCIA_DE"], direction="in", depth=1).nodes
        }
        candidates = [n for n in self._results_of(metric) if n.id in referenced]
        if candidates:
            latest = max(candidates, key=lambda n: str(n.properties.get("criado_em", "")))
            return {
                "valor": float(latest.properties["valor"]), "origem_referencia": "referencia_medida",
                "metrica_id": metric.id, "fixada_em": _now(), "resultado_id": latest.id,
            }
        criterio = problem.properties.get("criterio_sucesso")
        baseline = criterio.get("baseline") if isinstance(criterio, dict) else None
        if _is_number(baseline):
            return {
                "valor": float(baseline), "origem_referencia": "criterio_problema",
                "metrica_id": metric.id, "fixada_em": _now(),
            }
        return {"valor": None, "origem_referencia": "indisponivel", "metrica_id": metric.id, "fixada_em": _now()}

    def _best_so_far(self, metric: MetricRef) -> float | None:
        values = [float(n.properties["valor"]) for n in self._results_of(metric)]
        if not values:
            return None
        return min(values) if metric.sentido == "menor_melhor" else max(values)
