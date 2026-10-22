"""Registro de resultado e regra de réplicas (módulo puro; ADR 026 §2 e §3)."""

from __future__ import annotations

import pytest

from src.knowledge.result_records import (
    Attempt,
    Criterion,
    classify_attempt,
    compute_record,
    holds_fails,
    holds_works,
    hypothesis_state,
    improvement,
    reaches_target,
)

pytestmark = pytest.mark.unit

ALVO = Criterion(sentido="maior_melhor", delta_min=0.01, alvo=0.93)
MENOR = Criterion(sentido="menor_melhor", delta_min=None, alvo=0.10)


def attempt(valor, *, seed=1, datasets=("d1",), when="2026-10-22T10:00:00", baseline=None, kind="resultado", aid=None):
    return Attempt(
        attempt_id=aid or f"a-{seed}-{valor}-{'-'.join(datasets)}", timestamp=when, node_id="A", session_id="s",
        seed=seed, dataset_ids=tuple(datasets), config_hash="h", outcome_kind=kind, value=valor, baseline=baseline,
        validation="validado",
    )


def test_duas_replicas_acima_do_alvo_validam_e_dao_os_fatos_do_registro():
    facts = compute_record([attempt(0.94, seed=1), attempt(0.95, seed=2)], ALVO)
    assert facts.melhor_valor == 0.95 and facts.n_tentativas_validas == 2
    assert facts.n_replicas_independentes == facts.n_atingiu_alvo == 2 and facts.n_abaixo_alvo == 0
    assert facts.atingiu_alvo is True
    assert hypothesis_state(facts.n_atingiu_alvo, facts.n_abaixo_alvo, min_replicas=2, min_refutations=2) == "validada"
    assert holds_works(facts, min_replicas=2) and not holds_fails(facts, min_refutations=2)


def test_mesma_semente_e_mesmo_conjunto_contam_uma_replica_so():
    facts = compute_record([attempt(0.94, seed=1), attempt(0.95, seed=1)], ALVO)
    assert facts.n_tentativas_validas == 2 and facts.n_replicas_independentes == 1
    assert facts.n_atingiu_alvo == 1
    assert hypothesis_state(1, 0, min_replicas=2, min_refutations=2) is None


def test_outro_conjunto_de_dados_e_replica_independente_mesmo_com_a_mesma_semente():
    facts = compute_record([attempt(0.94, datasets=("d1",)), attempt(0.95, datasets=("d2",))], ALVO)
    assert facts.n_replicas_independentes == 2 and facts.n_atingiu_alvo == 2


def test_refutacao_exige_duas_abaixo_do_alvo_e_nenhuma_acima():
    abaixo = compute_record([attempt(0.60, seed=1), attempt(0.62, seed=2)], ALVO)
    assert abaixo.n_abaixo_alvo == 2 and abaixo.n_atingiu_alvo == 0
    assert hypothesis_state(0, 2, min_replicas=2, min_refutations=2) == "refutada"
    assert holds_fails(abaixo, min_refutations=2)
    misto = compute_record([attempt(0.60, seed=1), attempt(0.62, seed=2), attempt(0.95, seed=3)], ALVO)
    assert misto.n_atingiu_alvo == 1 and not holds_fails(misto, min_refutations=2)
    assert hypothesis_state(1, 2, min_replicas=2, min_refutations=2) is None


def test_tentativa_sem_valor_nao_conta_e_o_registro_vazio_nao_conclui():
    facts = compute_record([attempt(None, kind="falha")], ALVO)
    assert facts.n_tentativas_validas == 0 and facts.melhor_valor is None and not facts.atingiu_alvo


def test_delta_base_e_delta_pai_sao_melhoras_medidas():
    facts = compute_record([attempt(0.94, baseline=0.60)], ALVO, parent_best=0.90)
    assert facts.delta_base == pytest.approx(0.34) and facts.delta_pai == pytest.approx(0.04)
    sem_referencia = compute_record([attempt(0.94)], ALVO)
    assert sem_referencia.delta_base is None and sem_referencia.delta_pai is None
    com_referencia = compute_record([attempt(0.94)], ALVO, reference_value=0.90)
    assert com_referencia.delta_base == pytest.approx(0.04)


def test_metrica_a_minimizar_inverte_o_sentido_das_comparacoes():
    assert improvement(0.08, 0.10, "menor_melhor") == pytest.approx(0.02)
    assert reaches_target(0.09, None, MENOR) and not reaches_target(0.12, None, MENOR)
    facts = compute_record([attempt(0.09, seed=1), attempt(0.07, seed=2)], MENOR)
    assert facts.melhor_valor == 0.07 and facts.n_atingiu_alvo == 2


def test_sem_alvo_vale_a_melhora_minima_sobre_a_linha_de_base_e_sem_nenhum_nao_conclui():
    comparativo = Criterion(sentido="maior_melhor", delta_min=0.05, alvo=None)
    assert reaches_target(0.80, 0.70, comparativo) and not reaches_target(0.72, 0.70, comparativo)
    assert not reaches_target(0.80, None, comparativo)


def test_classificacao_da_tentativa_e_o_resultado_nao_depende_da_ordem():
    a, b = attempt(0.95, seed=1, when="2026-10-22T10:00:00"), attempt(0.60, seed=2, when="2026-10-22T11:00:00")
    assert classify_attempt(a, ALVO) == "atingiu" and classify_attempt(b, ALVO) == "abaixo"
    assert classify_attempt(attempt(None, kind="falha"), ALVO) == "invalida"
    assert compute_record([a, b], ALVO) == compute_record([b, a], ALVO)
