"""Registro de resultado: fatos medidos de uma abordagem e regra de estado da hipótese (ADR 026 §2 e §3).

Módulo puro (sem banco, rede nem LLM). Substitui o veredito do ADR 015 §9: em vez de um escore de confiança, o
sistema conta tentativas válidas e independentes que atingiram ou não o alvo do critério de sucesso e compara os
resultados medidos com referências explícitas (``delta_base`` e ``delta_pai``, como o AgentX). A regra de estado da
hipótese é uma contagem que qualquer pessoa confere:

- **validada**: o alvo é atingido em pelo menos ``min_replicas`` tentativas independentes;
- **refutada**: pelo menos ``min_refutations`` tentativas independentes ficam abaixo do alvo e nenhuma o atinge.

Duas tentativas são independentes quando diferem na semente ou nos conjuntos de dados.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Sentido = Literal["maior_melhor", "menor_melhor"]
Validation = Literal["validado", "divergente_documentado", "nao_validado"]
OutcomeKind = Literal["resultado", "falha"]
FailureCause = Literal["infraestrutura", "abordagem", "ambigua"]

QUALIFICACOES: tuple[str, ...] = ("pendente", "reparo", "restricao", "retido")
QUALIFICADORES_VALIDOS: frozenset[str] = frozenset({"teste", "cv"})
_TOL = 1e-12


@dataclass(frozen=True)
class Criterion:
    """Critério de sucesso do ``Problema``, definido pelo pesquisador antes dos experimentos.

    Attributes:
        sentido: Direção favorável da métrica (``maior_melhor`` ou ``menor_melhor``).
        delta_min: Menor efeito relevante em relação à linha de base; usado só quando não há ``alvo``.
        alvo: Valor que a métrica deve atingir; ``None`` quando o critério é só comparativo.
    """

    sentido: Sentido
    delta_min: float | None
    alvo: float | None


@dataclass(frozen=True)
class Attempt:
    """Uma tentativa (execução) lida do grafo para um registro ou uma hipótese.

    Attributes:
        attempt_id: Identificador da tentativa (o ``Resultado`` do critério, ou o ``Experimento`` na falha).
        timestamp: Instante ISO 8601 (ordenação determinística).
        node_id: ``NODE_ID`` do computador que executou.
        session_id: Sessão que produziu a tentativa.
        seed: Semente aleatória, quando registrada.
        dataset_ids: Conjuntos de dados usados.
        config_hash: Hash da configuração normalizada.
        outcome_kind: ``resultado`` quando há valor da métrica do critério, ``falha`` quando não há.
        value: Valor medido (apenas em ``resultado``).
        baseline: Linha de base registrada junto do resultado, quando existe.
        validation: Status atribuído pelo Validator ao resultado.
        contract_complete: ``params.json``, semente e ``metrics.json`` presentes.
        failure_cause: Causa da falha (apenas em ``falha``).
        failure_signature: Assinatura normalizada do erro (apenas em ``falha``).
    """

    attempt_id: str
    timestamp: str
    node_id: str
    session_id: str
    seed: int | None
    dataset_ids: tuple[str, ...]
    config_hash: str
    outcome_kind: OutcomeKind
    value: float | None = None
    baseline: float | None = None
    validation: Validation | None = None
    contract_complete: bool = False
    failure_cause: FailureCause | None = None
    failure_signature: str | None = None


@dataclass(frozen=True)
class RecordFacts:
    """Fatos de um registro de resultado (ADR 026 §2); todos recalculados, nunca escritos por agente.

    Attributes:
        melhor_valor: Melhor valor medido entre as tentativas válidas (``None`` sem tentativa válida).
        delta_base: Melhora do melhor valor sobre a linha de base (positiva = melhor); ``None`` sem referência.
        delta_pai: Melhora sobre o melhor valor do registro de origem; ``None`` sem origem.
        n_tentativas_validas: Tentativas com valor da métrica do critério.
        n_replicas_independentes: Pares distintos (semente, conjuntos de dados) entre as tentativas válidas.
        n_atingiu_alvo: Réplicas independentes cujo melhor valor atinge o alvo.
        n_abaixo_alvo: Réplicas independentes cujo melhor valor fica abaixo do alvo.
        atingiu_alvo: ``n_atingiu_alvo >= 1``.
        resultado_ids: Resultados que sustentam o registro, do melhor para o pior.
    """

    melhor_valor: float | None
    delta_base: float | None
    delta_pai: float | None
    n_tentativas_validas: int
    n_replicas_independentes: int
    n_atingiu_alvo: int
    n_abaixo_alvo: int
    atingiu_alvo: bool
    resultado_ids: tuple[str, ...]


def is_valid(attempt: Attempt) -> bool:
    """Tentativa válida: valor numérico finito da métrica do critério, verificado (qualquer status do experimento).

    Um resultado ``nao_validado`` (o Validator não verificou o número) continua sendo uma tentativa, mas não conta.
    """
    return (
        attempt.outcome_kind == "resultado"
        and attempt.value is not None
        and math.isfinite(attempt.value)
        and attempt.validation != "nao_validado"
    )


def improvement(value: float, reference: float, sentido: Sentido) -> float:
    """Melhora de ``value`` sobre ``reference`` (positiva quando ``value`` é melhor no ``sentido``)."""
    return value - reference if sentido == "maior_melhor" else reference - value


def reaches_target(value: float, baseline: float | None, criterion: Criterion) -> bool:
    """O valor atinge o alvo do critério.

    Com ``alvo``, vale o alvo absoluto. Sem ``alvo``, vale a melhora de ``delta_min`` sobre a linha de base; sem
    nenhum dos dois (ou sem linha de base), o critério não permite concluir e a resposta é ``False``.
    """
    if criterion.alvo is not None:
        return improvement(value, criterion.alvo, criterion.sentido) >= -_TOL
    if criterion.delta_min is not None and baseline is not None:
        return improvement(value, baseline, criterion.sentido) >= criterion.delta_min - _TOL
    return False


def _best(items: list[Attempt], sentido: Sentido) -> Attempt:
    pick = max if sentido == "maior_melhor" else min
    return pick(items, key=lambda a: (a.value if a.value is not None else 0.0))


def _independence_key(attempt: Attempt) -> tuple[int | None, tuple[str, ...]]:
    return attempt.seed, tuple(sorted(attempt.dataset_ids))


def compute_record(
    attempts: list[Attempt],
    criterion: Criterion,
    *,
    parent_best: float | None = None,
    reference_value: float | None = None,
) -> RecordFacts:
    """Calcula os fatos de um registro a partir das tentativas (determinístico; ordem das tentativas irrelevante).

    Args:
        attempts: Tentativas do registro (ou da hipótese); as inválidas são ignoradas.
        criterion: Critério de sucesso do ``Problema``.
        parent_best: Melhor valor do registro de origem, para ``delta_pai``.
        reference_value: Valor de referência (linha de base medida) quando o resultado não traz ``baseline``.
    """
    valid = sorted((a for a in attempts if is_valid(a)), key=lambda a: (a.timestamp, a.attempt_id))
    if not valid:
        return RecordFacts(None, None, None, 0, 0, 0, 0, False, ())
    groups: dict[tuple[int | None, tuple[str, ...]], list[Attempt]] = {}
    for attempt in valid:
        groups.setdefault(_independence_key(attempt), []).append(attempt)
    best = _best(valid, criterion.sentido)
    assert best.value is not None
    atingiu = abaixo = 0
    for members in groups.values():
        top = _best(members, criterion.sentido)
        assert top.value is not None
        if reaches_target(top.value, top.baseline if top.baseline is not None else reference_value, criterion):
            atingiu += 1
        else:
            abaixo += 1
    base = best.baseline if best.baseline is not None else reference_value
    ordered = sorted(valid, key=lambda a: improvement(a.value or 0.0, 0.0, criterion.sentido), reverse=True)
    return RecordFacts(
        melhor_valor=best.value,
        delta_base=None if base is None else round(improvement(best.value, base, criterion.sentido), 12),
        delta_pai=(
            None if parent_best is None else round(improvement(best.value, parent_best, criterion.sentido), 12)
        ),
        n_tentativas_validas=len(valid),
        n_replicas_independentes=len(groups),
        n_atingiu_alvo=atingiu,
        n_abaixo_alvo=abaixo,
        atingiu_alvo=atingiu >= 1,
        resultado_ids=tuple(a.attempt_id for a in ordered),
    )


def hypothesis_state(
    n_atingiu: int, n_abaixo: int, *, min_replicas: int, min_refutations: int
) -> Literal["validada", "refutada"] | None:
    """Estado concluído pela regra de réplicas, ou ``None`` quando a contagem ainda não permite concluir."""
    if n_atingiu >= min_replicas:
        return "validada"
    if n_atingiu == 0 and n_abaixo >= min_refutations:
        return "refutada"
    return None


def holds_works(facts: RecordFacts, *, min_replicas: int) -> bool:
    """O registro sustenta ``FUNCIONOU_PARA``: o alvo foi atingido em ``min_replicas`` réplicas independentes."""
    return facts.n_atingiu_alvo >= min_replicas


def holds_fails(facts: RecordFacts, *, min_refutations: int) -> bool:
    """O registro sustenta ``FALHOU_PARA``: ``min_refutations`` réplicas abaixo do alvo e nenhuma o atinge."""
    return facts.n_atingiu_alvo == 0 and facts.n_abaixo_alvo >= min_refutations


def classify_attempt(attempt: Attempt, criterion: Criterion, reference_value: float | None = None) -> str:
    """``atingiu`` ou ``abaixo`` para a tentativa válida e ``invalida`` para as demais."""
    if not is_valid(attempt) or attempt.value is None:
        return "invalida"
    base = attempt.baseline if attempt.baseline is not None else reference_value
    return "atingiu" if reaches_target(attempt.value, base, criterion) else "abaixo"
