"""``v18.7-hypothesis-linking``: papel do experimento decidido por ordem fixa (spec ``hypothesis-loop``)."""

from __future__ import annotations

import pytest

from src.knowledge.system_hypotheses import MetricRef
from src.orchestration.exploration_roles import (
    FONTE_DECLARADO,
    FONTE_ESTRUTURA_DAG,
    FONTE_HYPOTHESIS_REF,
    FONTE_RESIDUAL,
    FONTE_SINAL_DE_TESTE,
    FONTE_TASK_TYPE,
    classify_role,
    declared_role,
    declared_roles,
    has_test_signal,
)
from tests.support.linking_world import LinkingCycle, sub, to_task

M = MetricRef(id="m1", nome="acuracia", sinonimos=("accuracy", "test_accuracy"))

pytestmark = pytest.mark.unit


def _decide(item, others=(), *, resolved=False, metric=M):
    tasks = [to_task(item), *(to_task(o) for o in others)]
    decision = classify_role(tasks[0], tasks, metric, resolved)
    return decision.papel, decision.fonte


def test_preprocessamento_e_preparacao():
    """Scenario: Pré-processamento é preparação."""
    pre = sub("preprocessar_dados", criteria=("proporção de nulos <= 0",))
    deps = [sub(f"treinar_{i}", depends_on=["preprocessar_dados"]) for i in range(3)]
    assert _decide(pre, deps) == ("preparacao", FONTE_ESTRUTURA_DAG)


def test_teste_que_alimenta_comparacao_continua_teste():
    """Scenario: Teste que alimenta comparação continua teste."""
    rf = sub("treinar_rf", criteria=("accuracy >= 0.9",))
    comparar = sub("comparar_modelos", depends_on=["treinar_rf"])
    assert _decide(rf, [comparar]) == ("teste", FONTE_SINAL_DE_TESTE)


def test_limiar_sobre_outra_grandeza_nao_e_sinal_de_teste():
    """Scenario: Limiar sobre outra grandeza não é sinal de teste."""
    split = sub("dividir_treino_teste", criteria=("proporção de teste >= 0.2",),
                approach={"nome": "split estratificado", "tipo": "protocolo"})
    assert _decide(split) == ("preparacao", FONTE_RESIDUAL)


@pytest.mark.parametrize("criterio", ["cv_accuracy >= 0.8", "acurácia de treino >= 0.8", "validation accuracy >= 0.8"])
def test_limiar_de_validacao_cruzada_treino_ou_validacao_nao_e_sinal_de_teste(criterio):
    """Scenario: Limiar de validação cruzada não é sinal de teste."""
    assert _decide(sub("s", criteria=(criterio,)))[1] != FONTE_SINAL_DE_TESTE


@pytest.mark.parametrize("criterio", ["accuracy >= 0.9", "acurácia no teste >= 0.95", "test_accuracy > 0,8"])
def test_limiar_sobre_a_metrica_com_ou_sem_qualificador_de_teste_e_sinal(criterio):
    assert has_test_signal([criterio], M)


def test_sem_metrica_so_a_abordagem_de_algoritmo_da_sinal():
    """Design §2.3 / questão 3: sem ``MetricRef`` o critério numérico não basta."""
    assert not has_test_signal(["accuracy >= 0.9"], None)
    algoritmo = sub("s", criteria=None, approach={"nome": "svm", "tipo": "algoritmo"})
    assert _decide(algoritmo, metric=None) == ("teste", FONTE_SINAL_DE_TESTE)


def test_eda_com_abordagem_preenchida_e_preparacao():
    """Scenario: EDA com abordagem preenchida."""
    eda = sub("eda", task_type="eda", approach={"nome": "análise exploratória", "tipo": "algoritmo"})
    assert _decide(eda) == ("preparacao", FONTE_TASK_TYPE)


def test_hypothesis_ref_resolvido_e_teste():
    assert _decide(sub("s", criteria=None), resolved=True) == ("teste", FONTE_HYPOTHESIS_REF)


def test_papel_declarado_vence_e_referencia_so_vem_da_declaracao():
    baseline = sub("baseline_majoritario", task_type="validation", papel="referencia")
    assert _decide(baseline) == ("referencia", FONTE_DECLARADO)
    # a declaração vence o task_type (questão 4): uma EDA declarada ``teste`` é teste
    assert _decide(sub("eda", task_type="eda", papel="teste")) == ("teste", FONTE_DECLARADO)
    assert _decide(sub("dummy", criteria=("accuracy >= 0.3",)))[0] == "teste"  # sem declaração nunca é referência


def test_papel_invalido_e_tratado_como_ausente():
    assert declared_role("Exploratoria") == "exploratoria"
    assert _decide(sub("s", criteria=None, papel="exploratoria"))[1] == FONTE_RESIDUAL


def test_papeis_declarados_do_evento_so_os_validos():
    plan = [sub("a", papel="referencia"), sub("b", papel="exploratoria"), sub("c")]
    assert declared_roles(plan) == {"a": "referencia"}


def test_papel_gravado_pelo_ciclo_nas_subtarefas(tmp_path):
    """O ciclo decide o papel de todas as subtarefas não concluídas e o registra em ``papel_decidido``/``papel_fonte``."""
    cycle = LinkingCycle(tmp_path)
    cycle.run([
        sub("eda", task_type="eda", criteria=None),
        sub("preprocessar_dados", criteria=("proporção de nulos <= 0",), depends_on=["eda"]),
        sub("treinar_rf", depends_on=["preprocessar_dados"], approach={"nome": "rf", "tipo": "algoritmo"}),
    ])
    got = {n: (t.papel_decidido, t.papel_fonte) for n, t in cycle.tasks.items()}
    assert got == {
        "eda": ("preparacao", FONTE_TASK_TYPE),
        "preprocessar_dados": ("preparacao", FONTE_ESTRUTURA_DAG),
        "treinar_rf": ("teste", FONTE_SINAL_DE_TESTE),
    }
