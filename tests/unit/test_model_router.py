"""Testes do ModelRouter sobre o mapa resolvido da sessão (ADR 017; Roadmap V14.1/V16)."""

from unittest.mock import patch

import pytest

from src.llm import registry
from src.llm.base import LLMProvider, LLMResponse
from src.llm.providers.ollama import OllamaProvider
from src.llm.session import bind_session_routing, build_session_routing
from src.model_config import get_role_model_config
from src.model_router import ModelRouter
from tests.support.catalog_fixtures import model, write_yaml


@pytest.fixture(autouse=True)
def clean_router_cache():
    """Garante cache limpo antes e após cada teste."""
    ModelRouter.clear_cache()
    yield
    ModelRouter.clear_cache()


@pytest.fixture
def nuvem_liberada(monkeypatch):
    """third_party_allowed com chave do Google e sem chave da Anthropic."""
    monkeypatch.setattr("src.config.LLM_DATA_POLICY", "third_party_allowed")
    monkeypatch.setattr("src.config.GEMINI_API_KEY", "dummy_key")
    monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", None)


@pytest.mark.unit
def test_model_router_default_roles_sob_a_politica_padrao(monkeypatch):
    """Sem política explícita (self_hosted_only) todos os papéis caem no Ollama do catálogo."""
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://localhost:11434")

    for role in ("researcher", "validator", "developer", "base", "summarizer", "reviewer", "curator"):
        cfg = get_role_model_config(role)
        assert cfg.provider == "ollama", role
        assert cfg.model == "qwen3:8b", role

    provider = ModelRouter.get_provider("validator")
    assert isinstance(provider.inner, OllamaProvider)
    assert provider.model_name == "qwen3:8b"


@pytest.mark.unit
def test_model_router_com_nuvem_liberada(nuvem_liberada):
    """Com third_party_allowed e só a chave do Google, researcher e developer vão ao Gemini."""
    pytest.importorskip("google.genai")
    from src.llm.providers.google import GoogleProvider

    assert get_role_model_config("researcher").provider == "google"
    researcher = ModelRouter.get_provider("researcher")
    assert isinstance(researcher.inner, GoogleProvider)
    assert researcher.model_name == "gemini-3.8-flash"
    assert isinstance(ModelRouter.get_provider("developer").inner, GoogleProvider)
    # O Validator cai no Ollama: o Claude não tem chave.
    assert get_role_model_config("validator").provider == "ollama"


@pytest.mark.unit
def test_model_router_pin_por_variavel_de_ambiente(monkeypatch):
    """`{PAPEL}_MODEL=provedor/modelo` sobrescreve a preferência do catálogo."""
    monkeypatch.setenv("VALIDATOR_MODEL", "ollama/qwen3.5:4b")
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://localhost:11434")

    cfg = get_role_model_config("validator")
    assert (cfg.provider, cfg.model) == ("ollama", "qwen3.5:4b")

    provider = ModelRouter.get_provider("validator")
    assert isinstance(provider.inner, OllamaProvider)
    assert provider.model_name == "qwen3.5:4b"


@pytest.mark.unit
def test_model_router_papel_invalido_levanta_value_error():
    """Solicitação de papel inexistente deve levantar ValueError claro."""
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
def test_planner_e_alias_de_researcher():
    assert get_role_model_config("planner") == get_role_model_config("researcher")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sem_papel_delega_para_o_researcher_do_mapa_da_sessao(monkeypatch):
    """Cenário: Sem papel (get_provider() dentro da sessão devolve a instância do researcher)."""
    monkeypatch.setenv("RESEARCHER_MODEL", "ollama/qwen3.5:4b")
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://localhost:11434")
    bind_session_routing(await build_session_routing())

    sem_papel = ModelRouter.get_provider()

    assert sem_papel is ModelRouter.get_provider("researcher")
    assert sem_papel.model_name == "qwen3.5:4b"


@pytest.mark.unit
def test_get_provider_da_factory_nao_tem_singleton_e_vai_ao_roteador():
    from src.llm.factory import get_provider

    assert get_provider() is ModelRouter.get_provider("researcher")


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
def test_model_router_usa_provedor_registrado_sem_editar_o_roteador(monkeypatch, tmp_path):
    """Um provedor registrado só em teste (via catálogo local) é resolvido sem editar o roteador."""
    registry.register_provider("fake", lambda settings: _FakeProvider(settings.model))
    local = write_yaml(tmp_path / "local.yaml", {"modelos": [model("fake/fake-model", "self_hosted")]})
    monkeypatch.setattr("src.config.LLM_CATALOG_LOCAL_PATH", str(local))
    monkeypatch.setattr("src.config.LLM_PROVIDER_PRIORITY", "ollama,fake")
    monkeypatch.setenv("VALIDATOR_MODEL", "fake/fake-model")

    provider = ModelRouter.get_provider("validator")

    assert isinstance(provider.inner, _FakeProvider)
    assert provider.model_name == "fake-model"


@pytest.mark.unit
def test_model_router_dica_invalida_usa_o_modelo_resolvido(monkeypatch):
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://localhost:11434")

    with patch("src.llm.routing.logger.warning") as warn:
        provider = ModelRouter.get_provider("developer", model="qwen3:8b")

    assert provider.model_name == "qwen3:8b"
    assert warn.called


@pytest.mark.unit
def test_model_router_dica_valida_troca_o_modelo(monkeypatch):
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://localhost:11434")

    provider = ModelRouter.get_provider("developer", model="ollama/qwen3.5:4b")

    assert provider.model_name == "qwen3.5:4b"
