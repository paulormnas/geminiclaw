"""Testes unitários para o registro único de provedores (src.llm.registry, V16)."""

import pytest

from src import config
from src.llm import registry
from src.llm.base import LLMProvider, LLMResponse


class _FakeProvider(LLMProvider):
    """Provedor fictício usado apenas nestes testes."""

    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None):
        self._model = model
        self.base_url = base_url
        self.api_key = api_key

    async def generate(self, messages, tools=None, system=None, temperature=0.7, max_tokens=4096):
        return LLMResponse(text="ok")

    async def generate_stream(self, messages, system=None):
        yield "ok"

    async def health_check(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return self._model


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Isola o registro global para cada teste, sem afetar os provedores reais."""
    monkeypatch.setattr(registry, "_registry", {})
    monkeypatch.setattr(registry, "_aliases", {})
    yield


@pytest.mark.unit
def test_register_and_create_provider():
    registry.register_provider("fake", lambda settings: _FakeProvider(settings.model))

    provider = registry.create_provider("fake", "fake-model-1")

    assert isinstance(provider, _FakeProvider)
    assert provider.model_name == "fake-model-1"


@pytest.mark.unit
def test_alias_resolves_to_canonical_provider():
    registry.register_provider(
        "fake", lambda settings: _FakeProvider(settings.model), aliases=("legacy_fake",)
    )

    provider = registry.create_provider("legacy_fake", "fake-model-2")

    assert isinstance(provider, _FakeProvider)


@pytest.mark.unit
def test_unknown_provider_raises_value_error_listing_available():
    registry.register_provider("fake_a", lambda settings: _FakeProvider(settings.model))
    registry.register_provider("fake_b", lambda settings: _FakeProvider(settings.model))

    with pytest.raises(ValueError) as exc_info:
        registry.create_provider("inexistente", "any-model")

    msg = str(exc_info.value)
    assert "inexistente" in msg
    assert "fake_a" in msg
    assert "fake_b" in msg


@pytest.mark.unit
def test_provider_with_missing_optional_dependency_raises_value_error():
    """Simula uma fábrica cujo pacote opcional não está instalado (padrão do provedor google)."""

    def _factory(settings):
        raise ValueError(
            "Provedor 'fake_optional' requer o pacote 'fake-sdk'. Instale com: uv sync --extra fake"
        )

    registry.register_provider("fake_optional", _factory)

    with pytest.raises(ValueError, match="uv sync --extra fake"):
        registry.create_provider("fake_optional", "any-model")


@pytest.mark.unit
def test_settings_resolve_base_url_and_api_key_from_config(monkeypatch):
    """`create_provider` lê `base_url`/`api_key` de `src.config`, não do ambiente bruto."""
    monkeypatch.setattr(config, "FAKE_BASE_URL", "http://fake:1234", raising=False)
    monkeypatch.setattr(config, "FAKE_API_KEY", "fake-secret", raising=False)

    captured = {}

    def _factory(settings):
        captured["settings"] = settings
        return _FakeProvider(settings.model)

    registry.register_provider("fake", _factory)
    registry.create_provider("fake", "fake-model")

    assert captured["settings"].base_url == "http://fake:1234"
    assert captured["settings"].api_key == "fake-secret"


@pytest.mark.unit
def test_unresolved_config_var_defaults_to_none():
    """Um provedor sem constante declarada em `config.py` resolve para `None`, não erro."""
    captured = {}

    def _factory(settings):
        captured["settings"] = settings
        return _FakeProvider(settings.model)

    registry.register_provider("no_config_yet", _factory)
    registry.create_provider("no_config_yet", "fake-model")

    assert captured["settings"].base_url is None
    assert captured["settings"].api_key is None


@pytest.mark.unit
def test_api_key_never_in_repr():
    settings = registry.ProviderSettings(name="fake", model="m", base_url=None, api_key="super-secret")
    assert "super-secret" not in repr(settings)
