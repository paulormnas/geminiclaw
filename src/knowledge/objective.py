"""Critérios de atingimento, avanço e saturação do objetivo tipado (v18.7-exploration-limits, design §5).

O módulo é **determinístico** (sem LLM): ``evaluate`` recebe as leituras do grafo por um ``ObjectiveReader`` e devolve
o ``ObjectiveState`` do ciclo. Os nomes dos tipos, desfechos e conferências são os do schema do grafo
(:mod:`src.knowledge.schema`).

- ``limiar``: resultado **validado** da métrica principal que alcança o ``alvo`` e supera a referência em
  ``delta_min``; a contagem de réplicas da hipótese não entra (ADR 021 §5.2).
- ``discriminacao``: conferências **validadas** das predições das concorrentes decidem o desfecho.
- ``cobertura``: atingido só por decisão do pesquisador; novidade de hipóteses vira aviso.
- ``fronteira``: recusado (V19).

``ObjectiveMemory`` guarda o que o critério precisa lembrar entre ciclos e é gravada no checkpoint da sessão.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from src import config
from src.knowledge import schema
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import GraphStore
from src.knowledge.hypotheses import STATUS_ABANDONADA

DESFECHO_UMA_COMPATIVEL = "uma_compativel"
DESFECHO_TODAS_CONTRARIADAS = "todas_contrariadas"
DESFECHO_VARIAS_COMPATIVEIS = "varias_compativeis"
DESFECHO_AGUARDA_FISICO = "aguarda_experimento_fisico"

SATURACAO_CONFIRMADA = "confirmada"
SATURACAO_NAO_CONFIRMADA = "nao_confirmada"
SATURACAO_NAO_AVALIAVEL = "nao_avaliavel"
SATURACAO_SO_AVISO = "so_aviso"

Saturation = Literal["confirmada", "nao_confirmada", "nao_avaliavel", "so_aviso"]

FRONTEIRA_RECUSADA = "tipo `fronteira` ainda não suportado; será especificado com a V19 (equipamentos)"
_ROLE_REFERENCE = "referencia"


class ObjectiveError(ValueError):
    """Objetivo que não pode ser avaliado (tipo recusado ou inválido)."""


@dataclass(frozen=True)
class EligibleResult:
    """``Resultado`` elegível do ``limiar`` (validado, da métrica principal, de experimento que não é referência)."""

    resultado_id: str
    experimento_id: str
    hipotese_id: str
    valor: float
    baseline: float | None = None


@dataclass(frozen=True)
class Competitor:
    """Hipótese concorrente do objetivo de discriminação; ``predicao`` vazia = sem predição declarada."""

    hipotese_id: str
    predicao: str | None = None


@dataclass(frozen=True)
class PredictionCheck:
    """Conferência de uma predição gravada num ``Experimento`` (``validado``: seu resultado foi validado)."""

    experimento_id: str
    hipotese_id: str
    conferencia: str
    validado: bool


@dataclass(frozen=True)
class DiscriminatingTask:
    """Subtarefa na fila ou no último plano que declara ``discrimina``."""

    nome: str
    discrimina: tuple[str, ...]
    fisico: bool = False


@dataclass(frozen=True)
class CycleView:
    """O que o ciclo atual traz além do grafo: hipóteses novas e subtarefas que discriminam."""

    cycle_no: int
    new_hypotheses: int = 0
    discriminating: tuple[DiscriminatingTask, ...] = ()


class ObjectiveReader(Protocol):
    """Leituras do grafo de que os critérios precisam (implementação em :class:`GraphObjectiveReader`)."""

    def sentido(self) -> str | None: ...

    def eligible_results(self) -> list[EligibleResult]: ...

    def competitors(self) -> list[Competitor]: ...

    def prediction_checks(self) -> list[PredictionCheck]: ...


@dataclass(frozen=True)
class ObjectiveMemory:
    """Estado entre ciclos (gravado em ``payload["exploracao_estado"]`` para a retomada).

    Attributes:
        best_value: Melhor valor elegível que contou como avanço (``limiar``).
        cycles_without_advance: Ciclos seguidos sem avanço.
        interventions: Intervenções do Curator já feitas por estagnação (seção 6).
        novelty: Hipóteses novas por ciclo, os mais recentes por último (``cobertura``).
        seen_experiments: Experimentos cujas conferências já foram avaliadas (``discriminacao``).
        contradicted: Concorrentes já contrariadas em ciclos anteriores.
    """

    best_value: float | None = None
    cycles_without_advance: int = 0
    interventions: int = 0
    novelty: tuple[int, ...] = ()
    seen_experiments: frozenset[str] = frozenset()
    contradicted: frozenset[str] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_value": self.best_value,
            "cycles_without_advance": self.cycles_without_advance,
            "interventions": self.interventions,
            "novelty": list(self.novelty),
            "seen_experiments": sorted(self.seen_experiments),
            "contradicted": sorted(self.contradicted),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> ObjectiveMemory:
        """Lê o checkpoint; dado ausente ou malformado volta à memória vazia (nunca levanta)."""
        if not isinstance(raw, dict):
            return cls()
        best = raw.get("best_value")
        return cls(
            best_value=float(best) if isinstance(best, (int, float)) and not isinstance(best, bool) else None,
            cycles_without_advance=_int(raw.get("cycles_without_advance")),
            interventions=_int(raw.get("interventions")),
            novelty=tuple(_int(v) for v in raw.get("novelty") or [] if isinstance(v, (int, float))),
            seen_experiments=frozenset(str(v) for v in raw.get("seen_experiments") or []),
            contradicted=frozenset(str(v) for v in raw.get("contradicted") or []),
        )


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else 0


@dataclass(frozen=True)
class ObjectiveState:
    """Resultado de ``evaluate`` para o ciclo.

    Attributes:
        tipo: ``limiar``, ``discriminacao`` ou ``cobertura``.
        atingido: O objetivo foi atingido.
        desfecho: ``uma_compativel``, ``todas_contrariadas``, ``varias_compativeis``,
            ``aguarda_experimento_fisico`` ou ``None``.
        avanco: Houve avanço rumo ao objetivo neste ciclo.
        saturacao: ``confirmada``, ``nao_confirmada``, ``nao_avaliavel`` ou ``so_aviso``.
        detalhes: Valores usados (melhor valor, EP, réplicas, concorrentes...), só números e ids.
        memory: Memória atualizada com este ciclo.
    """

    tipo: str
    atingido: bool
    desfecho: str | None
    avanco: bool
    saturacao: Saturation
    detalhes: dict[str, Any] = field(default_factory=dict)
    memory: ObjectiveMemory = field(default_factory=ObjectiveMemory)


def effective_type(criterion: dict[str, Any] | None) -> str | None:
    """Tipo efetivo: o declarado, ``limiar`` para critério antigo sem ``tipo``, ``None`` sem critério utilizável."""
    if not isinstance(criterion, dict):
        return None
    kind = criterion.get("tipo")
    if kind is not None:
        return kind if kind in schema.TIPOS_OBJETIVO else None
    return "limiar" if criterion.get("metrica") or criterion.get("metrica_id") else None


def evaluate(
    reader: ObjectiveReader, criterion: dict[str, Any], previous: ObjectiveMemory, cycle: CycleView
) -> ObjectiveState:
    """Avalia o objetivo do ``Problema`` no fim de um ciclo.

    Raises:
        ObjectiveError: Tipo ``fronteira`` ou sem tipo utilizável.
    """
    kind = effective_type(criterion)
    if kind is None:
        raise ObjectiveError("O Problema não tem um objetivo válido (tipo ausente ou inválido).")
    if kind == "fronteira":
        raise ObjectiveError(FRONTEIRA_RECUSADA)
    if kind == "limiar":
        return _evaluate_threshold(reader, criterion, previous)
    if kind == "discriminacao":
        return _evaluate_discrimination(reader, previous, cycle)
    return _evaluate_coverage(previous, cycle)


# ---------------------------------------------------------------------------
# limiar
# ---------------------------------------------------------------------------


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _improvement(sentido: str, value: float, reference: float) -> float:
    return value - reference if sentido == "maior_melhor" else reference - value


def meets_threshold(result: EligibleResult, criterion: dict[str, Any], sentido: str) -> bool:
    """Alcança o ``alvo`` (quando definido) **e** supera a referência em ``delta_min`` (quando há referência)."""
    alvo, delta = _number(criterion.get("alvo")), _number(criterion.get("delta_min"))
    if alvo is None and delta is None:
        return False
    if alvo is not None and _improvement(sentido, result.valor, alvo) < 0:
        return False
    if delta is not None and result.baseline is not None:
        return _improvement(sentido, result.valor, result.baseline) >= delta
    return alvo is not None


def _standard_error(values: list[float]) -> float | None:
    """``s / √n`` das réplicas; ``None`` com menos de duas."""
    if len(values) < 2:
        return None
    return statistics.stdev(values) / math.sqrt(len(values))


def _evaluate_threshold(
    reader: ObjectiveReader, criterion: dict[str, Any], previous: ObjectiveMemory
) -> ObjectiveState:
    sentido = str(criterion.get("sentido") or reader.sentido() or "maior_melhor")
    results = reader.eligible_results()
    reached = [r for r in results if meets_threshold(r, criterion, sentido)]
    pick = max if sentido == "maior_melhor" else min
    hit = pick(reached, key=lambda r: r.valor) if reached else None
    details: dict[str, Any] = {"elegiveis": len(results)}
    if hit is not None:
        details.update({"resultado_id": hit.resultado_id, "hipotese_id": hit.hipotese_id, "valor": hit.valor})
    if not results:
        memory = replace(previous, cycles_without_advance=previous.cycles_without_advance + 1)
        return ObjectiveState("limiar", hit is not None, None, False, SATURACAO_NAO_AVALIAVEL, details, memory)

    best = pick(results, key=lambda r: r.valor)
    replicas = [r.valor for r in results if r.hipotese_id == best.hipotese_id]
    se = _standard_error(replicas)
    details.update({"melhor_valor": best.valor, "melhor_hipotese_id": best.hipotese_id, "replicas": len(replicas)})
    if se is not None:
        details["erro_padrao"] = round(se, 6)
    if previous.best_value is None:
        advance = True
    else:
        gain = _improvement(sentido, best.valor, previous.best_value)
        advance = gain > 0 if se is None else gain > config.SATURATION_SE_MULTIPLIER * se
        if se is None and advance:
            details["avanco_sem_incerteza"] = True
    memory = replace(
        previous,
        best_value=best.valor if advance else previous.best_value,
        cycles_without_advance=0 if advance else previous.cycles_without_advance + 1,
    )
    if len(replicas) < config.SATURATION_MIN_REPLICATES:
        saturation: Saturation = SATURACAO_NAO_AVALIAVEL
    else:
        saturation = SATURACAO_NAO_CONFIRMADA if advance else SATURACAO_CONFIRMADA
    return ObjectiveState("limiar", hit is not None, None, advance, saturation, details, memory)


# ---------------------------------------------------------------------------
# discriminacao
# ---------------------------------------------------------------------------


MAX_DISCRIMINA = 20
_MAX_ID = 128


def parse_discrimina(value: Any) -> list[str]:
    """Campo ``discrimina`` da subtarefa do plano: lista de refs ou ids de concorrentes (texto curto, sem repetição)."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and len(item.strip()) <= _MAX_ID and item.strip() not in out:
            out.append(item.strip())
    return out[:MAX_DISCRIMINA]


def normalize_predictions(
    competitors: list[Competitor], discrimina: tuple[str, ...], items: Any
) -> dict[str, str]:
    """Conferências do parecer de revisão, prontas para ``Experimento.conferencia_predicoes`` (design §5.2).

    Itens de hipóteses fora de ``discrimina`` são descartados; valor inválido vira ``inconclusiva``; concorrente sem
    predição declarada recebe ``inconclusiva`` mesmo que o parecer diga outra coisa; as listadas em ``discrimina``
    que o parecer não cobriu também ficam ``inconclusiva``.
    """
    declared = {c.hipotese_id: bool((c.predicao or "").strip()) for c in competitors}
    said: dict[str, str] = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("hipotese_id"), str):
            said[item["hipotese_id"]] = str(item.get("conferencia"))
    result: dict[str, str] = {}
    for hypothesis_id in discrimina:
        if hypothesis_id not in declared:
            continue
        value = said.get(hypothesis_id)
        if not declared[hypothesis_id] or value not in schema.CONFERENCIAS_PREDICAO:
            value = "inconclusiva"
        result[hypothesis_id] = value
    return result


def _evaluate_discrimination(reader: ObjectiveReader, previous: ObjectiveMemory, cycle: CycleView) -> ObjectiveState:
    competitors = [c.hipotese_id for c in reader.competitors()]
    checks = [c for c in reader.prediction_checks() if c.validado and c.hipotese_id in competitors]
    contradicted = {c.hipotese_id for c in checks if c.conferencia == "contraria"}
    confirmed = {c.hipotese_id for c in checks if c.conferencia == "confirma"}
    compatible = sorted((confirmed - contradicted) & set(competitors))
    alive = [h for h in competitors if h not in contradicted]
    details: dict[str, Any] = {
        "concorrentes": len(competitors), "contrariadas": sorted(contradicted), "compativeis": compatible,
    }
    fresh = [c for c in checks if c.experimento_id not in previous.seen_experiments]
    fresh_confirmed = {c.hipotese_id for c in fresh if c.conferencia == "confirma"}
    fresh_contradicted = {c.hipotese_id for c in fresh if c.conferencia == "contraria"}
    advance = bool(fresh_contradicted - previous.contradicted) or bool(fresh_confirmed and fresh_contradicted)
    memory = replace(
        previous,
        seen_experiments=previous.seen_experiments | {c.experimento_id for c in checks},
        contradicted=previous.contradicted | contradicted,
        cycles_without_advance=0 if advance else previous.cycles_without_advance + 1,
    )

    if len(competitors) >= 2 and len(compatible) == 1 and len(alive) == 1:
        details["hipotese_id"] = compatible[0]
        return ObjectiveState("discriminacao", True, DESFECHO_UMA_COMPATIVEL, advance, SATURACAO_NAO_CONFIRMADA,
                              details, memory)
    if competitors and not alive:
        return ObjectiveState("discriminacao", False, DESFECHO_TODAS_CONTRARIADAS, advance, SATURACAO_NAO_CONFIRMADA,
                              details, memory)

    def covers(task: DiscriminatingTask) -> bool:
        return len(set(task.discrimina) & set(alive)) >= 2

    physical = [t for t in cycle.discriminating if t.fisico and covers(t)]
    runnable = [t for t in cycle.discriminating if not t.fisico and covers(t)]
    if runnable:
        return ObjectiveState("discriminacao", False, None, advance, SATURACAO_NAO_CONFIRMADA, details, memory)
    if physical:
        details["subtarefa"] = physical[0].nome
        return ObjectiveState("discriminacao", False, DESFECHO_AGUARDA_FISICO, advance, SATURACAO_NAO_CONFIRMADA,
                              details, memory)
    desfecho = DESFECHO_VARIAS_COMPATIVEIS if len(compatible) >= 2 else None
    return ObjectiveState("discriminacao", False, desfecho, advance, SATURACAO_CONFIRMADA, details, memory)


# ---------------------------------------------------------------------------
# cobertura
# ---------------------------------------------------------------------------


def _evaluate_coverage(previous: ObjectiveMemory, cycle: CycleView) -> ObjectiveState:
    window = config.COVERAGE_NOVELTY_WINDOW
    novelty = (*previous.novelty, max(0, cycle.new_hypotheses))[-window:]
    advance = cycle.new_hypotheses > 0
    memory = replace(
        previous, novelty=novelty, cycles_without_advance=0 if advance else previous.cycles_without_advance + 1
    )
    details: dict[str, Any] = {"hipoteses_novas": cycle.new_hypotheses}
    saturation: Saturation = SATURACAO_NAO_CONFIRMADA
    if len(novelty) >= window:
        rate = sum(novelty) / len(novelty)
        details["taxa"] = round(rate, 6)
        if rate <= config.COVERAGE_NOVELTY_MIN_RATE:
            saturation = SATURACAO_SO_AVISO
    return ObjectiveState("cobertura", False, None, advance, saturation, details, memory)


# ---------------------------------------------------------------------------
# leitor sobre o grafo
# ---------------------------------------------------------------------------


class GraphObjectiveReader:
    """``ObjectiveReader`` sobre o grafo de conhecimento do projeto (somente leitura)."""

    def __init__(self, store: GraphStore, service: Any, project_id: str, problem_id: str) -> None:
        """
        Args:
            store: Grafo de conhecimento.
            service: ``KnowledgeService`` (resolve critério, métrica e tentativas).
            project_id: Projeto da sessão.
            problem_id: ``Problema`` cujo objetivo é avaliado.
        """
        self._store = store
        self._service = service
        self._project_id = project_id
        self._problem_id = problem_id

    def _hypotheses(self) -> list[Any]:
        return self._store.find_nodes("Hipotese", {"projeto_id": self._project_id}, limit=2000)

    def _blocked(self, node: Any) -> bool:
        """Hipótese abandonada pelo pesquisador não conta; a abandonada pelo sistema ou pelo agente conta."""
        if node.properties.get("status") != STATUS_ABANDONADA:
            return False
        author = node.properties.get("abandonada_por")
        return author == "pesquisador" or author is None

    def sentido(self) -> str | None:
        problem = self._store.get_node(self._problem_id)
        if problem is None:
            return None
        try:
            criterion, _ = self._service.criterion_for(problem)
        except GraphStoreError:
            return None
        return criterion.sentido

    def eligible_results(self) -> list[EligibleResult]:
        problem = self._store.get_node(self._problem_id)
        if problem is None:
            return []
        try:
            _, metric = self._service.criterion_for(problem)
        except GraphStoreError:
            return []
        out: list[EligibleResult] = []
        for node in self._hypotheses():
            if self._blocked(node):
                continue
            for item in self._service.collect_attempts(node, metric):
                attempt = item.attempt
                if attempt.outcome_kind != "resultado" or attempt.validation != "validado" or attempt.value is None:
                    continue
                if item.resultado_id is None:
                    continue
                experiment = self._store.get_node(item.experimento_id)
                result = self._store.get_node(item.resultado_id)
                if experiment is None or result is None:
                    continue
                if experiment.properties.get("papel") == _ROLE_REFERENCE:
                    continue
                if result.properties.get("qualificador") not in (None, "", "teste"):
                    continue
                out.append(EligibleResult(
                    item.resultado_id, item.experimento_id, node.id, attempt.value, attempt.baseline
                ))
        return out

    def competitors(self) -> list[Competitor]:
        return [
            Competitor(n.id, n.properties.get("predicao"))
            for n in self._hypotheses()
            if n.properties.get("concorrente") is True
        ]

    def prediction_checks(self) -> list[PredictionCheck]:
        rivals = {c.hipotese_id for c in self.competitors()}
        checks: list[PredictionCheck] = []
        for rival in rivals:
            for edge in self._store.neighbors(rival, ["TESTA"], direction="in", depth=1).nodes:
                if edge.label != "Experimento":
                    continue
                mapping = edge.properties.get("conferencia_predicoes")
                value = mapping.get(rival) if isinstance(mapping, dict) else None
                if value not in schema.CONFERENCIAS_PREDICAO:
                    continue
                checks.append(PredictionCheck(edge.id, rival, value, self._validated(edge.id)))
        return checks

    def _validated(self, experiment_id: str) -> bool:
        """O experimento produziu ao menos um ``Resultado`` validado (a conferência só vale então)."""
        for node in self._store.neighbors(experiment_id, ["PRODUZIU"], direction="out", depth=1).nodes:
            if node.label == "Resultado" and node.properties.get("status_validacao") == "validado":
                return True
        return False
