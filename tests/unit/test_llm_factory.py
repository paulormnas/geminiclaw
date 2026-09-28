from unittest.mock import patch

import pytest

from src.llm.factory import get_provider
from src.llm.providers.ollama import OllamaProvider


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reseta a instância singleton do provedor antes de cada teste."""
    import src.llm.factory
    src.llm.factory._provider_instance = None
    yield


@pytest.mark.unit
def test_get_provider_ollama_default():
    """Valida a criação do OllamaProvider via registro."""
    with patch("src.config.LLM_PROVIDER", "ollama"), \
         patch("src.config.OLLAMA_BASE_URL", "http://test:11434"), \
         patch("src.config.LLM_MODEL", "test-model"):
        provider = get_provider()
        assert isinstance(provider, OllamaProvider)
        assert provider.model_name == "test-model"


@pytest.mark.unit
def test_get_provider_local_alias_resolves_to_ollama():
    """Valida que o alias legado 'local' resolve para o provedor 'ollama'."""
    with patch("src.config.LLM_PROVIDER", "local"), \
         patch("src.config.OLLAMA_BASE_URL", "http://test:11434"), \
         patch("src.config.LLM_MODEL", "test-model"):
        provider = get_provider()
        assert isinstance(provider, OllamaProvider)


@pytest.mark.unit
def test_get_provider_google_default():
    """Valida que o provedor 'google' é criado via registro quando google-genai está instalado."""
    pytest.importorskip("google.genai")
    from src.llm.providers.google import GoogleProvider

    with patch("src.config.LLM_PROVIDER", "google"), \
         patch("src.config.GEMINI_API_KEY", "test-key"):
        provider = get_provider()
        assert isinstance(provider, GoogleProvider)


@pytest.mark.unit
def test_get_provider_singleton():
    """Valida que get_provider retorna a mesma instância (singleton)."""
    with patch("src.config.LLM_PROVIDER", "ollama"), \
         patch("src.config.OLLAMA_BASE_URL", "http://test:11434"), \
         patch("src.config.LLM_MODEL", "test-model"):
        p1 = get_provider()
        p2 = get_provider()
        assert p1 is p2


@pytest.mark.unit
def test_invalid_provider_raises_error_listing_available():
    """Valida que um provedor inválido lança ValueError listando os provedores disponíveis."""
    with patch("src.config.LLM_PROVIDER", "unknown"):
        with pytest.raises(ValueError) as exc_info:
            get_provider()

        msg = str(exc_info.value)
        assert "unknown" in msg
        assert "ollama" in msg
        assert "google" in msg
        assert "openai_compatible" in msg
