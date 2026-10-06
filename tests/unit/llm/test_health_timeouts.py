"""Os timeouts dos health checks vêm de LLM_HEALTH_CHECK_TIMEOUT_SECONDS (sem 5.0 fixo nos provedores)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _response(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "http://x"))


async def test_ollama_usa_o_timeout_configurado(monkeypatch):
    from src.llm.providers.ollama import OllamaProvider

    monkeypatch.setattr("src.config.LLM_HEALTH_CHECK_TIMEOUT_SECONDS", 2.5)
    provider = OllamaProvider(base_url="http://localhost:11434", model="qwen3:8b")
    provider._client = MagicMock(get=AsyncMock(return_value=_response({"models": [{"name": "qwen3:8b"}]})))

    assert await provider.check_availability() is None
    assert await provider.health_check() is True

    assert [c.kwargs["timeout"] for c in provider._client.get.call_args_list] == [2.5, 2.5]


async def test_openai_compatible_usa_o_timeout_configurado(monkeypatch):
    from src.llm.providers.openai_compatible import OpenAICompatibleProvider

    monkeypatch.setattr("src.config.LLM_HEALTH_CHECK_TIMEOUT_SECONDS", 7)
    provider = OpenAICompatibleProvider(base_url="http://localhost:8000/v1", model="m")
    provider._client = MagicMock(get=AsyncMock(return_value=_response({"data": [{"id": "m"}]})))

    assert await provider.check_availability() is None
    assert await provider.health_check() is True

    assert [c.kwargs["timeout"] for c in provider._client.get.call_args_list] == [7, 7]


async def test_anthropic_usa_o_timeout_configurado(monkeypatch):
    pytest.importorskip("anthropic")
    from src.llm.providers.anthropic import AnthropicProvider

    monkeypatch.setattr("src.config.LLM_HEALTH_CHECK_TIMEOUT_SECONDS", 3)
    provider = AnthropicProvider(api_key="k", model="claude-sonnet-5-5")
    retrieve = AsyncMock()
    options = MagicMock()
    options.models.retrieve = retrieve
    provider._client = MagicMock()
    provider._client.with_options.return_value = options

    assert await provider.check_availability() is None
    assert await provider.health_check() is True

    assert [c.kwargs["timeout"] for c in provider._client.with_options.call_args_list] == [3, 3]
