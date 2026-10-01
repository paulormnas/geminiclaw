"""Testes do provedor OpenAI, da tabela de preços e do registro de chamadas LLM."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm import pricing
from src.llm.base import LLMResponse
from src.llm.providers.openai import OpenAIProvider
from src.llm.registry import create_provider

pytestmark = pytest.mark.unit


class TestOpenAIProvider:
    def _provider(self):
        return OpenAIProvider(api_key="sk-test", model="gpt-6-luna")

    def test_requires_key(self):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAIProvider(api_key=None, model="gpt-6-luna")

    def test_default_base_url(self):
        assert self._provider()._base_url == "https://api.openai.com/v1"

    def test_payload_uses_max_completion_tokens_and_no_temperature(self):
        payload = self._provider()._build_payload([{"role": "user", "content": "oi"}], None, "sys", 0.7, 100)
        assert "temperature" not in payload and "max_tokens" not in payload
        assert payload["max_completion_tokens"] >= 8192
        assert payload["messages"][0] == {"role": "system", "content": "sys"}

    def test_history_is_normalized_to_strict_schema(self):
        history = [
            {"role": "user", "content": "x"},
            {"role": "assistant", "thought": "t", "provider_data": {"a": 1},
             "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": {"k": "ç"}}}]},
            {"role": "tool", "tool_call_id": "c1", "name": "f", "content": {"ok": True}},
        ]
        out = self._provider()._build_messages(history, None)
        assert out[1] == {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "f", "arguments": '{"k": "ç"}'}}]}
        assert out[2] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'}

    def test_usage_reports_cached_and_reasoning(self):
        provider = self._provider()
        data = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                          "prompt_tokens_details": {"cached_tokens": 4},
                          "completion_tokens_details": {"reasoning_tokens": 3}}}

        async def fake_post(path, payload):
            return data, 0

        provider._post_with_retry = fake_post
        resp = asyncio.run(provider.generate([{"role": "user", "content": "oi"}]))
        assert resp.usage["cached_tokens"] == 4 and resp.usage["reasoning_tokens"] == 3

    def test_registry_creates_openai(self):
        with patch("src.config.OPENAI_API_KEY", "sk-x"), patch("src.config.OPENAI_BASE_URL", None):
            assert isinstance(create_provider("openai", "gpt-6-luna"), OpenAIProvider)


class TestPricing:
    def test_known_model(self):
        # 1M entrada + 1M saída do Sonnet 5.5 = 2 + 10
        assert pricing.estimate_cost("anthropic", "claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.0)

    def test_cached_tokens_use_cache_rate(self):
        cost = pricing.estimate_cost("anthropic", "claude-sonnet-5-5", 1_000_000, 0, cached_tokens=1_000_000)
        assert cost == pytest.approx(0.20)

    def test_openai_without_cache_price_uses_input_rate(self):
        assert pricing.estimate_cost("openai", "gpt-6-luna", 1_000_000, 0, cached_tokens=500_000) == pytest.approx(0.10)

    def test_unknown_model_is_none_not_zero(self):
        assert pricing.estimate_cost("google", "modelo-inexistente", 10, 10) is None

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("LLM_PRICING_OVERRIDES", json.dumps({"google/novo": [1, 2]}))
        assert pricing.estimate_cost("google", "novo", 1_000_000, 1_000_000) == pytest.approx(3.0)

    def test_invalid_override_fails_fast(self, monkeypatch):
        monkeypatch.setenv("LLM_PRICING_OVERRIDES", "{ruim")
        with pytest.raises(ValueError, match="LLM_PRICING_OVERRIDES"):
            pricing.get_price("google", "x")


class TestMetering:
    def test_record_uses_bound_execution_and_cost(self):
        from src.llm import metering

        provider = MagicMock()
        provider.model_name = "gpt-6-luna"
        type(provider).__name__ = "OpenAIProvider"
        telemetry = MagicMock()
        metering.bind_execution("exec-1", "sess-1")
        with patch("src.llm.metering.get_telemetry", return_value=telemetry):
            metering.record_llm_call(
                provider, LLMResponse(text="x", usage={"prompt_tokens": 1000, "completion_tokens": 100}), 42, "triage"
            )
        kwargs = telemetry.record_token_usage.call_args.kwargs
        assert (kwargs["execution_id"], kwargs["session_id"], kwargs["agent_id"]) == ("exec-1", "sess-1", "triage")
        assert kwargs["llm_provider"] == "openai" and kwargs["latency_ms"] == 42
        assert kwargs["estimated_cost_usd"] == pytest.approx(0.00015)


class TestTokenSummaryIncludesBuffer:
    def test_unflushed_rows_are_summed(self):
        from src.telemetry import TelemetryCollector

        tel = TelemetryCollector.__new__(TelemetryCollector)
        tel._buffer = MagicMock()
        row = MagicMock(execution_id="e1", llm_provider="google", llm_model="m", latency_ms=100,
                        prompt_tokens=10, completion_tokens=5, total_tokens=15, estimated_cost_usd=0.5)
        other = MagicMock(execution_id="outra")
        tel._buffer.token_usage = [row, other]
        db = [{"llm_provider": "google", "llm_model": "m", "total_prompt_tokens": 90, "total_completion_tokens": 45,
               "total_tokens": 135, "total_cost_usd": 1.0, "avg_latency_ms": 200.0, "calls": 9}]
        out = tel._merge_buffered_tokens("e1", db)
        assert out[0]["total_tokens"] == 150 and out[0]["calls"] == 10
        assert out[0]["total_cost_usd"] == pytest.approx(1.5) and out[0]["avg_latency_ms"] == pytest.approx(190.0)
