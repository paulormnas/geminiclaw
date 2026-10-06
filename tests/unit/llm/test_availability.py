"""Cenários do requisito "Disponibilidade sem geração de texto" (v16-model-catalog-router)."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.llm import availability
from src.llm.availability import Availability, compute_availability, parse_priority, sanitize_error
from src.llm.base import LLMProvider
from tests.support.catalog_fixtures import load

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

CHAVE = "chave-secreta-de-teste-123"


class _FakeProvider(LLMProvider):
    """Provedor cujo check_availability devolve/levanta o que o teste configura."""

    def __init__(self, outcome=None):
        self.outcome = outcome

    async def check_availability(self):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    async def generate(self, messages, tools=None, system=None, temperature=0.7, max_tokens=4096):
        raise AssertionError("health check não pode gerar texto")

    async def generate_stream(self, messages, system=None):
        raise AssertionError("health check não pode gerar texto")

    async def health_check(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return "fake"


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setattr("src.config.GEMINI_API_KEY", CHAVE)
    monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", CHAVE)
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://ollama.local:11434")


async def test_modelo_ollama_nao_instalado(tmp_path, credentials):
    """Cenário: Modelo Ollama não instalado (servidor responde em /api/tags sem o modelo)."""
    from src.llm.providers.ollama import OllamaProvider

    catalog = load(tmp_path)
    provider = OllamaProvider(base_url="http://ollama.local:11434", model="qwen3:8b")
    provider._client = SimpleNamespace(
        get=AsyncMock(
            return_value=httpx.Response(
                200, json={"models": [{"name": "llama3:8b"}]}, request=httpx.Request("GET", "http://x/api/tags")
            )
        )
    )

    result = await compute_availability(
        catalog,
        ["ollama/qwen3:8b"],
        priority=("ollama",),
        timeout=1,
        provider_factory=lambda p, m: provider,
    )

    assert result["ollama/qwen3:8b"] == Availability(False, "modelo_nao_instalado")


async def test_modelo_ollama_instalado(tmp_path, credentials):
    from src.llm.providers.ollama import OllamaProvider

    catalog = load(tmp_path)
    provider = OllamaProvider(base_url="http://ollama.local:11434", model="qwen3:8b")
    provider._client = SimpleNamespace(
        get=AsyncMock(
            return_value=httpx.Response(
                200, json={"models": [{"name": "qwen3:8b"}]}, request=httpx.Request("GET", "http://x/api/tags")
            )
        )
    )

    result = await compute_availability(
        catalog, ["ollama/qwen3:8b"], priority=("ollama",), timeout=1, provider_factory=lambda p, m: provider
    )

    assert result["ollama/qwen3:8b"].ok is True


async def test_provedor_fora_da_lista_de_permissao(tmp_path, credentials):
    """Cenário: Provedor fora da lista de permissão (nenhum anthropic/* disponível)."""
    catalog = load(tmp_path)
    priority = parse_priority("ollama,google", "default")

    result = await compute_availability(
        catalog,
        None,
        priority=priority,
        timeout=1,
        provider_factory=lambda p, m: _FakeProvider(None),
    )

    assert result["anthropic/claude-sonnet-5-5"] == Availability(False, availability.MOTIVO_FORA_DA_LISTA)
    assert result["google/gemini-3.8-flash"].ok is True
    assert result["ollama/qwen3:8b"].ok is True


async def test_sem_credencial_e_sem_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.GEMINI_API_KEY", None)
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "")
    catalog = load(tmp_path)

    result = await compute_availability(
        catalog, None, priority=parse_priority("", "default"), timeout=1,
        provider_factory=lambda p, m: _FakeProvider(None),
    )

    assert result["google/gemini-3.8-flash"].motivo == availability.MOTIVO_SEM_CREDENCIAL
    assert result["ollama/qwen3:8b"].motivo == availability.MOTIVO_SEM_ENDPOINT


async def test_health_check_do_google_sem_geracao():
    """Cenário: Health check do Google sem geração (nenhuma chamada a generate_content)."""
    from src.llm.providers.google import GoogleProvider

    with patch("src.llm.providers.google.genai.Client") as client_cls:
        client = MagicMock()
        client.aio.models.get = AsyncMock(return_value=object())
        client.aio.models.generate_content = AsyncMock()
        client_cls.return_value = client
        provider = GoogleProvider(api_key="k", model="gemini-3.8-flash")

    assert await provider.check_availability() is None
    assert await provider.health_check() is True

    client.aio.models.generate_content.assert_not_called()
    client.aio.models.get.assert_awaited_with(model="gemini-3.8-flash")


async def test_erro_sanitizado(tmp_path, credentials, caplog):
    """Cenário: Erro sanitizado (o corpo da resposta com a chave não chega ao log nem ao motivo)."""
    request = httpx.Request("GET", f"https://api.exemplo.com/models?key={CHAVE}", headers={"x-api-key": CHAVE})
    response = httpx.Response(401, text=f'{{"error": "chave {CHAVE} inválida"}}', request=request)
    error = httpx.HTTPStatusError(f"401 em {request.url} corpo {response.text}", request=request, response=response)
    catalog = load(tmp_path)

    with caplog.at_level(logging.DEBUG):
        result = await compute_availability(
            catalog,
            ["google/gemini-3.8-flash"],
            priority=("google",),
            timeout=1,
            provider_factory=lambda p, m: _FakeProvider(error),
        )

    assert result["google/gemini-3.8-flash"].motivo == "health_check_falhou:HTTPStatusError:401"
    everything = " ".join(r.getMessage() + str(r.__dict__) for r in caplog.records)
    assert CHAVE not in everything
    assert "HTTPStatusError" in everything and "401" in everything
    assert sanitize_error(error) == "HTTPStatusError:401"
    assert sanitize_error(ValueError(CHAVE)) == "ValueError"


async def test_timeout_do_health_check(tmp_path, credentials):
    import asyncio

    class _Slow(_FakeProvider):
        async def check_availability(self):
            await asyncio.sleep(5)

    catalog = load(tmp_path)

    result = await compute_availability(
        catalog, ["google/gemini-3.8-flash"], priority=("google",), timeout=0.01,
        provider_factory=lambda p, m: _Slow(),
    )

    assert result["google/gemini-3.8-flash"].motivo.startswith("health_check_timeout")


async def test_checks_em_paralelo_e_um_por_modelo(tmp_path, credentials):
    catalog = load(tmp_path)
    calls = []

    def factory(provider, model):
        calls.append((provider, model))
        return _FakeProvider(None)

    await compute_availability(
        catalog, None, priority=parse_priority("", "default"), timeout=1, provider_factory=factory
    )

    assert sorted(calls) == [
        ("anthropic", "claude-sonnet-5-5"),
        ("google", "gemini-3.8-flash"),
        ("ollama", "qwen3:8b"),
    ]


async def test_lista_de_permissao_padrao_por_perfil():
    assert parse_priority("", "pi5")[0] == "ollama"
    assert parse_priority("", "default")[0] == "google"
    assert parse_priority("local, google", "default") == ("ollama", "google")
