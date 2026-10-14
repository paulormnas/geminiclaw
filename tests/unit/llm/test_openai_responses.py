"""API Responses do provedor OpenAI (esforço de raciocínio ligado), preços de Terra e Haiku 5.5 e catálogo."""

from __future__ import annotations

import asyncio

import pytest

from src.llm import pricing
from src.llm.providers.anthropic import _EFFORT_MODEL_PREFIXES
from src.llm.providers.openai import MIN_RESPONSES_TOKENS, OpenAIProvider

pytestmark = pytest.mark.unit

TOOLS = [{"type": "function", "function": {"name": "ping", "description": "d", "parameters": {"type": "object", "properties": {}}}}]


def _provider(effort: str | None = "xhigh") -> OpenAIProvider:
    return OpenAIProvider(api_key="sk", model="gpt-6-luna", reasoning_effort=effort)


def test_so_usa_responses_com_esforco_diferente_de_none() -> None:
    assert _provider("xhigh")._uses_responses() and _provider("high")._uses_responses()
    assert not _provider("none")._uses_responses() and not _provider(None)._uses_responses()


def test_payload_responses_converte_historico_ferramentas_e_esforco() -> None:
    history = [
        {"role": "user", "content": "faça"},
        {"role": "assistant", "content": "vou chamar",
         "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "ping", "arguments": {"a": 1}}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "ping", "content": {"ok": True}},
    ]
    payload = _provider()._build_responses_payload(history, TOOLS, "sistema", 100)
    assert payload["reasoning"] == {"effort": "xhigh"} and payload["instructions"] == "sistema"
    assert payload["max_output_tokens"] >= MIN_RESPONSES_TOKENS and "messages" not in payload
    assert payload["input"] == [
        {"role": "user", "content": "faça"},
        {"role": "assistant", "content": "vou chamar"},
        {"type": "function_call", "call_id": "c1", "name": "ping", "arguments": '{"a": 1}'},
        {"type": "function_call_output", "call_id": "c1", "output": '{"ok": true}'},
    ]
    assert payload["tools"] == [{"type": "function", "name": "ping", "description": "d",
                                 "parameters": {"type": "object", "properties": {}}, "strict": False}]


def test_mensagem_de_sistema_no_historico_vira_instrucao() -> None:
    payload = _provider()._build_responses_payload([{"role": "system", "content": "regra"},
                                                    {"role": "user", "content": "x"}], None, None, 10)
    assert payload["instructions"] == "regra" and payload["input"] == [{"role": "user", "content": "x"}]
    assert "tools" not in payload


def _run_generate(provider: OpenAIProvider, data: dict, tools=None):
    seen: dict = {}

    async def fake_post(path, payload):
        seen["path"], seen["payload"] = path, payload
        return data, 2

    provider._post_with_retry = fake_post  # type: ignore[method-assign]
    response = asyncio.run(provider.generate([{"role": "user", "content": "oi"}], tools=tools))
    return response, seen


def test_generate_responses_texto_e_uso() -> None:
    data = {"model": "gpt-6-luna-2026", "status": "completed",
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text", "text": "olá"}]}],
            "usage": {"input_tokens": 100, "output_tokens": 60, "total_tokens": 160,
                      "input_tokens_details": {"cached_tokens": 40}, "output_tokens_details": {"reasoning_tokens": 50}}}
    response, seen = _run_generate(_provider(), data)
    assert seen["path"] == "/responses" and response.text == "olá" and response.finish_reason == "stop"
    assert response.usage == {"prompt_tokens": 100, "completion_tokens": 60, "total_tokens": 160, "cached_tokens": 40,
                              "reasoning_tokens": 50, "ttft_ms": None, "retry_count": 2}
    assert response.versao_efetiva != "desconhecida"


def test_generate_responses_chamada_de_ferramenta() -> None:
    data = {"status": "completed", "output": [{"type": "function_call", "call_id": "call_9", "name": "ping",
                                               "arguments": '{"x": 2}'}], "usage": {}}
    response, _ = _run_generate(_provider(), data, TOOLS)
    assert response.finish_reason == "tool_calls" and response.text is None
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [("call_9", "ping", {"x": 2})]


def test_generate_responses_truncada_vira_length() -> None:
    data = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": [], "usage": {}}
    response, _ = _run_generate(_provider(), data)
    assert response.finish_reason == "length"


def test_esforco_none_continua_no_chat(monkeypatch) -> None:
    provider = _provider("none")
    paths: list[str] = []

    async def fake_post(path, payload):
        paths.append(path)
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}, 0

    provider._post_with_retry = fake_post  # type: ignore[method-assign]
    assert asyncio.run(provider.generate([{"role": "user", "content": "x"}])).text == "ok"
    assert paths == ["/chat/completions"]


def test_precos_sol_e_haiku_com_faixa_de_prompt_longo() -> None:
    assert pricing.estimate_cost("openai", "gpt-6.1-sol", 1_000_000, 1_000_000) == pytest.approx(4.0 + 15.0)
    short = pricing.estimate_cost("anthropic", "claude-haiku-5-5", 100_000, 10_000, cached_tokens=50_000)
    assert short == pytest.approx((50_000 * 0.10 + 50_000 * 0.01 + 10_000 * 0.50) / 1e6)
    long = pricing.estimate_cost("anthropic", "claude-haiku-5-5", 100_001, 10_000)
    assert long == pytest.approx((100_001 * 0.50 + 10_000 * 2.50) / 1e6)


def test_catalogo_tem_sol_e_haiku() -> None:
    from src.llm.catalog import load_catalog

    catalog = load_catalog()
    assert {"openai/gpt-6.1-sol", "anthropic/claude-haiku-5-5"} <= set(catalog.modelos)


def test_haiku_55_recebe_effort() -> None:
    assert "claude-haiku-5-5".startswith(_EFFORT_MODEL_PREFIXES)
    assert not "claude-haiku-4-5-20251001".startswith(_EFFORT_MODEL_PREFIXES)
