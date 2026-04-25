import pytest
from unittest.mock import patch
from src.llm.factory import get_provider
from src.llm.providers.google import GoogleProvider
from src.llm.providers.ollama import OllamaProvider
from src import config

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reseta a instância singleton do provedor antes de cada teste."""
    import src.llm.factory
    src.llm.factory._provider_instance = None
    yield

def test_get_provider_google_default():
    """Valida que o provedor padrão é GoogleProvider."""
    with patch("src.config.LLM_PROVIDER", "google"), \
         patch("src.config.GEMINI_API_KEY", "test-key"):
        provider = get_provider()
        assert isinstance(provider, GoogleProvider)

def test_get_provider_ollama():
    """Valida a criação do OllamaProvider."""
    with patch("src.config.LLM_PROVIDER", "ollama"), \
         patch("src.config.OLLAMA_BASE_URL", "http://test:11434"), \
         patch("src.config.LLM_MODEL", "test-model"):
        provider = get_provider()
        assert isinstance(provider, OllamaProvider)
        assert provider.model_name == "test-model"

def test_get_provider_singleton():
    """Valida que get_provider retorna a mesma instância (singleton)."""
    with patch("src.config.LLM_PROVIDER", "google"), \
         patch("src.config.GEMINI_API_KEY", "test-key"):
        p1 = get_provider()
        p2 = get_provider()
        assert p1 is p2

def test_invalid_provider_raises_error():
    """Valida que um provedor inválido sem fallback lança ValueError."""
    with patch("src.config.LLM_PROVIDER", "unknown"):
        with pytest.raises(ValueError, match="LLM_PROVIDER inválido"):
            get_provider()
