"""``get_provider()`` sem papel: delega ao ModelRouter (papel ``researcher``), sem singleton."""

import pytest

from src.llm.factory import get_provider
from src.llm.providers.ollama import OllamaProvider
from src.model_router import ModelRouter


@pytest.fixture(autouse=True)
def clean_router_cache():
    ModelRouter.clear_cache()
    yield
    ModelRouter.clear_cache()


@pytest.mark.unit
def test_get_provider_delega_ao_researcher(monkeypatch):
    """Valida a criação do OllamaProvider pelo roteador (política padrão self_hosted_only)."""
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://localhost:11434")

    provider = get_provider()

    assert isinstance(provider, OllamaProvider)
    assert provider.model_name == "qwen3:8b"
    assert provider is ModelRouter.get_provider("researcher")


@pytest.mark.unit
def test_get_provider_sem_singleton_de_modulo():
    import src.llm.factory as factory

    assert not hasattr(factory, "_provider_instance")


@pytest.mark.unit
def test_get_provider_respeita_o_pin_do_researcher(monkeypatch):
    monkeypatch.setenv("RESEARCHER_MODEL", "ollama/qwen3.5:4b")
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://localhost:11434")

    assert get_provider().model_name == "qwen3.5:4b"


@pytest.mark.unit
def test_alias_local_do_registro_continua_resolvendo_para_ollama():
    """O alias legado 'local' do registro continua valendo para a lista de permissão."""
    from src.llm.availability import parse_priority

    assert parse_priority("local", "default") == ("ollama",)
