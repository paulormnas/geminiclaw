"""Cálculo do veredito de confiança de uma hipótese a partir de suas evidências.

Módulo puro (sem acesso a banco de dados, rede ou LLM) que implementa a equação de
confiança do ADR 015 §9: cada tentativa registrada para uma hipótese vira uma
evidência com peso objetivo (`w = q · m · d · b`), acumulada num modelo Beta-Bernoulli
que separa **para onde a evidência aponta** (`suporte`) de **quanta evidência existe**
(`certeza`). O resultado é um único número entre −1 e +1 — o **veredito** — em que
positivo significa "funciona", negativo "não funciona" e valores perto de zero,
evidência insuficiente para concluir.

Este módulo não coleta evidências do grafo de conhecimento nem grava o veredito nos
nós — isso é responsabilidade do agente Curator (mudança `v17-curator-agent`), que usa
`compute_verdict` como a única fonte de verdade para o cálculo.

Referências: ADR 015 §9 (`docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md`).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from src.logger import get_logger

logger = get_logger(__name__)

Sentido = Literal["maior_melhor", "menor_melhor"]
Validation = Literal["validado", "divergente_documentado", "nao_validado"]
OutcomeKind = Literal["resultado", "falha"]
FailureCause = Literal["infraestrutura", "abordagem", "ambigua"]
Classificacao = Literal["positiva", "negativa", "ambigua", "infraestrutura", "nao_evidencia"]


@dataclass(frozen=True)
class Criterion:
    """Critério de sucesso da hipótese, definido pelo pesquisador antes dos experimentos.

    Attributes:
        sentido: Direção favorável da métrica, herdada do catálogo canônico
            (`maior_melhor` ou `menor_melhor`).
        delta_min: Menor efeito relevante (`δ`) em relação ao baseline, definido no
            `criterio_sucesso` do `Problema` antes de qualquer experimento. `None`
            quando não há baseline ou o pesquisador optou por um alvo absoluto.
        alvo: Valor absoluto que a métrica deve atingir, usado apenas quando não há
            baseline. `None` quando o critério é sempre comparativo (via `delta_min`).
    """

    sentido: Sentido
    delta_min: float | None
    alvo: float | None


@dataclass(frozen=True)
class Attempt:
    """Uma tentativa (execução) registrada para uma hipótese.

    Attributes:
        attempt_id: Identificador único da tentativa.
        timestamp: Data/hora ISO 8601 da tentativa — usada para ordenação
            determinística antes do cálculo.
        node_id: `NODE_ID` do computador que executou a tentativa.
        session_id: Identificador da sessão que produziu a tentativa.
        seed: Semente aleatória usada, quando registrada.
        dataset_ids: Datasets usados pela tentativa.
        config_hash: Hash da configuração normalizada (usado para detectar réplica
            e para contar `n_config` na penalidade de busca).
        outcome_kind: `"resultado"` quando a tentativa produziu uma métrica, ou
            `"falha"` quando não chegou a um resultado.
        value: Valor da métrica obtido (apenas para `outcome_kind == "resultado"`).
        baseline: Valor de referência do baseline, quando existe.
        validation: Status atribuído pelo Validator (apenas para `"resultado"`).
        contract_complete: `True` quando `params.json`, semente e `metrics.json`
            (contrato de reprodutibilidade, Spec G2) estão todos presentes.
        failure_cause: Causa da falha, identificada objetivamente pelo orquestrador
            (apenas para `outcome_kind == "falha"`).
        failure_signature: Assinatura normalizada do erro (ex.: tipo de exceção),
            usada para agrupar falhas de abordagem reproduzidas.
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
class VerdictParams:
    """Parâmetros calibráveis da equação de confiança (ADR 015 §9.8).

    Os valores default reproduzem os valores iniciais do ADR. Em produção, os
    consumidores (Curator, CLI) devem construir a instância via `from_config()`,
    que lê os valores efetivos de `src/config.py` — este módulo permanece puro e
    não lê variáveis de ambiente por conta própria.

    Attributes:
        q_validated_complete: `q` quando validado e contrato de reprodutibilidade
            completo.
        q_validated_incomplete: `q` quando validado, mas contrato incompleto.
        q_divergent: `q` quando `divergente_documentado`, e também `q` das
            evidências negativas de falha de abordagem reproduzida.
        d_new_node_or_dataset: `d` quando o nó ou algum dataset da tentativa ainda
            não apareceu para esta hipótese.
        d_new_session: `d` quando a sessão é nova, mas o nó e os datasets já
            apareceram.
        d_new_seed: `d` quando apenas a semente é nova, na mesma sessão.
        gamma: `γ`, fator da penalidade de busca `b`.
        lambda_ambiguous: `λ`, peso das tentativas ambíguas no fator de conclusão `f`.
        approach_failure_q: `q` atribuído a falhas de abordagem reproduzidas.
        approach_failure_min_repeats: Número mínimo de falhas de abordagem
            independentes com a mesma assinatura para contarem como evidência.
        prior: Ponto de partida neutro de `α` e `β` (`α0 = β0`).
        thresholds: Limiares `(fraco, moderado, forte)` que definem as faixas de
            leitura do veredito, em ordem crescente.
    """

    q_validated_complete: float = 1.0
    q_validated_incomplete: float = 0.7
    q_divergent: float = 0.3
    d_new_node_or_dataset: float = 1.0
    d_new_session: float = 0.5
    d_new_seed: float = 0.2
    gamma: float = 0.5
    lambda_ambiguous: float = 0.5
    approach_failure_q: float = 0.3
    approach_failure_min_repeats: int = 2
    prior: float = 1.0
    thresholds: tuple[float, float, float] = (0.1, 0.3, 0.5)

    @classmethod
    def from_config(cls) -> "VerdictParams":
        """Constrói os parâmetros a partir das variáveis lidas em `src/config.py`.

        O import é feito dentro do método (e não no topo do módulo) para que
        `src/knowledge/verdict.py` continue importável e testável sem exigir as
        variáveis de ambiente obrigatórias de `src/config.py` (ex.: `GEMINI_API_KEY`)
        — a dependência de configuração é opcional e só existe para quem a pedir.

        Returns:
            Uma instância de `VerdictParams` com os valores calibráveis efetivos do
            projeto.
        """
        from src import config as app_config

        return cls(
            q_validated_complete=app_config.VERDICT_Q_VALIDATED_COMPLETE,
            q_validated_incomplete=app_config.VERDICT_Q_VALIDATED_INCOMPLETE,
            q_divergent=app_config.VERDICT_Q_DIVERGENT,
            d_new_node_or_dataset=app_config.VERDICT_D_NEW_NODE_OR_DATASET,
            d_new_session=app_config.VERDICT_D_NEW_SESSION,
            d_new_seed=app_config.VERDICT_D_NEW_SEED,
            gamma=app_config.VERDICT_GAMMA,
            lambda_ambiguous=app_config.VERDICT_LAMBDA_AMBIGUOUS,
            approach_failure_q=app_config.VERDICT_APPROACH_FAILURE_Q,
            approach_failure_min_repeats=app_config.VERDICT_APPROACH_FAILURE_MIN_REPEATS,
            prior=app_config.VERDICT_PRIOR,
            thresholds=app_config.VERDICT_THRESHOLDS,
        )


@dataclass(frozen=True)
class EvidenceBreakdown:
    """Detalhamento auditável de uma tentativa dentro do veredito.

    Attributes:
        attempt_id: Identificador da tentativa a que este detalhamento se refere.
        classificacao: `"positiva"`, `"negativa"`, `"ambigua"`, `"infraestrutura"`
            ou `"nao_evidencia"`.
        q: Qualidade da validação (0 quando a tentativa não é evidência).
        m: Magnitude do efeito (0 quando a tentativa não é evidência).
        d: Independência (0 quando a tentativa não é evidência).
        b: Penalidade de busca (0 quando a tentativa não é evidência; 1,0 para
            evidências negativas, que não sofrem essa penalidade).
        w: Peso final `q · m · d · b` (0 quando a tentativa não é evidência).
    """

    attempt_id: str
    classificacao: Classificacao
    q: float
    m: float
    d: float
    b: float
    w: float


@dataclass(frozen=True)
class VerdictResult:
    """Resultado do cálculo do veredito para uma hipótese.

    Attributes:
        alpha: Massa de evidência positiva acumulada (`α`), incluindo o prior.
        beta: Massa de evidência negativa acumulada (`β`), incluindo o prior.
        suporte: Direção da evidência (`α / (α + β)`); 0,5 é equilíbrio.
        certeza: Quantidade de evidência, normalizada em `[0, 1)`.
        f: Fator de conclusão — penaliza tentativas ambíguas.
        veredito: Veredito final em `[−1, +1]`.
        confianca: `|veredito|`.
        leitura: Rótulo textual da faixa em que o veredito cai.
        tipo_descoberta: `"funciona"`, `"nao_funciona"` ou `None` (faixa
            insuficiente).
        n_tentativas: Total de tentativas consideradas (todas, inclusive as que não
            afetam o veredito).
        n_evidencias: Tentativas que viraram evidência (positiva ou negativa).
        n_ambiguas: Tentativas classificadas como ambíguas.
        n_infraestrutura: Tentativas que falharam por causa de infraestrutura.
        detalhes: Detalhamento por tentativa, na ordem cronológica usada no
            cálculo.
    """

    alpha: float
    beta: float
    suporte: float
    certeza: float
    f: float
    veredito: float
    confianca: float
    leitura: str
    tipo_descoberta: str | None
    n_tentativas: int
    n_evidencias: int
    n_ambiguas: int
    n_infraestrutura: int
    detalhes: tuple[EvidenceBreakdown, ...]


@dataclass
class _WorkingRecord:
    """Estado mutável de uma tentativa durante o cálculo (uso interno)."""

    attempt: Attempt
    classificacao: Classificacao
    o: int | None
    q: float
    m: float
    d: float = 0.0
    b: float = 0.0
    w: float = 0.0


def _validate_attempt(attempt: Attempt) -> None:
    """Garante que uma tentativa tem os campos mínimos para o seu tipo de desfecho.

    Args:
        attempt: A tentativa a validar.

    Raises:
        ValueError: Quando campos obrigatórios para o `outcome_kind` estão ausentes.
    """
    if attempt.outcome_kind == "resultado":
        if attempt.value is None:
            raise ValueError(f"Tentativa '{attempt.attempt_id}': outcome_kind='resultado' exige 'value'.")
        if attempt.validation is None:
            raise ValueError(f"Tentativa '{attempt.attempt_id}': outcome_kind='resultado' exige 'validation'.")
    elif attempt.outcome_kind == "falha":
        if attempt.failure_cause is None:
            raise ValueError(f"Tentativa '{attempt.attempt_id}': outcome_kind='falha' exige 'failure_cause'.")
        if attempt.failure_cause == "abordagem" and not attempt.failure_signature:
            raise ValueError(f"Tentativa '{attempt.attempt_id}': falha de abordagem exige 'failure_signature'.")
    else:
        raise ValueError(f"Tentativa '{attempt.attempt_id}': outcome_kind inválido: {attempt.outcome_kind!r}.")


def _quality(attempt: Attempt, params: VerdictParams) -> float:
    """Calcula `q` (qualidade da validação) para um resultado (ADR 015 §9.4).

    Args:
        attempt: Tentativa com `outcome_kind == "resultado"` e `validation` diferente
            de `"nao_validado"`.
        params: Parâmetros calibráveis.

    Returns:
        O valor de `q` correspondente ao status de validação e à completude do
        contrato de reprodutibilidade.
    """
    if attempt.validation == "validado":
        return params.q_validated_complete if attempt.contract_complete else params.q_validated_incomplete
    # "divergente_documentado" — nao_validado já foi tratado antes de chamar esta função.
    return params.q_divergent


def _direction_and_magnitude(attempt: Attempt, criterion: Criterion) -> tuple[int, float] | None:
    """Calcula a direção (`o`) e a magnitude (`m`) de um resultado (ADR 015 §9.2/§9.4).

    Args:
        attempt: Tentativa com `outcome_kind == "resultado"`.
        criterion: Critério de sucesso da hipótese.

    Returns:
        Uma tupla `(o, m)`, ou `None` quando não há baseline nem alvo — caso em que
        a tentativa é ambígua.
    """
    if criterion.delta_min is not None and attempt.baseline is not None:
        delta = (
            attempt.value - attempt.baseline
            if criterion.sentido == "maior_melhor"
            else attempt.baseline - attempt.value
        )
        if delta >= criterion.delta_min:
            m = min(1.0, delta / (2 * criterion.delta_min))
            return 1, m
        m = min(1.0, (criterion.delta_min - delta) / criterion.delta_min)
        return -1, m

    if criterion.alvo is not None:
        atingiu = (
            attempt.value >= criterion.alvo if criterion.sentido == "maior_melhor" else attempt.value <= criterion.alvo
        )
        return (1, 0.5) if atingiu else (-1, 0.5)

    return None


def _reproduced_failure_signatures(attempts: list[Attempt], params: VerdictParams) -> set[str]:
    """Identifica assinaturas de falha de abordagem reproduzidas de forma independente.

    Uma assinatura é considerada reproduzida quando existem pelo menos
    `params.approach_failure_min_repeats` tentativas com essa assinatura vindas de
    combinações distintas de nó, sessão e semente (ADR 015 §9.3).

    Args:
        attempts: Todas as tentativas da hipótese.
        params: Parâmetros calibráveis.

    Returns:
        O conjunto de `failure_signature` reproduzidas de forma independente.
    """
    by_signature: dict[str, list[Attempt]] = defaultdict(list)
    for attempt in attempts:
        if attempt.outcome_kind == "falha" and attempt.failure_cause == "abordagem":
            by_signature[attempt.failure_signature].append(attempt)

    reproduced: set[str] = set()
    for signature, group in by_signature.items():
        combos = {(a.node_id, a.session_id, a.seed) for a in group}
        if len(combos) >= params.approach_failure_min_repeats:
            reproduced.add(signature)
    return reproduced


def _classify(
    attempt: Attempt, criterion: Criterion, params: VerdictParams, reproduced_signatures: set[str]
) -> tuple[Classificacao, int | None, float, float]:
    """Classifica uma tentativa e calcula `q` e `m` quando ela vira evidência.

    Args:
        attempt: A tentativa a classificar.
        criterion: Critério de sucesso da hipótese.
        params: Parâmetros calibráveis.
        reproduced_signatures: Assinaturas de falha de abordagem já identificadas
            como reproduzidas de forma independente (ver `_reproduced_failure_signatures`).

    Returns:
        Uma tupla `(classificacao, o, q, m)`. `o`, `q` e `m` são `0`/`None` para
        classificações que não entram no cálculo (`ambigua`, `infraestrutura`,
        `nao_evidencia`).
    """
    if attempt.outcome_kind == "resultado":
        if attempt.validation == "nao_validado":
            return "nao_evidencia", None, 0.0, 0.0
        direction = _direction_and_magnitude(attempt, criterion)
        if direction is None:
            return "ambigua", None, 0.0, 0.0
        o, m = direction
        q = _quality(attempt, params)
        return ("positiva" if o == 1 else "negativa"), o, q, m

    # outcome_kind == "falha"
    if attempt.failure_cause == "infraestrutura":
        return "infraestrutura", None, 0.0, 0.0
    if attempt.failure_cause == "abordagem":
        if attempt.failure_signature in reproduced_signatures:
            return "negativa", -1, params.approach_failure_q, 1.0
        return "ambigua", None, 0.0, 0.0
    # "ambigua"
    return "ambigua", None, 0.0, 0.0


def _independence_factor(
    attempt: Attempt,
    seen_nodes: set[str],
    seen_datasets: set[str],
    seen_sessions: set[str],
    params: VerdictParams,
) -> float:
    """Calcula `d` (independência) e reflete o estado de "já visto" (ADR 015 §9.4).

    Percorre, nesta ordem: nó ou dataset novo > sessão nova > semente nova. Deve ser
    chamada em ordem cronológica, só para tentativas que se tornam evidência —
    tentativas ambíguas, de infraestrutura ou não-evidência não contam como
    exploração de um nó/sessão/dataset novo para esta hipótese.

    Args:
        attempt: A tentativa (já classificada como evidência).
        seen_nodes: Nós já vistos para esta hipótese (mutado nesta chamada).
        seen_datasets: Datasets já vistos para esta hipótese (mutado nesta chamada).
        seen_sessions: Sessões já vistas para esta hipótese (mutado nesta chamada).
        params: Parâmetros calibráveis.

    Returns:
        O valor de `d` para esta tentativa.
    """
    is_new_node_or_dataset = attempt.node_id not in seen_nodes or any(
        dataset_id not in seen_datasets for dataset_id in attempt.dataset_ids
    )
    if is_new_node_or_dataset:
        d = params.d_new_node_or_dataset
    elif attempt.session_id not in seen_sessions:
        d = params.d_new_session
    else:
        d = params.d_new_seed

    seen_nodes.add(attempt.node_id)
    seen_datasets.update(attempt.dataset_ids)
    seen_sessions.add(attempt.session_id)
    return d


def _search_penalty(
    record: _WorkingRecord, all_records: list[_WorkingRecord], n_config: int, params: VerdictParams
) -> float:
    """Calcula `b` (penalidade de busca) para uma evidência positiva (ADR 015 §9.4).

    Args:
        record: O registro de trabalho da evidência positiva.
        all_records: Todos os registros de trabalho já classificados (usado para
            checar réplica em outra sessão ou nó, independentemente da ordem
            cronológica).
        n_config: Número de configurações distintas tentadas para a hipótese
            (`config_hash` distintos entre todas as tentativas).
        params: Parâmetros calibráveis.

    Returns:
        `1,0` se a configuração já foi replicada por outra evidência positiva de
        outra sessão ou nó; senão, `1 / (1 + γ · ln(n_config))`.
    """
    replicated = any(
        other.classificacao == "positiva"
        and other.attempt.attempt_id != record.attempt.attempt_id
        and other.attempt.config_hash == record.attempt.config_hash
        and (other.attempt.node_id != record.attempt.node_id or other.attempt.session_id != record.attempt.session_id)
        for other in all_records
    )
    if replicated:
        return 1.0
    return 1.0 / (1.0 + params.gamma * math.log(n_config))


def _read_verdict(veredito: float, thresholds: tuple[float, float, float]) -> tuple[str, str | None]:
    """Traduz o veredito numérico em leitura textual e tipo de descoberta sugerido.

    Args:
        veredito: O veredito calculado, em `[−1, +1]`.
        thresholds: Limiares `(fraco, moderado, forte)`, em ordem crescente.

    Returns:
        Uma tupla `(leitura, tipo_descoberta)`.
    """
    fraco, moderado, forte = thresholds
    if veredito >= forte:
        return "funciona_forte", "funciona"
    if veredito >= moderado:
        return "funciona_moderada", "funciona"
    if veredito >= fraco:
        return "funciona_fraca", "funciona"
    if veredito <= -forte:
        return "nao_funciona_forte", "nao_funciona"
    if veredito <= -moderado:
        return "nao_funciona_moderada", "nao_funciona"
    if veredito <= -fraco:
        return "nao_funciona_fraca", "nao_funciona"
    return "insuficiente", None


def read_verdict(veredito: float, thresholds: tuple[float, float, float]) -> tuple[str, str | None]:
    """Versão pública de ``_read_verdict``: ``(leitura, tipo_descoberta)`` de um veredito numérico (sem LLM)."""
    return _read_verdict(veredito, thresholds)


def compute_verdict(
    attempts: list[Attempt], criterion: Criterion, params: VerdictParams | None = None
) -> VerdictResult:
    """Calcula o veredito de confiança de uma hipótese a partir de suas tentativas.

    Implementa a equação de confiança do ADR 015 §9: tentativas ordenadas por
    `timestamp` viram evidências ponderadas (`w = q · m · d · b`), acumuladas num
    modelo Beta-Bernoulli (`α`/`β`) que separa a direção da evidência (`suporte`) da
    quantidade de evidência (`certeza`). O resultado é o veredito em `[−1, +1]`.

    Módulo puro: não acessa banco de dados, rede ou LLM. Determinístico — o
    resultado não depende da ordem de entrada de `attempts` (internamente
    reordenados por `timestamp`).

    Args:
        attempts: Tentativas registradas para a hipótese. Pode ser vazia (nesse
            caso o veredito é 0 e a leitura é `"insuficiente"`).
        criterion: Critério de sucesso da hipótese (sentido da métrica, `delta_min`
            e/ou `alvo`).
        params: Parâmetros calibráveis. Quando `None`, usa os valores default de
            `VerdictParams` (que reproduzem o ADR 015 §9.8) — para os valores
            efetivos de `src/config.py`, passe `VerdictParams.from_config()`.

    Returns:
        O `VerdictResult` com o veredito, seus componentes e o detalhamento
        auditável por tentativa.

    Raises:
        ValueError: Quando alguma tentativa tem `outcome_kind` inválido ou está
            faltando um campo obrigatório para o seu tipo de desfecho.
    """
    params = params or VerdictParams()
    for attempt in attempts:
        _validate_attempt(attempt)

    sorted_attempts = sorted(attempts, key=lambda a: a.timestamp)
    n_config = len({a.config_hash for a in sorted_attempts})
    reproduced_signatures = _reproduced_failure_signatures(sorted_attempts, params)

    seen_nodes: set[str] = set()
    seen_datasets: set[str] = set()
    seen_sessions: set[str] = set()

    records: list[_WorkingRecord] = []
    for attempt in sorted_attempts:
        classificacao, o, q, m = _classify(attempt, criterion, params, reproduced_signatures)
        record = _WorkingRecord(attempt=attempt, classificacao=classificacao, o=o, q=q, m=m)
        if classificacao in ("positiva", "negativa"):
            record.d = _independence_factor(attempt, seen_nodes, seen_datasets, seen_sessions, params)
        records.append(record)

    for record in records:
        if record.classificacao == "positiva":
            record.b = _search_penalty(record, records, n_config, params)
        elif record.classificacao == "negativa":
            record.b = 1.0
        record.w = record.q * record.m * record.d * record.b

    alpha = params.prior + sum(r.w for r in records if r.classificacao == "positiva")
    beta = params.prior + sum(r.w for r in records if r.classificacao == "negativa")

    n_tentativas = len(sorted_attempts)
    n_infraestrutura = sum(1 for r in records if r.classificacao == "infraestrutura")
    n_evidencias = sum(1 for r in records if r.classificacao in ("positiva", "negativa"))
    n_ambiguas = sum(1 for r in records if r.classificacao == "ambigua")

    n_validas = n_tentativas - n_infraestrutura
    fator_conclusao = 1.0 if n_validas == 0 else 1.0 - params.lambda_ambiguous * n_ambiguas / n_validas

    suporte = alpha / (alpha + beta)
    certeza = (alpha + beta - 2 * params.prior) / (alpha + beta)
    veredito = fator_conclusao * certeza * (2 * suporte - 1)
    confianca = abs(veredito)

    leitura, tipo_descoberta = _read_verdict(veredito, params.thresholds)

    detalhes = tuple(
        EvidenceBreakdown(
            attempt_id=r.attempt.attempt_id,
            classificacao=r.classificacao,
            q=r.q,
            m=r.m,
            d=r.d,
            b=r.b,
            w=r.w,
        )
        for r in records
    )

    result = VerdictResult(
        alpha=alpha,
        beta=beta,
        suporte=suporte,
        certeza=certeza,
        f=fator_conclusao,
        veredito=veredito,
        confianca=confianca,
        leitura=leitura,
        tipo_descoberta=tipo_descoberta,
        n_tentativas=n_tentativas,
        n_evidencias=n_evidencias,
        n_ambiguas=n_ambiguas,
        n_infraestrutura=n_infraestrutura,
        detalhes=detalhes,
    )

    logger.debug(
        "verdict_computed",
        extra={
            "event": "verdict_computed",
            "n_tentativas": n_tentativas,
            "n_evidencias": n_evidencias,
            "n_ambiguas": n_ambiguas,
            "n_infraestrutura": n_infraestrutura,
            "veredito": veredito,
            "leitura": leitura,
        },
    )
    return result
