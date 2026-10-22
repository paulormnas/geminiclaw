"""Variáveis removidas pelo ADR 026: a carga da configuração as recusa, citando o ADR (``hypothesis-loop``)."""

from __future__ import annotations

import pytest

from src.config import check_removed_variables
from src.utils.configuration_error import ConfigurationError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "name",
    ["VERDICT_PRIOR", "VERDICT_THRESHOLDS", "KNOWLEDGE_SHORTCUT_MIN_VERDICT", "DECISION_EVAL_MIN_VERDICT",
     "SIM_CROSS_PROJECT_MIN_CONFIDENCE"],
)
def test_variavel_do_veredito_e_recusada_com_mensagem_acionavel(name):
    with pytest.raises(ConfigurationError, match=name) as exc:
        check_removed_variables({name: "0.5"})
    assert "ADR 026" in str(exc.value) and "remova a linha" in str(exc.value)


def test_variavel_de_fora_do_projeto_com_o_mesmo_prefixo_nao_e_recusada():
    check_removed_variables({"VERDICT_API_URL": "https://exemplo.test", "PATH": "/usr/bin"})


def test_minimos_de_replicas_tem_padrao_dois():
    from src import config

    assert config.HYPOTHESIS_MIN_REPLICAS == 2 and config.HYPOTHESIS_MIN_REFUTATIONS == 2
