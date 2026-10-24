import pytest

from scripts.memory_eval.snapshot import approach_key, problem_signature

pytestmark = pytest.mark.unit


def test_chave_da_abordagem_ignora_caixa_acento_e_pontuacao():
    assert approach_key("Random Forest") == approach_key("random  forest")
    assert approach_key("Regressão Logística (L2)") == "regressao logistica l2"


def test_assinatura_do_problema_ignora_a_ordem():
    a = {"classes": "3", "tamanho": "150 amostras"}
    assert problem_signature(a) == problem_signature(dict(reversed(list(a.items()))))
    assert problem_signature(None) == ""
