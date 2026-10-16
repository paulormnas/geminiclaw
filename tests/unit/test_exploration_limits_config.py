"""Variáveis dos limites da exploração (v18.7-exploration-limits, seção 1; specs ``usage-limits``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.utils.configuration_error import ConfigurationError
from tests.support.env_override import env_override

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def test_padroes_do_design():
    with env_override() as load:
        config = load()
        assert config.SESSION_MAX_COST_USD == 20.0 and config.SESSION_MAX_COST_USD_BY_PROVIDER == {}
        assert config.OPERATIONAL_THRESHOLD_COST_USAGE_PCT == 0.80
        assert (config.EXPLORATION_STALL_CYCLES, config.EXPLORATION_MAX_INTERVENTIONS) == (5, 3)
        assert config.EXPLORATION_PATIENCE_GROWTH == 0.5
        assert (config.SATURATION_MIN_REPLICATES, config.SATURATION_SE_MULTIPLIER) == (3, 1.0)
        assert (config.COVERAGE_NOVELTY_WINDOW, config.COVERAGE_NOVELTY_MIN_RATE) == (5, 0.2)
        assert config.RESTRICTION_SIMILARITY == 0.80 and config.ON_PLAN_REJECTIONS == "explorar"


@pytest.mark.parametrize("value", ["0", "-1", "", "abc"])
def test_zero_nao_desliga_o_limite_de_custo(value):
    """Scenario: Zero não desliga."""
    with env_override({"SESSION_MAX_COST_USD": value}) as load:
        with pytest.raises(ConfigurationError) as error:
            load()
    assert "SESSION_MAX_COST_USD" in str(error.value)
    if value in ("0", "-1", ""):
        assert "--unlimited" in str(error.value)


def test_custo_por_provedor_valido():
    with env_override({"SESSION_MAX_COST_USD_BY_PROVIDER": "google=5, anthropic=2.5"}) as load:
        assert load().SESSION_MAX_COST_USD_BY_PROVIDER == {"google": 5.0, "anthropic": 2.5}


@pytest.mark.parametrize("value", ["google=abc", "google=0", "google", "=3", "google=-1"])
def test_formato_invalido_do_custo_por_provedor(value):
    """Scenario: Formato inválido."""
    with env_override({"SESSION_MAX_COST_USD_BY_PROVIDER": value}) as load:
        with pytest.raises(ConfigurationError, match="SESSION_MAX_COST_USD_BY_PROVIDER"):
            load()


@pytest.mark.parametrize(
    "name,value",
    [
        ("OPERATIONAL_THRESHOLD_COST_USAGE_PCT", "0"),
        ("OPERATIONAL_THRESHOLD_COST_USAGE_PCT", "1.5"),
        ("EXPLORATION_STALL_CYCLES", "-1"),
        ("EXPLORATION_STALL_CYCLES", "2.5"),
        ("EXPLORATION_MAX_INTERVENTIONS", "0"),
        ("EXPLORATION_PATIENCE_GROWTH", "-0.1"),
        ("SATURATION_MIN_REPLICATES", "1"),
        ("SATURATION_SE_MULTIPLIER", "0"),
        ("COVERAGE_NOVELTY_WINDOW", "0"),
        ("COVERAGE_NOVELTY_MIN_RATE", "-1"),
        ("RESTRICTION_SIMILARITY", "0"),
        ("RESTRICTION_SIMILARITY", "1.01"),
        ("ON_PLAN_REJECTIONS", "ignorar"),
        ("SATURATION_MIN_REPLICATES", ""),
    ],
)
def test_valor_fora_da_regra_falha_citando_a_variavel(name, value):
    with env_override({name: value}) as load:
        with pytest.raises(ConfigurationError, match=name):
            load()


def test_zero_em_estagnacao_desliga_e_limites_de_borda_valem():
    env = {"EXPLORATION_STALL_CYCLES": "0", "RESTRICTION_SIMILARITY": "1", "ON_PLAN_REJECTIONS": "PARAR",
           "COVERAGE_NOVELTY_MIN_RATE": "0", "EXPLORATION_PATIENCE_GROWTH": "0"}
    with env_override(env) as load:
        config = load()
        assert config.EXPLORATION_STALL_CYCLES == 0 and config.RESTRICTION_SIMILARITY == 1.0
        assert config.ON_PLAN_REJECTIONS == "parar"


def test_env_example_documenta_as_variaveis():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("SESSION_MAX_COST_USD", "SESSION_MAX_COST_USD_BY_PROVIDER", "OPERATIONAL_THRESHOLD_COST_USAGE_PCT",
                 "EXPLORATION_STALL_CYCLES", "EXPLORATION_MAX_INTERVENTIONS", "EXPLORATION_PATIENCE_GROWTH",
                 "SATURATION_MIN_REPLICATES", "SATURATION_SE_MULTIPLIER", "COVERAGE_NOVELTY_WINDOW",
                 "COVERAGE_NOVELTY_MIN_RATE", "RESTRICTION_SIMILARITY", "ON_PLAN_REJECTIONS"):
        assert f"\n{name}=" in text
