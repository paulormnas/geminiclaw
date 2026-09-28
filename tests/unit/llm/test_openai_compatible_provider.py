"""Testes unitários para o provedor openai_compatible (V16)."""

import json

import httpx
import pytest
import respx

from src.llm.providers.openai_compatible import OpenAICompatibleProvider

BASE_URL = "http://test-server:8000/v1"
MODEL = "llama-3.1-8b"


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Evita esperar o backoff real durante os testes de retentativa."""
    async def _instant_sleep(_seconds):
        return None

    monkeypatch.setattr("src.llm.providers.openai_compatible.asyncio.sleep", _instant_sleep)


@pytest.mark.asyncio
async def test_generate_simple_text():
    provider = OpenAICompatibleProvider(base_url=BASE_URL, model=MODEL, api_key="secret-key")

    payload = {
        "choices": [{"message": {"role": "assistant", "content": "Olá!"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }

    async with respx.mock:
        route = respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=payload)
        )
        response = await provider.generate(messages=[{"role": "user", "content": "Oi"}])

        assert route.calls.last.request.headers["Authorization"] == "Bearer secret-key"
        assert response.text == "Olá!"
        assert response.finish_reason == "stop"
        assert response.usage == {
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 8,
            "ttft_ms": None,
            "retry_count": 0,
        }


@pytest.mark.asyncio
async def test_generate_with_tool_call():
    provider = OpenAICompatibleProvider(base_url=BASE_URL, model=MODEL)

    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "function": {
                                "name": "get_weather",
                                "arguments": json.dumps({"location": "São Paulo"}),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    async with respx.mock:
        respx.post(f"{BASE_URL}/chat/completions").mock(return_value=httpx.Response(200, json=payload))
        response = await provider.generate(
            messages=[{"role": "user", "content": "Tempo em SP"}],
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
        )

    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_abc"
    assert response.tool_calls[0].name == "get_weather"
    assert response.tool_calls[0].arguments == {"location": "São Paulo"}


@pytest.mark.asyncio
async def test_generate_with_invalid_tool_call_arguments():
    provider = OpenAICompatibleProvider(base_url=BASE_URL, model=MODEL)

    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_bad",
                            "function": {"name": "get_weather", "arguments": "{not valid json"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }

    async with respx.mock:
        respx.post(f"{BASE_URL}/chat/completions").mock(return_value=httpx.Response(200, json=payload))
        response = await provider.generate(messages=[{"role": "user", "content": "Tempo em SP"}])

    assert response.tool_calls[0].arguments == {"_raw": "{not valid json"}


@pytest.mark.asyncio
async def test_generate_retries_on_rate_limit_then_succeeds():
    provider = OpenAICompatibleProvider(base_url=BASE_URL, model=MODEL)

    success_payload = {
        "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    async with respx.mock:
        route = respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=[
                httpx.Response(429, json={"error": "rate limited"}),
                httpx.Response(200, json=success_payload),
            ]
        )
        response = await provider.generate(messages=[{"role": "user", "content": "Oi"}])

    assert route.call_count == 2
    assert response.text == "ok"
    assert response.usage["retry_count"] == 1


@pytest.mark.asyncio
async def test_generate_gives_up_after_exhausting_retries():
    provider = OpenAICompatibleProvider(base_url=BASE_URL, model=MODEL)

    async with respx.mock:
        route = respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(503, json={"error": "unavailable"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await provider.generate(messages=[{"role": "user", "content": "Oi"}])

    # 1 tentativa inicial + 3 retentativas = 4 chamadas no total.
    assert route.call_count == 4


@pytest.mark.asyncio
async def test_generate_stream_yields_text_chunks():
    provider = OpenAICompatibleProvider(base_url=BASE_URL, model=MODEL)

    sse_body = (
        'data: {"choices": [{"delta": {"content": "Ol"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "á!"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    async with respx.mock:
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(
                200, content=sse_body, headers={"content-type": "text/event-stream"}
            )
        )
        chunks = [chunk async for chunk in provider.generate_stream(messages=[{"role": "user", "content": "Oi"}])]

    assert chunks == ["Ol", "á!"]


@pytest.mark.asyncio
async def test_health_check_true_when_models_endpoint_ok():
    provider = OpenAICompatibleProvider(base_url=BASE_URL, model=MODEL)

    async with respx.mock:
        respx.get(f"{BASE_URL}/models").mock(return_value=httpx.Response(200, json={"data": []}))
        assert await provider.health_check() is True


@pytest.mark.asyncio
async def test_health_check_false_on_error():
    provider = OpenAICompatibleProvider(base_url=BASE_URL, model=MODEL)

    async with respx.mock:
        respx.get(f"{BASE_URL}/models").mock(return_value=httpx.Response(500))
        assert await provider.health_check() is False


def test_missing_base_url_raises_value_error():
    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        OpenAICompatibleProvider(base_url=None, model=MODEL)
