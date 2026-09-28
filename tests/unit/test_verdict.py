"""Testes unitários para src/knowledge/verdict.py (ADR 015 §9).

Cobre os testes-ouro do ADR (exemplo completo, cenário pré-réplica e a tabela de
referência do §9.7) e os testes de regra do tasks.md da mudança
`v17-evidence-verdict`.
"""

from __future__ import annotations

import random

import pytest

from src.knowledge.verdict import Attempt, Criterion, VerdictParams, compute_verdict

pytestmark = pytest.mark.unit


def _attempt(
    attempt_id: str,
    timestamp: str,
    *,
    node_id: str = "node-a",
    session_id: str = "session-1",
    seed: int | None = 1,
    dataset_ids: tuple[str, ...] = ("dataset-1",),
    config_hash: str = "cfg-1",
    outcome_kind: str = "resultado",
    value: float | None = None,
    baseline: float | None = None,
    validation: str | None = None,
    contract_complete: bool = False,
    failure_cause: str | None = None,
    failure_signature: str | None = None,
) -> Attempt:
    """Fábrica terse de `Attempt` para os testes deste módulo."""
    return Attempt(
        attempt_id=attempt_id,
        timestamp=timestamp,
        node_id=node_id,
        session_id=session_id,
        seed=seed,
        dataset_ids=dataset_ids,
        config_hash=config_hash,
        outcome_kind=outcome_kind,
        value=value,
        baseline=baseline,
        validation=validation,
        contract_complete=contract_complete,
        failure_cause=failure_cause,
        failure_signature=failure_signature,
    )


R2_CRITERION = Criterion(sentido="maior_melhor", delta_min=0.05, alvo=None)


def _adr_e1_to_e6() -> list[Attempt]:
    """As seis evidências do exemplo completo do ADR 015 §9.6."""
    return [
        _attempt(
            "E1",
            "2026-01-01T00:00:00",
            node_id="A",
            session_id="s1",
            seed=1,
            dataset_ids=("ds1",),
            config_hash="cfgX",
            value=0.80,
            baseline=0.70,
            validation="validado",
            contract_complete=True,
        ),
        _attempt(
            "E2",
            "2026-01-01T01:00:00",
            node_id="A",
            session_id="s1",
            seed=2,
            dataset_ids=("ds1",),
            config_hash="cfgX",
            value=0.78,
            baseline=0.70,
            validation="validado",
            contract_complete=True,
        ),
        _attempt(
            "E3",
            "2026-01-01T02:00:00",
            node_id="A",
            session_id="s2",
            seed=None,
            dataset_ids=("ds1",),
            config_hash="cfgX",
            value=0.79,
            baseline=0.70,
            validation="validado",
            contract_complete=False,
        ),
        _attempt(
            "E4",
            "2026-01-01T03:00:00",
            node_id="B",
            session_id="s4",
            seed=1,
            dataset_ids=("ds1",),
            config_hash="cfgX",
            value=0.76,
            baseline=0.70,
            validation="validado",
            contract_complete=True,
        ),
        _attempt(
            "E5",
            "2026-01-01T04:00:00",
            node_id="B",
            session_id="s5",
            seed=1,
            dataset_ids=("ds2",),
            config_hash="cfgY",
            value=0.71,
            baseline=0.70,
            validation="validado",
            contract_complete=True,
        ),
        _attempt(
            "E6",
            "2026-01-01T05:00:00",
            node_id="A",
            session_id="s6",
            seed=1,
            dataset_ids=("ds1",),
            config_hash="cfgX",
            value=0.82,
            baseline=0.70,
            validation="divergente_documentado",
            contract_complete=True,
        ),
    ]


# --------------------------------------------------------------------------- #
# 2. Testes-ouro
# --------------------------------------------------------------------------- #


def test_exemplo_completo_adr_015():
    """2.1 — exemplo completo do ADR 015 §9.6: pesos por evidência e veredito."""
    result = compute_verdict(_adr_e1_to_e6(), R2_CRITERION)

    pesos = {d.attempt_id: d.w for d in result.detalhes}
    assert pesos["E1"] == pytest.approx(1.000, abs=0.005)
    assert pesos["E2"] == pytest.approx(0.160, abs=0.005)
    assert pesos["E3"] == pytest.approx(0.315, abs=0.005)
    assert pesos["E4"] == pytest.approx(0.600, abs=0.005)
    assert pesos["E5"] == pytest.approx(0.800, abs=0.005)
    assert pesos["E6"] == pytest.approx(0.150, abs=0.005)

    assert result.alpha == pytest.approx(3.225, abs=0.005)
    assert result.beta == pytest.approx(1.8, abs=0.005)
    assert result.suporte == pytest.approx(0.642, abs=0.005)
    assert result.certeza == pytest.approx(0.602, abs=0.005)
    assert result.veredito == pytest.approx(0.171, abs=0.005)
    assert result.leitura == "funciona_fraca"
    assert result.tipo_descoberta == "funciona"


def test_so_e1_antes_da_replica():
    """2.2 — só E1, com 4 configurações tentadas e sem réplica ainda."""
    e1 = _attempt(
        "E1",
        "2026-01-01T00:00:00",
        node_id="A",
        session_id="s1",
        seed=1,
        dataset_ids=("ds1",),
        config_hash="cfgX",
        value=0.80,
        baseline=0.70,
        validation="validado",
        contract_complete=True,
    )
    # As outras 3 configurações tentadas na mesma sessão não produziram evidência
    # (ex.: resultado não validado) — mas ainda contam para n_config (b).
    outras_configs = [
        _attempt(
            f"outra-{i}",
            f"2026-01-01T00:0{i}:00",
            node_id="A",
            session_id="s1",
            config_hash=f"cfg-{i}",
            outcome_kind="resultado",
            value=0.5,
            validation="nao_validado",
        )
        for i in range(1, 4)
    ]
    result = compute_verdict([e1, *outras_configs], R2_CRITERION)

    e1_detail = next(d for d in result.detalhes if d.attempt_id == "E1")
    assert e1_detail.b == pytest.approx(0.591, abs=0.005)
    assert result.alpha == pytest.approx(1.59, abs=0.01)
    assert result.beta == pytest.approx(1.0, abs=0.005)
    assert result.veredito == pytest.approx(0.052, abs=0.005)
    assert result.leitura == "insuficiente"


def test_divisao_por_dataset():
    """2.4 — dividindo o exemplo completo por dataset (§9.6): +0,28 e -0,08."""
    attempts = _adr_e1_to_e6()
    dataset_1 = [a for a in attempts if a.dataset_ids == ("ds1",)]
    dataset_2 = [a for a in attempts if a.dataset_ids == ("ds2",)]

    resultado_ds1 = compute_verdict(dataset_1, R2_CRITERION)
    resultado_ds2 = compute_verdict(dataset_2, R2_CRITERION)

    assert resultado_ds1.veredito == pytest.approx(0.28, abs=0.005)
    assert resultado_ds2.veredito == pytest.approx(-0.08, abs=0.005)
    assert resultado_ds2.leitura == "insuficiente"


def _independent_positive_attempts(n: int) -> list[Attempt]:
    """`n` evidências positivas, cada uma de um nó novo (independência máxima)."""
    return [
        _attempt(
            f"pos-{i}",
            f"2026-01-01T00:{i:02d}:00",
            node_id=f"node-{i}",
            session_id=f"session-{i}",
            seed=1,
            dataset_ids=(f"dataset-{i}",),
            config_hash="cfg-shared",
            value=0.60,
            baseline=0.50,
            validation="validado",
            contract_complete=True,
        )
        for i in range(n)
    ]


def _independent_negative_attempts(n: int, offset: int = 0) -> list[Attempt]:
    """`n` evidências negativas, cada uma de um nó novo (independência máxima)."""
    return [
        _attempt(
            f"neg-{offset + i}",
            f"2026-01-02T00:{offset + i:02d}:00",
            node_id=f"node-{offset + i}",
            session_id=f"session-{offset + i}",
            seed=1,
            dataset_ids=(f"dataset-{offset + i}",),
            config_hash="cfg-shared",
            value=0.40,
            baseline=0.50,
            validation="validado",
            contract_complete=True,
        )
        for i in range(n)
    ]


def test_tabela_referencia_1_positivo_1_sessao():
    """2.3 — §9.7 linha 1: 1 positivo, 1 sessão."""
    result = compute_verdict(_independent_positive_attempts(1), R2_CRITERION)
    assert result.alpha == pytest.approx(2.0, abs=0.005)
    assert result.beta == pytest.approx(1.0, abs=0.005)
    assert result.veredito == pytest.approx(0.11, abs=0.005)


def test_tabela_referencia_5_sementes_mesma_sessao():
    """2.3 — §9.7 linha 2: 5 sementes positivas na mesma sessão."""
    attempts = [
        _attempt(
            f"seed-{i}",
            f"2026-01-01T00:{i:02d}:00",
            node_id="node-only",
            session_id="session-only",
            seed=i,
            dataset_ids=("dataset-only",),
            config_hash="cfg-shared",
            value=0.60,
            baseline=0.50,
            validation="validado",
            contract_complete=True,
        )
        for i in range(5)
    ]
    result = compute_verdict(attempts, R2_CRITERION)
    assert result.alpha == pytest.approx(2.8, abs=0.005)
    assert result.beta == pytest.approx(1.0, abs=0.005)
    assert result.veredito == pytest.approx(0.22, abs=0.005)


def test_tabela_referencia_3_nos_diferentes():
    """2.3 — §9.7 linha 3: 3 nós diferentes, todos positivos."""
    result = compute_verdict(_independent_positive_attempts(3), R2_CRITERION)
    assert result.alpha == pytest.approx(4.0, abs=0.005)
    assert result.beta == pytest.approx(1.0, abs=0.005)
    assert result.veredito == pytest.approx(0.36, abs=0.005)


def test_tabela_referencia_5_nos_ou_datasets():
    """2.3 — §9.7 linha 4: 5 nós/datasets diferentes, todos positivos."""
    result = compute_verdict(_independent_positive_attempts(5), R2_CRITERION)
    assert result.alpha == pytest.approx(6.0, abs=0.005)
    assert result.beta == pytest.approx(1.0, abs=0.005)
    assert result.veredito == pytest.approx(0.51, abs=0.005)


def test_tabela_referencia_6_positivos_1_negativo():
    """2.3 — §9.7 linha 5: 6 positivos e 1 negativo, independentes."""
    attempts = _independent_positive_attempts(6) + _independent_negative_attempts(1, offset=6)
    result = compute_verdict(attempts, R2_CRITERION)
    assert result.alpha == pytest.approx(7.0, abs=0.005)
    assert result.beta == pytest.approx(2.0, abs=0.005)
    assert result.veredito == pytest.approx(0.43, abs=0.005)


def test_tabela_referencia_4_negativos_independentes():
    """2.3 — §9.7 linha 6: 4 negativos independentes."""
    result = compute_verdict(_independent_negative_attempts(4), R2_CRITERION)
    assert result.alpha == pytest.approx(1.0, abs=0.005)
    assert result.beta == pytest.approx(5.0, abs=0.005)
    assert result.veredito == pytest.approx(-0.44, abs=0.005)
    assert result.tipo_descoberta == "nao_funciona"
    assert result.leitura == "nao_funciona_moderada"


def test_tabela_referencia_1_positivo_20_configuracoes():
    """2.3 — §9.7 linha 7: 1 positivo entre 20 configurações, sem réplica."""
    vencedor = _attempt(
        "vencedor",
        "2026-01-01T00:00:00",
        node_id="node-a",
        session_id="session-1",
        config_hash="cfg-0",
        value=0.60,
        baseline=0.50,
        validation="validado",
        contract_complete=True,
    )
    outras_configs = [
        _attempt(
            f"perdedor-{i}",
            f"2026-01-01T00:{i:02d}:00",
            node_id="node-a",
            session_id="session-1",
            config_hash=f"cfg-{i}",
            outcome_kind="resultado",
            value=0.3,
            validation="nao_validado",
        )
        for i in range(1, 20)
    ]
    result = compute_verdict([vencedor, *outras_configs], R2_CRITERION)
    assert result.alpha == pytest.approx(1.4, abs=0.01)
    assert result.beta == pytest.approx(1.0, abs=0.005)
    assert result.veredito == pytest.approx(0.03, abs=0.005)
    assert result.leitura == "insuficiente"


# --------------------------------------------------------------------------- #
# 3. Testes de regra
# --------------------------------------------------------------------------- #


def test_sentido_menor_melhor_inverte_delta():
    """3.1 — sentido menor_melhor inverte o cálculo de Δ."""
    criterion = Criterion(sentido="menor_melhor", delta_min=0.05, alvo=None)
    # Métrica menor é melhor: baseline 0.70, valor 0.60 → Δ = baseline - value = 0.10 (positivo)
    melhora = _attempt(
        "melhora", "2026-01-01T00:00:00", value=0.60, baseline=0.70, validation="validado", contract_complete=True
    )
    result = compute_verdict([melhora], criterion)
    assert result.detalhes[0].classificacao == "positiva"

    # Piora: valor 0.80 (maior que baseline, pior para métrica menor_melhor) → Δ negativo
    piora = _attempt(
        "piora", "2026-01-01T00:00:00", value=0.80, baseline=0.70, validation="validado", contract_complete=True
    )
    result_piora = compute_verdict([piora], criterion)
    assert result_piora.detalhes[0].classificacao == "negativa"


def test_sem_baseline_usa_alvo():
    """3.2 — sem baseline usa o alvo, com m = 0,5; sem baseline e sem alvo é ambígua."""
    criterion_com_alvo = Criterion(sentido="maior_melhor", delta_min=None, alvo=0.75)
    atinge_alvo = _attempt(
        "atinge", "2026-01-01T00:00:00", value=0.80, baseline=None, validation="validado", contract_complete=True
    )
    result = compute_verdict([atinge_alvo], criterion_com_alvo)
    detail = result.detalhes[0]
    assert detail.classificacao == "positiva"
    assert detail.m == pytest.approx(0.5)

    criterion_sem_nada = Criterion(sentido="maior_melhor", delta_min=None, alvo=None)
    sem_referencia = _attempt(
        "sem-ref", "2026-01-01T00:00:00", value=0.80, baseline=None, validation="validado", contract_complete=True
    )
    result_ambigua = compute_verdict([sem_referencia], criterion_sem_nada)
    assert result_ambigua.detalhes[0].classificacao == "ambigua"
    assert result_ambigua.n_ambiguas == 1


def test_falha_infraestrutura_nao_afeta_veredito():
    """3.3 — falha de infraestrutura não altera o veredito e soma em n_tentativas."""
    positiva = _attempt(
        "e1", "2026-01-01T00:00:00", value=0.80, baseline=0.70, validation="validado", contract_complete=True
    )
    sem_infra = compute_verdict([positiva], R2_CRITERION)

    infra = _attempt(
        "infra",
        "2026-01-01T00:30:00",
        outcome_kind="falha",
        failure_cause="infraestrutura",
    )
    com_infra = compute_verdict([positiva, infra], R2_CRITERION)

    assert com_infra.veredito == pytest.approx(sem_infra.veredito)
    assert com_infra.n_tentativas == 2
    assert com_infra.n_infraestrutura == 1
    infra_detail = next(d for d in com_infra.detalhes if d.attempt_id == "infra")
    assert infra_detail.classificacao == "infraestrutura"
    assert infra_detail.w == 0.0


def test_falha_abordagem_isolada_e_reproduzida():
    """3.4 — uma falha isolada vira ambígua; duas independentes viram negativas (q=0,3)."""
    isolada = _attempt(
        "isolada",
        "2026-01-01T00:00:00",
        outcome_kind="falha",
        failure_cause="abordagem",
        failure_signature="oom",
    )
    result_isolada = compute_verdict([isolada], R2_CRITERION)
    assert result_isolada.detalhes[0].classificacao == "ambigua"

    reproduzida_1 = _attempt(
        "rep-1",
        "2026-01-01T00:00:00",
        node_id="node-a",
        session_id="session-1",
        outcome_kind="falha",
        failure_cause="abordagem",
        failure_signature="oom",
    )
    reproduzida_2 = _attempt(
        "rep-2",
        "2026-01-01T01:00:00",
        node_id="node-b",
        session_id="session-2",
        outcome_kind="falha",
        failure_cause="abordagem",
        failure_signature="oom",
    )
    result_reproduzida = compute_verdict([reproduzida_1, reproduzida_2], R2_CRITERION)
    for detail in result_reproduzida.detalhes:
        assert detail.classificacao == "negativa"
        assert detail.q == pytest.approx(0.3)
        assert detail.m == pytest.approx(1.0)


def test_fator_conclusao_6_conclusivas_2_ambiguas():
    """3.5 — fator f com 6 conclusivas e 2 ambíguas = 0,875."""
    conclusivas = _independent_positive_attempts(6)
    ambiguas = [
        _attempt(
            f"ambigua-{i}",
            f"2026-01-02T00:{i:02d}:00",
            outcome_kind="falha",
            failure_cause="ambigua",
        )
        for i in range(2)
    ]
    result = compute_verdict(conclusivas + ambiguas, R2_CRITERION)
    assert result.n_ambiguas == 2
    assert result.f == pytest.approx(0.875)


def test_nao_validado_nao_conta_como_evidencia():
    """3.6 — resultado não validado não é evidência, mas conta em n_tentativas."""
    nao_validado = _attempt("nv", "2026-01-01T00:00:00", value=0.80, baseline=0.70, validation="nao_validado")
    result = compute_verdict([nao_validado], R2_CRITERION)
    assert result.n_tentativas == 1
    assert result.n_evidencias == 0
    assert result.detalhes[0].classificacao == "nao_evidencia"
    assert result.alpha == pytest.approx(1.0)
    assert result.beta == pytest.approx(1.0)


def test_resultado_independe_da_ordem_de_entrada():
    """3.7 — o resultado independe da ordem de entrada (ordenado por timestamp)."""
    attempts = _adr_e1_to_e6()
    resultado_ordem_original = compute_verdict(attempts, R2_CRITERION)

    embaralhado = list(attempts)
    random.Random(42).shuffle(embaralhado)
    resultado_embaralhado = compute_verdict(embaralhado, R2_CRITERION)

    assert resultado_embaralhado.veredito == pytest.approx(resultado_ordem_original.veredito)
    assert resultado_embaralhado.alpha == pytest.approx(resultado_ordem_original.alpha)
    assert resultado_embaralhado.beta == pytest.approx(resultado_ordem_original.beta)
    assert [d.attempt_id for d in resultado_embaralhado.detalhes] == [
        d.attempt_id for d in resultado_ordem_original.detalhes
    ]


def test_nenhuma_tentativa_veredito_zero_insuficiente():
    """3.8 — nenhuma tentativa: veredito 0, leitura insuficiente."""
    result = compute_verdict([], R2_CRITERION)
    assert result.veredito == pytest.approx(0.0)
    assert result.leitura == "insuficiente"
    assert result.tipo_descoberta is None
    assert result.n_tentativas == 0
    assert result.detalhes == ()


# --------------------------------------------------------------------------- #
# Requisitos adicionais do spec (detalhamento auditável, parâmetros configuráveis)
# --------------------------------------------------------------------------- #


def test_detalhamento_contem_todas_as_tentativas():
    """Requirement 'Detalhamento auditável': detalhes tem 1 item por tentativa."""
    result = compute_verdict(_adr_e1_to_e6(), R2_CRITERION)
    assert len(result.detalhes) == 6
    for detail in result.detalhes:
        assert detail.classificacao in ("positiva", "negativa", "ambigua", "infraestrutura", "nao_evidencia")


def test_parametro_divergente_configuravel():
    """Requirement 'Parâmetros configuráveis': VERDICT_Q_DIVERGENT ajustável."""
    divergente = _attempt("div", "2026-01-01T00:00:00", value=0.82, baseline=0.70, validation="divergente_documentado")
    params = VerdictParams(q_divergent=0.5)
    result = compute_verdict([divergente], R2_CRITERION, params=params)
    assert result.detalhes[0].q == pytest.approx(0.5)


def test_qualidade_validado_sem_contrato_completo():
    """Requirement 'Pesos objetivos': validado sem contrato completo → q=0,7."""
    sem_semente = _attempt(
        "sem-semente",
        "2026-01-01T00:00:00",
        value=0.80,
        baseline=0.70,
        validation="validado",
        contract_complete=False,
    )
    result = compute_verdict([sem_semente], R2_CRITERION)
    assert result.detalhes[0].q == pytest.approx(0.7)


def test_dataset_novo_vale_como_no_novo():
    """Requirement 'Independência': dataset novo no mesmo nó vale d=1,0."""
    primeiro = _attempt(
        "primeiro",
        "2026-01-01T00:00:00",
        node_id="node-a",
        session_id="session-1",
        dataset_ids=("dataset-1",),
        value=0.80,
        baseline=0.70,
        validation="validado",
        contract_complete=True,
    )
    novo_dataset = _attempt(
        "novo-dataset",
        "2026-01-01T01:00:00",
        node_id="node-a",
        session_id="session-2",
        dataset_ids=("dataset-2",),
        value=0.78,
        baseline=0.70,
        validation="validado",
        contract_complete=True,
    )
    result = compute_verdict([primeiro, novo_dataset], R2_CRITERION)
    novo_detail = next(d for d in result.detalhes if d.attempt_id == "novo-dataset")
    assert novo_detail.d == pytest.approx(1.0)


def test_replica_zera_penalidade_de_busca():
    """Requirement 'Penalidade de busca': após réplica em outro nó, b passa a 1,0."""
    original = _attempt(
        "original",
        "2026-01-01T00:00:00",
        node_id="node-a",
        session_id="session-1",
        config_hash="cfg-shared",
        value=0.80,
        baseline=0.70,
        validation="validado",
        contract_complete=True,
    )
    outras_configs = [
        _attempt(
            f"outra-{i}",
            f"2026-01-01T00:0{i}:00",
            config_hash=f"cfg-{i}",
            value=0.5,
            validation="nao_validado",
        )
        for i in range(1, 4)
    ]
    resultado_sem_replica = compute_verdict([original, *outras_configs], R2_CRITERION)
    original_sem_replica = next(d for d in resultado_sem_replica.detalhes if d.attempt_id == "original")
    assert original_sem_replica.b == pytest.approx(0.591, abs=0.005)

    replica = _attempt(
        "replica",
        "2026-01-01T02:00:00",
        node_id="node-b",
        session_id="session-2",
        config_hash="cfg-shared",
        value=0.79,
        baseline=0.70,
        validation="validado",
        contract_complete=True,
    )
    resultado_com_replica = compute_verdict([original, replica, *outras_configs], R2_CRITERION)
    original_com_replica = next(d for d in resultado_com_replica.detalhes if d.attempt_id == "original")
    assert original_com_replica.b == pytest.approx(1.0)


def test_attempt_resultado_sem_value_levanta_erro():
    """Robustez: outcome_kind='resultado' sem 'value' deve falhar de forma explícita."""
    invalida = _attempt("invalida", "2026-01-01T00:00:00", validation="validado")
    with pytest.raises(ValueError):
        compute_verdict([invalida], R2_CRITERION)


def test_attempt_falha_abordagem_sem_assinatura_levanta_erro():
    """Robustez: falha de abordagem sem 'failure_signature' deve falhar explicitamente."""
    invalida = _attempt("invalida", "2026-01-01T00:00:00", outcome_kind="falha", failure_cause="abordagem")
    with pytest.raises(ValueError):
        compute_verdict([invalida], R2_CRITERION)
