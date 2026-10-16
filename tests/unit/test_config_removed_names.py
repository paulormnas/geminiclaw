"""Configuração sem designação de máquina (v18.7-resource-monitor-config, specs ``agent-runtime``)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.config import check_removed_variables
from src.utils.configuration_error import ConfigurationError
from tests.support.env_override import env_override

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


# --- Nomes removidos ----------------------------------------------------------------------------------------------


def test_prefixo_pi():
    """Scenario: Prefixo PI_ (a mensagem cita os nomes novos)."""
    with env_override({"PI_TEMPERATURE_LIMIT": "75.0", "PI_MIN_AVAILABLE_MEMORY_MB": "512.0"}) as load:
        with pytest.raises(ConfigurationError) as error:
            load()
    assert "TEMPERATURE_LIMIT" in str(error.value) and "MIN_AVAILABLE_MEMORY_MB" in str(error.value)
    assert str(error.value).count("\n- ") == 2


def test_perfil_default_pede_so_remover_a_linha():
    """Scenario: Perfil default."""
    with env_override({"DEPLOYMENT_PROFILE": "default"}) as load:
        with pytest.raises(ConfigurationError) as error:
            load()
    assert "remova a linha" in str(error.value)
    assert "MAX_CONCURRENT_AGENTS" not in str(error.value)


def test_perfil_pi5_lista_os_valores_do_perfil():
    """Scenario: Perfil pi5."""
    with env_override({"DEPLOYMENT_PROFILE": "pi5"}) as load:
        with pytest.raises(ConfigurationError) as error:
            load()
    for text in (
        "MAX_SUBTASKS_PER_TASK=5", "MAX_CONCURRENT_AGENTS=2", "AGENT_TIMEOUT_SECONDS=0",
        "LLM_PROVIDER_PRIORITY=ollama,openai_compatible,google,anthropic,openai",
    ):
        assert text in str(error.value)


def test_valor_do_nome_removido_nao_e_ecoado():
    with env_override({"DEPLOYMENT_PROFILE": "valor-secreto-xyz", "PI_TEMPERATURE_LIMIT": "senha-123"}) as load:
        with pytest.raises(ConfigurationError) as error:
            load()
    assert "valor-secreto-xyz" not in str(error.value) and "senha-123" not in str(error.value)


def test_nome_antigo_nunca_e_lido_como_sinonimo():
    with pytest.raises(ConfigurationError):
        check_removed_variables({"PI_TEMPERATURE_LIMIT": "80"})
    check_removed_variables({"TEMPERATURE_LIMIT": "80"})  # sem nome removido: não falha


def test_mecanismo_aceita_nomes_acrescentados(monkeypatch):
    """A interface é estável para ``v18.7-exploration-limits`` acrescentar nomes ao dicionário."""
    from src import config

    monkeypatch.setitem(config._REMOVED_VARIABLES, "NOME_FICTICIO", "renomeie NOME_FICTICIO para OUTRO")
    monkeypatch.setitem(config._REMOVED_VARIABLES, "NOME_COM_VALOR", lambda value: f"valor tipo {value[:1]}")
    with pytest.raises(ConfigurationError) as error:
        check_removed_variables({"NOME_FICTICIO": "x", "NOME_COM_VALOR": "abc"})
    assert "renomeie NOME_FICTICIO" in str(error.value) and "valor tipo a" in str(error.value)


def test_comando_direto_com_nome_antigo():
    """Scenario: Comando direto com nome antigo (código 1, antes de qualquer chamada a provedor)."""
    env = {k: v for k, v in os.environ.items() if k not in {"DEPLOYMENT_PROFILE", "PI_TEMPERATURE_LIMIT"}}
    env["PI_MIN_AVAILABLE_MEMORY_MB"] = "512.0"
    result = subprocess.run(
        [sys.executable, "-m", "src.cli.main", "tarefa"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 1
    assert "MIN_AVAILABLE_MEMORY_MB" in result.stderr


# --- Limites e padrões --------------------------------------------------------------------------------------------


def test_padroes_gerais():
    """Scenario: Padrões gerais."""
    with env_override({}) as load:
        module = load()
        assert module.MIN_AVAILABLE_MEMORY_MB == 512
        assert module.TEMPERATURE_LIMIT is None
        assert module.MAX_SUBTASKS_PER_TASK == 10
        assert module.MAX_CONCURRENT_AGENTS == 3
        assert module.AGENT_TIMEOUT_SECONDS == 300
        assert module.TEMPERATURE_WARNING_MARGIN_C == 5.0
        assert module.TEMPERATURE_SENSOR == ""
        assert not hasattr(module, "DEPLOYMENT_PROFILE")


@pytest.mark.parametrize("value", ["-1", "0", "abc"])
def test_limite_de_temperatura_invalido(value):
    """Scenario: Limite de temperatura inválido."""
    with env_override({"TEMPERATURE_LIMIT": value}) as load:
        with pytest.raises(ConfigurationError, match="TEMPERATURE_LIMIT"):
            load()


def test_limite_de_temperatura_valido_e_margem():
    with env_override({"TEMPERATURE_LIMIT": "80", "TEMPERATURE_WARNING_MARGIN_C": "3"}) as load:
        module = load()
        assert module.TEMPERATURE_LIMIT == 80.0 and module.TEMPERATURE_WARNING_MARGIN_C == 3.0
    with env_override({"TEMPERATURE_WARNING_MARGIN_C": "-1"}) as load:
        with pytest.raises(ConfigurationError, match="TEMPERATURE_WARNING_MARGIN_C"):
            load()


def test_zero_e_sem_limite_de_tempo():
    """Scenario: Zero é sem limite (o runtime já trata ``None`` sem interromper o agente)."""
    with env_override({"AGENT_TIMEOUT_SECONDS": "0"}) as load:
        assert load().AGENT_TIMEOUT_SECONDS is None


@pytest.mark.parametrize("value", ["abc", "-5", "1.5"])
def test_tempo_limite_invalido(value):
    """Scenario: Valor inválido."""
    with env_override({"AGENT_TIMEOUT_SECONDS": value}) as load:
        with pytest.raises(ConfigurationError, match="AGENT_TIMEOUT_SECONDS"):
            load()


def test_variaveis_de_limites_declaradas():
    with env_override({"MIN_AVAILABLE_MEMORY_MB": "1024", "MAX_CONCURRENT_AGENTS": "2", "TEMPERATURE_SENSOR": "nvme"}) as load:
        module = load()
        assert module.MIN_AVAILABLE_MEMORY_MB == 1024.0 and module.MAX_CONCURRENT_AGENTS == 2
        assert module.TEMPERATURE_SENSOR == "nvme"
