"""Testes unitários para o Model Router (Roadmap V14.1)."""

import os
import pytest
from unittest.mock import patch, MagicMock

from src.model_config import get_role_model_config, DEFAULT_ROLE_CONFIGS
from src.model_router import ModelRouter
from src.llm.providers.google import GoogleProvider
from src.llm.providers.ollama import OllamaProvider


@pytest.fixture(autouse=True)
def clean_router_cache():
    """Garante cache limpo antes e após cada teste."""
    ModelRouter.clear_cache()
    yield
    ModelRouter.clear_cache()


@pytest.mark.unit
def test_model_router_default_roles():
    """Cenário 1: Verifica o mapeamento padrão para researcher, validator e developer."""
    researcher_cfg = get_role_model_config("researcher")
    assert researcher_cfg.provider == "google"
    assert researcher_cfg.model == "gemini-2.0-flash"

    validator_cfg = get_role_model_config("validator")
    assert validator_cfg.provider == "ollama"
    assert validator_cfg.model == "qwen3:8b"

    developer_cfg = get_role_model_config("developer")
    assert developer_cfg.provider == "google"
    assert developer_cfg.model == "gemini-2.0-flash"

    # Testa instanciação dos provedores com mocks
    with patch("src.config.GEMINI_API_KEY", "dummy_key"):
        researcher_provider = ModelRouter.get_provider("researcher")
        assert isinstance(researcher_provider, GoogleProvider)
        assert researcher_provider.model_name == "gemini-2.0-flash"

        validator_provider = ModelRouter.get_provider("validator")
        assert isinstance(validator_provider, OllamaProvider)
        assert validator_provider.model_name == "qwen3:8b"

        developer_provider = ModelRouter.get_provider("developer")
        assert isinstance(developer_provider, GoogleProvider)
        assert developer_provider.model_name == "gemini-2.0-flash"


@pytest.mark.unit
def test_model_router_env_overrides(monkeypatch):
    """Cenário 2: Sobrescrita de modelo e provedor via variáveis de ambiente."""
    monkeypatch.setenv("VALIDATOR_PROVIDER", "google")
    monkeypatch.setenv("VALIDATOR_MODEL", "gemini-custom-validator")
    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key")

    cfg = get_role_model_config("validator")
    assert cfg.provider == "google"
    assert cfg.model == "gemini-custom-validator"

    provider = ModelRouter.get_provider("validator")
    assert isinstance(provider, GoogleProvider)
    assert provider.model_name == "gemini-custom-validator"


@pytest.mark.unit
def test_model_router_invalid_role_raises_value_error():
    """Cenário 3: Solicitação de papel inexistente deve levantar ValueError claro."""
    invalid_role = "papel_inexistente"
    with pytest.raises(ValueError) as exc_info:
        ModelRouter.get_provider(invalid_role)

    msg = str(exc_info.value)
    assert "Papel desconhecido" in msg
    assert invalid_role in msg
    assert "researcher" in msg
    assert "validator" in msg
    assert "developer" in msg


@pytest.mark.unit
def test_model_router_fallback_none_role():
    """Cenário 4: Fallback para o modelo padrão quando role=None (retrocompatibilidade)."""
    with patch("src.llm.factory.get_provider") as mock_get_provider:
        dummy_provider = MagicMock()
        mock_get_provider.return_value = dummy_provider

        result = ModelRouter.get_provider(None)
        assert result == dummy_provider
        mock_get_provider.assert_called_once()
