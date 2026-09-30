"""Testes unitários do provedor Anthropic (ADR 011).

O SDK é substituído por um cliente simulado: nenhum teste acessa a rede nem exige chave.
As regras verificadas vêm das restrições dos modelos atuais (sem `temperature`, blocos de
pensamento devolvidos intactos, `tool_result` primeiro, recusa como erro explícito).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx2
import pytest

from src.llm import registry
from src.llm.base import LLMResponse
from src.llm.providers.anthropic import AnthropicProvider, ProviderRefusalError

MODEL = "claude-sonnet-5-5"


def _provider(**kwargs) -> AnthropicProvider:
    provider = AnthropicProvider(api_key="sk-ant-teste", model=MODEL, **kwargs)
    provider._client = MagicMock()
    provider._client.messages.create = AsyncMock()
    return provider


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _thinking(text: str = "", signature: str = "assinatura-1") -> SimpleNamespace:
    return SimpleNamespace(type="thinking", thinking=text, signature=signature)


def _tool_use(call_id: str, name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=arguments)


def _response(content: list, stop_reason: str = "end_turn", **usage) -> SimpleNamespace:
    counts = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    counts.update(usage)
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=SimpleNamespace(**counts), stop_details=None)


def _status_error(cls, status: int):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("erro simulado", response=httpx2.Response(status, request=request), body=None)


@pytest.fixture(autouse=True)
def no_real_sleep_or_telemetry(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr("src.llm.providers.anthropic.asyncio.sleep", _instant)
    emitted = MagicMock()
    monkeypatch.setattr("src.llm.providers.anthropic.emit_connection_retry", emitted)
    return emitted


@pytest.mark.unit
class TestConstruction:
    def test_missing_api_key_is_an_explicit_error(self) -> None:
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            AnthropicProvider(api_key=None, model=MODEL)

    def test_invalid_effort_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="ANTHROPIC_EFFORT"):
            AnthropicProvider(api_key="k", model=MODEL, effort="turbo")

    def test_model_name(self) -> None:
        assert _provider().model_name == MODEL

    def test_registered_in_the_provider_registry(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", "sk-ant-teste")
        monkeypatch.setattr("src.config.ANTHROPIC_BASE_URL", None)
        provider = registry.create_provider("anthropic", MODEL)
        assert isinstance(provider, AnthropicProvider)
        assert "anthropic" in registry.available_providers()

    def test_registry_without_key_fails_with_actionable_message(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", None)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            registry.create_provider("anthropic", MODEL)


@pytest.mark.unit
class TestConvertMessages:
    def test_system_messages_become_the_system_parameter(self) -> None:
        system, converted = _provider()._convert_messages(
            [{"role": "system", "content": "Você é um pesquisador."}, {"role": "user", "content": "Oi"}], None
        )
        assert system == "Você é um pesquisador."
        assert converted == [{"role": "user", "content": [{"type": "text", "text": "Oi"}]}]

    def test_system_argument_is_not_duplicated(self) -> None:
        system, _ = _provider()._convert_messages(
            [{"role": "system", "content": "Instrução"}, {"role": "user", "content": "Oi"}], "Instrução"
        )
        assert system == "Instrução"

    def test_tool_results_come_first_and_share_one_user_turn(self) -> None:
        messages = [
            {"role": "user", "content": "tarefa"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "t1", "type": "function", "function": {"name": "a", "arguments": {"x": 1}}},
                    {"id": "t2", "type": "function", "function": {"name": "b", "arguments": {}}},
                ],
            },
            {"role": "tool", "tool_call_id": "t1", "content": "r1"},
            {"role": "tool", "tool_call_id": "t2", "content": "r2"},
            {"role": "user", "content": "alerta do orquestrador"},
        ]
        _, converted = _provider()._convert_messages(messages, None)

        assert [m["role"] for m in converted] == ["user", "assistant", "user"]
        assert converted[1]["content"] == [
            {"type": "tool_use", "id": "t1", "name": "a", "input": {"x": 1}},
            {"type": "tool_use", "id": "t2", "name": "b", "input": {}},
        ]
        last = converted[2]["content"]
        assert [b["type"] for b in last] == ["tool_result", "tool_result", "text"]
        assert last[0] == {"type": "tool_result", "tool_use_id": "t1", "content": "r1"}

    def test_non_string_tool_content_is_serialized(self) -> None:
        _, converted = _provider()._convert_messages(
            [{"role": "tool", "tool_call_id": "t1", "content": {"ok": True}}], None
        )
        assert converted[0]["content"][0]["content"] == '{"ok": true}'

    def test_stored_thinking_blocks_are_replayed_unchanged(self) -> None:
        stored = [
            {"type": "thinking", "thinking": "", "signature": "assinatura-1"},
            {"type": "text", "text": "vou usar a ferramenta"},
            {"type": "tool_use", "id": "t1", "name": "a", "input": {"x": 1}},
        ]
        message = {
            "role": "assistant",
            "content": "vou usar a ferramenta",
            "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "a", "arguments": {"x": 1}}}],
            "provider_data": {"content": stored},
        }
        _, converted = _provider()._convert_messages([{"role": "user", "content": "oi"}, message], None)
        assert converted[1]["content"] == stored

    def test_stored_blocks_are_dropped_when_the_message_was_edited(self) -> None:
        message = {
            "role": "assistant",
            "content": "texto resumido pela compressão de contexto",
            "provider_data": {"content": [{"type": "thinking", "thinking": "", "signature": "s"},
                                          {"type": "text", "text": "texto original"}]},
        }
        _, converted = _provider()._convert_messages([{"role": "user", "content": "oi"}, message], None)
        assert converted[1]["content"] == [{"type": "text", "text": "texto resumido pela compressão de contexto"}]

    def test_empty_messages_are_skipped(self) -> None:
        _, converted = _provider()._convert_messages(
            [{"role": "user", "content": ""}, {"role": "assistant", "content": None}, {"role": "user", "content": "x"}],
            None,
        )
        assert converted == [{"role": "user", "content": [{"type": "text", "text": "x"}]}]


@pytest.mark.unit
class TestConvertTools:
    def test_openai_format_becomes_input_schema(self) -> None:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "write_artifact",
                    "description": "Salva um artefato",
                    "parameters": {"type": "object", "properties": {"filename": {"type": "string"}}},
                },
            }
        ]
        assert AnthropicProvider._convert_tools(tools) == [
            {
                "name": "write_artifact",
                "description": "Salva um artefato",
                "input_schema": {"type": "object", "properties": {"filename": {"type": "string"}}},
            }
        ]

    def test_tool_without_parameters_gets_an_empty_object_schema(self) -> None:
        converted = AnthropicProvider._convert_tools([{"type": "function", "function": {"name": "ping"}}])
        assert converted[0]["input_schema"] == {"type": "object", "properties": {}}


@pytest.mark.unit
@pytest.mark.asyncio
class TestRequest:
    async def test_temperature_is_never_sent(self) -> None:
        provider = _provider()
        provider._client.messages.create.return_value = _response([_text("ok")])

        await provider.generate([{"role": "user", "content": "oi"}], temperature=0.9)

        assert "temperature" not in provider._client.messages.create.call_args.kwargs

    async def test_forced_tool_choice_and_explicit_thinking_are_never_sent(self) -> None:
        provider = _provider()
        provider._client.messages.create.return_value = _response([_text("ok")])
        tools = [{"type": "function", "function": {"name": "a", "parameters": {"type": "object"}}}]

        await provider.generate([{"role": "user", "content": "oi"}], tools=tools)

        sent = provider._client.messages.create.call_args.kwargs
        assert "tool_choice" not in sent
        assert "thinking" not in sent
        assert sent["tools"][0]["name"] == "a"

    async def test_max_tokens_has_a_floor_because_thinking_consumes_it(self) -> None:
        provider = _provider()
        provider._client.messages.create.return_value = _response([_text("ok")])

        await provider.generate([{"role": "user", "content": "oi"}], max_tokens=4096)
        assert provider._client.messages.create.call_args.kwargs["max_tokens"] == 16000

        await provider.generate([{"role": "user", "content": "oi"}], max_tokens=32000)
        assert provider._client.messages.create.call_args.kwargs["max_tokens"] == 32000

    async def test_effort_and_fallback_are_sent_by_default(self) -> None:
        provider = _provider()
        provider._client.messages.create.return_value = _response([_text("ok")])

        await provider.generate([{"role": "user", "content": "oi"}])

        sent = provider._client.messages.create.call_args.kwargs
        assert sent["output_config"] == {"effort": "medium"}
        assert sent["extra_headers"] == {"anthropic-beta": "server-side-fallback-2026-07-01"}
        assert sent["extra_body"] == {"fallbacks": "default"}

    async def test_effort_and_fallback_can_be_disabled(self) -> None:
        provider = _provider(effort="", refusal_fallback=False)
        provider._client.messages.create.return_value = _response([_text("ok")])

        await provider.generate([{"role": "user", "content": "oi"}])

        sent = provider._client.messages.create.call_args.kwargs
        assert "output_config" not in sent
        assert "extra_headers" not in sent and "extra_body" not in sent


@pytest.mark.unit
@pytest.mark.asyncio
class TestModelCapabilities:
    """Modelos sem suporte rejeitam `effort` e o fallback do servidor com HTTP 400; o provedor não os envia."""

    async def _sent(self, model: str) -> dict:
        provider = AnthropicProvider(api_key="sk-ant-teste", model=model)
        provider._client = MagicMock()
        provider._client.messages.create = AsyncMock(return_value=_response([_text("ok")]))
        await provider.generate([{"role": "user", "content": "oi"}])
        return provider._client.messages.create.call_args.kwargs

    async def test_haiku_gets_neither_effort_nor_fallback(self) -> None:
        sent = await self._sent("claude-haiku-4-5")
        assert "output_config" not in sent
        assert "extra_headers" not in sent and "extra_body" not in sent

    async def test_sonnet_5_5_gets_effort_and_fallback(self) -> None:
        sent = await self._sent("claude-sonnet-5-5")
        assert sent["output_config"] == {"effort": "medium"}
        assert sent["extra_body"] == {"fallbacks": "default"}

    async def test_sonnet_4_6_gets_effort_but_not_the_fallback(self) -> None:
        sent = await self._sent("claude-sonnet-4-6")
        assert sent["output_config"] == {"effort": "medium"}
        assert "extra_body" not in sent


@pytest.mark.unit
@pytest.mark.asyncio
class TestResponse:
    async def test_text_and_usage(self) -> None:
        provider = _provider()
        provider._client.messages.create.return_value = _response(
            [_text("Olá"), _text(", mundo")], input_tokens=100, output_tokens=20,
            cache_read_input_tokens=50, cache_creation_input_tokens=10,
        )

        result = await provider.generate([{"role": "user", "content": "oi"}])

        assert result.text == "Olá, mundo"
        assert result.finish_reason == "stop"
        assert result.usage["prompt_tokens"] == 160  # entrada + leitura + escrita de cache
        assert result.usage["completion_tokens"] == 20
        assert result.usage["total_tokens"] == 180
        assert result.usage["retry_count"] == 0

    async def test_tool_use_and_thinking_blocks_are_kept_in_order(self) -> None:
        provider = _provider()
        provider._client.messages.create.return_value = _response(
            [_thinking("raciocínio", "sig-9"), _text("chamando"), _tool_use("t1", "a", {"x": 1})],
            stop_reason="tool_use",
        )

        result = await provider.generate([{"role": "user", "content": "oi"}])

        assert result.finish_reason == "tool_calls"
        assert result.tool_calls[0].id == "t1" and result.tool_calls[0].arguments == {"x": 1}
        assert result.thought == "raciocínio"
        assert result.provider_data == {
            "content": [
                {"type": "thinking", "thinking": "raciocínio", "signature": "sig-9"},
                {"type": "text", "text": "chamando"},
                {"type": "tool_use", "id": "t1", "name": "a", "input": {"x": 1}},
            ]
        }

    async def test_round_trip_replays_the_thinking_block(self) -> None:
        """A resposta com ferramenta, devolvida ao histórico, reenvia o pensamento assinado."""
        provider = _provider()
        provider._client.messages.create.return_value = _response(
            [_thinking("", "sig-9"), _tool_use("t1", "a", {"x": 1})], stop_reason="tool_use"
        )
        first = await provider.generate([{"role": "user", "content": "oi"}])

        history = [{"role": "user", "content": "oi"}, first.to_message(),
                   {"role": "tool", "tool_call_id": "t1", "content": "resultado"}]
        provider._client.messages.create.return_value = _response([_text("pronto")])
        await provider.generate(history)

        assistant = provider._client.messages.create.call_args.kwargs["messages"][1]
        assert assistant["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-9"}

    async def test_length_finish_reason(self) -> None:
        provider = _provider()
        provider._client.messages.create.return_value = _response([_text("cortado")], stop_reason="max_tokens")
        assert (await provider.generate([{"role": "user", "content": "oi"}])).finish_reason == "length"

    async def test_response_served_by_fallback_model_drops_provider_data(self) -> None:
        provider = _provider()
        provider._client.messages.create.return_value = _response(
            [SimpleNamespace(type="fallback"), _text("resposta do modelo de fallback")]
        )
        result = await provider.generate([{"role": "user", "content": "oi"}])
        assert result.text == "resposta do modelo de fallback"
        assert result.provider_data is None

    async def test_refusal_is_an_explicit_error_with_the_category(self) -> None:
        provider = _provider()
        refusal = _response([], stop_reason="refusal")
        refusal.stop_details = SimpleNamespace(category="bio", explanation="pedido bloqueado")
        provider._client.messages.create.return_value = refusal

        with pytest.raises(ProviderRefusalError) as excinfo:
            await provider.generate([{"role": "user", "content": "oi"}])

        assert excinfo.value.category == "bio"
        assert "bio" in str(excinfo.value) and MODEL in str(excinfo.value)


@pytest.mark.unit
@pytest.mark.asyncio
class TestRetry:
    async def test_retries_rate_limit_and_overload_then_succeeds(self, no_real_sleep_or_telemetry) -> None:
        provider = _provider()
        provider._client.messages.create.side_effect = [
            _status_error(anthropic.RateLimitError, 429),
            _status_error(anthropic.InternalServerError, 529),
            _response([_text("ok")]),
        ]

        result = await provider.generate([{"role": "user", "content": "oi"}])

        assert result.text == "ok"
        assert result.usage["retry_count"] == 2
        assert no_real_sleep_or_telemetry.call_count == 2
        assert no_real_sleep_or_telemetry.call_args.args[0] == "llm_provider:anthropic"

    async def test_connection_errors_are_retried(self) -> None:
        provider = _provider()
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        provider._client.messages.create.side_effect = [anthropic.APIConnectionError(request=request),
                                                       _response([_text("ok")])]
        assert (await provider.generate([{"role": "user", "content": "oi"}])).usage["retry_count"] == 1

    async def test_client_errors_are_not_retried(self) -> None:
        provider = _provider()
        provider._client.messages.create.side_effect = _status_error(anthropic.BadRequestError, 400)

        with pytest.raises(anthropic.BadRequestError):
            await provider.generate([{"role": "user", "content": "oi"}])

        assert provider._client.messages.create.call_count == 1

    async def test_gives_up_after_the_retry_budget(self) -> None:
        provider = _provider()
        provider._client.messages.create.side_effect = _status_error(anthropic.InternalServerError, 500)

        with pytest.raises(anthropic.InternalServerError):
            await provider.generate([{"role": "user", "content": "oi"}])

        assert provider._client.messages.create.call_count == 4  # tentativa inicial + 3


@pytest.mark.unit
@pytest.mark.asyncio
class TestHealthAndStream:
    async def test_health_check_true_and_false(self) -> None:
        provider = _provider()
        provider._client.with_options.return_value.models.retrieve = AsyncMock(return_value=SimpleNamespace(id=MODEL))
        assert await provider.health_check() is True

        provider._client.with_options.return_value.models.retrieve = AsyncMock(side_effect=RuntimeError("sem rede"))
        assert await provider.health_check() is False

    async def test_generate_stream_yields_text_chunks(self) -> None:
        provider = _provider()

        async def text_stream():
            for chunk in ("Olá", ", ", "mundo"):
                yield chunk

        stream = MagicMock()
        stream.text_stream = text_stream()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=stream)
        context.__aexit__ = AsyncMock(return_value=False)
        provider._client.messages.stream = MagicMock(return_value=context)

        chunks = [c async for c in provider.generate_stream([{"role": "user", "content": "oi"}])]

        assert "".join(chunks) == "Olá, mundo"
        assert "temperature" not in provider._client.messages.stream.call_args.kwargs


@pytest.mark.unit
def test_llm_response_serializes_provider_data_only_when_present() -> None:
    assert "provider_data" not in LLMResponse(text="oi").to_message()
    assert LLMResponse(text="oi", provider_data={"content": [1]}).to_message()["provider_data"] == {"content": [1]}
