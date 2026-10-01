"""Testes unitários do provedor Google (Gemini 3.x).

O SDK é substituído por um cliente simulado: nenhum teste acessa a rede nem exige chave. As regras
vêm de erros reais da API: papel ``function`` recusado, ``thought_signature`` obrigatória nas
chamadas de ferramenta e chamada síncrona congelando o event loop.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types as genai_types

from src.llm import registry
from src.llm.providers.google import GoogleProvider

MODEL = "gemini-3.8-flash"
FALLBACK = "gemini-3.7-flash"


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr("src.llm.providers.google.asyncio.sleep", _instant)
    monkeypatch.setattr("src.llm.providers.google.emit_connection_retry", MagicMock())


def _provider(fallback: str | None = FALLBACK) -> GoogleProvider:
    with patch("src.llm.providers.google.genai.Client") as client_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock()
        client_cls.return_value = client
        provider = GoogleProvider(api_key="chave-de-teste", model=MODEL, fallback_model=fallback)
    return provider


def _response(parts, finish_reason="STOP", prompt=10, candidates=5, thoughts=0):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts), finish_reason=finish_reason)],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt,
            candidates_token_count=candidates,
            thoughts_token_count=thoughts,
            total_token_count=prompt + candidates + thoughts,
        ),
    )


def _text(text: str, signature: bytes | None = None) -> genai_types.Part:
    return genai_types.Part(text=text, thought_signature=signature)


def _call(name: str, args: dict, signature: bytes | None = None) -> genai_types.Part:
    return genai_types.Part(function_call=genai_types.FunctionCall(name=name, args=args), thought_signature=signature)


def _sent_contents(provider: GoogleProvider):
    return provider._client.aio.models.generate_content.call_args.kwargs["contents"]


@pytest.mark.unit
@pytest.mark.asyncio
class TestToolResultRole:
    async def test_tool_results_are_sent_as_a_user_turn(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.return_value = _response([_text("pronto")])
        messages = [
            {"role": "user", "content": "some 2+3"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "soma", "type": "function", "function": {"name": "soma", "arguments": {"a": 2, "b": 3}}}]},
            {"role": "tool", "tool_call_id": "soma", "name": "soma", "content": "5"},
        ]

        await provider.generate(messages)

        contents = _sent_contents(provider)
        assert [c.role for c in contents] == ["user", "model", "user"]
        response = contents[2].parts[0].function_response
        assert response.name == "soma" and response.response == {"result": "5"}

    async def test_parallel_tool_results_share_one_turn_and_merge_with_following_text(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.return_value = _response([_text("ok")])
        messages = [
            {"role": "user", "content": "duas contas"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "a", "arguments": {}}},
                {"id": "b", "type": "function", "function": {"name": "b", "arguments": {}}}]},
            {"role": "tool", "tool_call_id": "a", "name": "a", "content": "1"},
            {"role": "tool", "tool_call_id": "b", "name": "b", "content": "2"},
            {"role": "user", "content": "alerta do orquestrador"},
        ]

        await provider.generate(messages)

        contents = _sent_contents(provider)
        assert [c.role for c in contents] == ["user", "model", "user"]
        assert [p.function_response.name for p in contents[2].parts[:2]] == ["a", "b"]
        assert contents[2].parts[2].text == "alerta do orquestrador"

    async def test_tool_name_falls_back_to_the_call_id(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.return_value = _response([_text("ok")])

        await provider.generate([{"role": "tool", "tool_call_id": "soma", "content": "5"}])

        assert _sent_contents(provider)[0].parts[0].function_response.name == "soma"

    async def test_system_messages_stay_out_of_the_history(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.return_value = _response([_text("ok")])

        await provider.generate([{"role": "system", "content": "instrução"}, {"role": "user", "content": "oi"}],
                                system="instrução")

        assert [c.role for c in _sent_contents(provider)] == ["user"]
        assert provider._client.aio.models.generate_content.call_args.kwargs["config"].system_instruction == "instrução"

    async def test_low_max_tokens_gets_a_floor_for_thinking(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.return_value = _response([_text("ok")])

        await provider.generate([{"role": "user", "content": "oi"}], max_tokens=10)
        assert provider._client.aio.models.generate_content.call_args.kwargs["config"].max_output_tokens == 8192

        await provider.generate([{"role": "user", "content": "oi"}], max_tokens=20000)
        assert provider._client.aio.models.generate_content.call_args.kwargs["config"].max_output_tokens == 20000


@pytest.mark.unit
@pytest.mark.asyncio
class TestThoughtSignature:
    async def test_signature_is_stored_and_replayed_on_the_next_call(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.return_value = _response(
            [_call("soma", {"a": 2, "b": 3}, signature=b"assinatura-binaria")]
        )
        first = await provider.generate([{"role": "user", "content": "some"}])
        assert first.tool_calls[0].name == "soma"
        assert first.provider_data["parts"][0]["thought_signature"] is not None  # base64, serializável

        history = [{"role": "user", "content": "some"}, first.to_message(),
                   {"role": "tool", "tool_call_id": "soma", "name": "soma", "content": "5"}]
        provider._client.aio.models.generate_content.return_value = _response([_text("5")])
        await provider.generate(history)

        replayed = _sent_contents(provider)[1].parts[0]
        assert replayed.function_call.name == "soma"
        assert replayed.thought_signature == b"assinatura-binaria"

    async def test_edited_message_drops_the_stored_signature(self) -> None:
        provider = _provider()
        message = {
            "role": "assistant",
            "content": "resumo da compressão de contexto",
            "provider_data": {"parts": [{"type": "text", "text": "texto original", "thought_signature": "YXNz"}]},
        }
        provider._client.aio.models.generate_content.return_value = _response([_text("ok")])

        await provider.generate([{"role": "user", "content": "oi"}, message])

        part = _sent_contents(provider)[1].parts[0]
        assert part.text == "resumo da compressão de contexto"
        assert part.thought_signature is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestResponse:
    async def test_uses_the_async_client(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.return_value = _response([_text("ok")])

        await provider.generate([{"role": "user", "content": "oi"}])

        provider._client.aio.models.generate_content.assert_awaited_once()
        provider._client.models.generate_content.assert_not_called()

    async def test_thinking_tokens_count_as_output(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.return_value = _response(
            [_text("ok")], prompt=100, candidates=20, thoughts=300
        )

        result = await provider.generate([{"role": "user", "content": "oi"}])

        assert result.usage["prompt_tokens"] == 100
        assert result.usage["completion_tokens"] == 320
        assert result.usage["total_tokens"] == 420

    async def test_text_tool_calls_and_finish_reason(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.return_value = _response(
            [_text("vou somar"), _call("soma", {"a": 1, "b": 2})]
        )
        result = await provider.generate([{"role": "user", "content": "oi"}])
        assert result.text == "vou somar"
        assert result.finish_reason == "tool_calls"
        assert result.tool_calls[0].arguments == {"a": 1, "b": 2}

        provider._client.aio.models.generate_content.return_value = _response(
            [_text("cortado")], finish_reason="FinishReason.MAX_TOKENS"
        )
        assert (await provider.generate([{"role": "user", "content": "oi"}])).finish_reason == "length"

    async def test_thought_parts_are_kept_out_of_the_text(self) -> None:
        provider = _provider()
        thought = genai_types.Part(text="raciocínio interno", thought=True)
        provider._client.aio.models.generate_content.return_value = _response([thought, _text("resposta")])

        result = await provider.generate([{"role": "user", "content": "oi"}])

        assert result.text == "resposta"
        assert result.thought == "raciocínio interno"


@pytest.mark.unit
@pytest.mark.asyncio
class TestRateLimitFallback:
    RATE_LIMIT = Exception("429 RESOURCE_EXHAUSTED. Quota exceeded")

    async def test_falls_back_to_the_secondary_model_on_429(self) -> None:
        provider = _provider()
        calls = provider._client.aio.models.generate_content
        calls.side_effect = [self.RATE_LIMIT] * 4 + [_response([_text("via fallback")])]

        result = await provider.generate([{"role": "user", "content": "oi"}])

        assert result.text == "via fallback"
        assert [c.kwargs["model"] for c in calls.call_args_list] == [MODEL] * 4 + [FALLBACK]
        assert provider.model_name == FALLBACK

    async def test_fallback_stays_active_for_the_following_calls(self) -> None:
        provider = _provider()
        calls = provider._client.aio.models.generate_content
        calls.side_effect = [self.RATE_LIMIT] * 4 + [_response([_text("1")]), _response([_text("2")])]

        await provider.generate([{"role": "user", "content": "oi"}])
        await provider.generate([{"role": "user", "content": "oi"}])

        assert calls.call_args_list[-1].kwargs["model"] == FALLBACK
        assert calls.call_count == 6  # a segunda chamada não repetiu as 4 tentativas no modelo principal

    async def test_other_errors_do_not_trigger_the_fallback(self) -> None:
        provider = _provider()
        provider._client.aio.models.generate_content.side_effect = ValueError("400 INVALID_ARGUMENT")

        with pytest.raises(ValueError):
            await provider.generate([{"role": "user", "content": "oi"}])

        assert provider._client.aio.models.generate_content.call_count == 1

    async def test_without_fallback_the_429_is_raised(self) -> None:
        provider = _provider(fallback=None)
        provider._client.aio.models.generate_content.side_effect = self.RATE_LIMIT

        with pytest.raises(Exception, match="429"):
            await provider.generate([{"role": "user", "content": "oi"}])

    async def test_fallback_equal_to_the_main_model_is_ignored(self) -> None:
        assert _provider(fallback=MODEL)._fallback_model is None


@pytest.mark.unit
def test_registry_passes_the_configured_fallback(monkeypatch) -> None:
    monkeypatch.setattr("src.config.GOOGLE_FALLBACK_MODEL", FALLBACK)
    with patch("src.llm.providers.google.genai.Client"):
        provider = registry.create_provider("google", MODEL)
    assert provider._fallback_model == FALLBACK
