"""Testes unitários para o Model Router (Roadmap V14.1 / V16)."""

from unittest.mock import MagicMock, patch

import pytest

from src.llm import registry
from src.llm.base import LLMProvider, LLMResponse
from src.llm.providers.ollama import OllamaProvider
from src.model_config import get_role_model_config
from src.model_router import ModelRouter


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

    # Provedor 'ollama' (validator) não depende de pacote opcional.
    with patch("src.config.OLLAMA_BASE_URL", "http://test:11434"):
        validator_provider = ModelRouter.get_provider("validator")
        assert isinstance(validator_provider, OllamaProvider)
        assert validator_provider.model_name == "qwen3:8b"

    # Provedor 'google' (researcher/developer) só é exercido se google-genai estiver instalado.
    pytest.importorskip("google.genai")
    from src.llm.providers.google import GoogleProvider

    with patch("src.config.GEMINI_API_KEY", "dummy_key"):
        researcher_provider = ModelRouter.get_provider("researcher")
        assert isinstance(researcher_provider, GoogleProvider)
        assert researcher_provider.model_name == "gemini-2.0-flash"

        developer_provider = ModelRouter.get_provider("developer")
        assert isinstance(developer_provider, GoogleProvider)
        assert developer_provider.model_name == "gemini-2.0-flash"


@pytest.mark.unit
def test_model_router_env_overrides(monkeypatch):
    """Cenário 2: Sobrescrita de modelo e provedor via variáveis de ambiente."""
    monkeypatch.setenv("VALIDATOR_PROVIDER", "ollama")
    monkeypatch.setenv("VALIDATOR_MODEL", "qwen-custom-validator")
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://test:11434")

    cfg = get_role_model_config("validator")
    assert cfg.provider == "ollama"
    assert cfg.model == "qwen-custom-validator"

    provider = ModelRouter.get_provider("validator")
    assert isinstance(provider, OllamaProvider)
    assert provider.model_name == "qwen-custom-validator"


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


class _FakeProvider(LLMProvider):
    """Provedor fictício usado para validar a extensibilidade do registro (spec V16)."""

    def __init__(self, model: str):
        self._model = model

    async def generate(self, messages, tools=None, system=None, temperature=0.7, max_tokens=4096):
        return LLMResponse(text="ok")

    async def generate_stream(self, messages, system=None):
        yield "ok"

    async def health_check(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return self._model


@pytest.mark.unit
def test_model_router_uses_provider_registered_without_touching_router_code(monkeypatch):
    """Cenário: um provedor registrado só em teste é resolvido pelo ModelRouter sem editar
    `model_router.py` — valida o requisito 'Adicionar provedor sem editar código central'."""
    registry.register_provider("fake", lambda settings: _FakeProvider(settings.model))
    monkeypatch.setenv("VALIDATOR_PROVIDER", "fake")
    monkeypatch.setenv("VALIDATOR_MODEL", "fake-model")

    provider = ModelRouter.get_provider("validator")

    assert isinstance(provider, _FakeProvider)
    assert provider.model_name == "fake-model"
