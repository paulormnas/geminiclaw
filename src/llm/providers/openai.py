"""Provedor da API da OpenAI (modelos GPT-6 em diante, ex.: ``gpt-6-luna``).

Reaproveita o protocolo ``/chat/completions`` de :class:`OpenAICompatibleProvider`, com as
diferenças dos modelos de raciocínio atuais da OpenAI:

- o limite de saída vai em ``max_completion_tokens`` (``max_tokens`` é rejeitado) e inclui os
  tokens de raciocínio, então o teto padrão é maior que o dos modelos sem raciocínio;
- ``temperature`` não é enviada (só o valor padrão é aceito);
- a chave é obrigatória e falha cedo, com mensagem acionável;
- com ``reasoning_effort`` diferente de ``none`` o ``/chat/completions`` recusa ferramentas ("Function tools with
  reasoning_effort are not supported ... use /v1/responses"), então o provedor usa a **API Responses**
  (``/v1/responses``) nesse caso; sem raciocínio, segue em ``/chat/completions``.
"""

from __future__ import annotations

import json

from src.llm.base import LLMResponse, ToolCall
from src.llm.providers.openai_compatible import OpenAICompatibleProvider
from src.llm.versions import compose_compatible_version

DEFAULT_BASE_URL = "https://api.openai.com/v1"
# Raciocínio consome parte de max_completion_tokens; um teto baixo devolveria resposta vazia.
MIN_COMPLETION_TOKENS = 8192
# Na API Responses o teto cobre raciocínio + resposta; com esforço alto 8192 devolveria resposta vazia.
MIN_RESPONSES_TOKENS = 32768


class OpenAIProvider(OpenAICompatibleProvider):
    PROVIDER_KEY = "openai"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        reasoning_effort: str | None = None,
    ):
        if not api_key:
            raise ValueError("Provedor 'openai' requer OPENAI_API_KEY configurada em .env.")
        super().__init__(base_url=base_url or DEFAULT_BASE_URL, model=model, api_key=api_key)
        self._reasoning_effort = reasoning_effort or None

    def _build_messages(self, messages: list[dict], system: str | None) -> list[dict]:
        """Normaliza o histórico interno para o esquema estrito da API da OpenAI.

        O histórico guarda ``arguments`` como dict e campos próprios (``thought``, ``provider_data``,
        ``name`` em resultados de ferramenta); a API exige ``arguments`` em string JSON e rejeita
        campos desconhecidos.
        """
        clean: list[dict] = []
        for msg in super()._build_messages(messages, system):
            role = msg.get("role")
            if role == "assistant":
                out: dict = {"role": "assistant", "content": msg.get("content")}
                if msg.get("tool_calls"):
                    out["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"]
                                if isinstance(tc["function"]["arguments"], str)
                                else json.dumps(tc["function"]["arguments"], ensure_ascii=False),
                            },
                        }
                        for tc in msg["tool_calls"]
                    ]
                clean.append(out)
            elif role == "tool":
                content = msg.get("content")
                clean.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg["tool_call_id"],
                        "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                    }
                )
            else:
                clean.append({"role": role, "content": msg.get("content")})
        return clean

    def _build_payload(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        system: str | None,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        payload = {
            "model": self._model,
            "messages": self._build_messages(messages, system),
            "max_completion_tokens": max(max_tokens, MIN_COMPLETION_TOKENS),
        }
        if self._reasoning_effort:
            payload["reasoning_effort"] = self._reasoning_effort
        if tools:
            payload["tools"] = tools
        return payload

    # -- API Responses (raciocínio ligado) -----------------------------------------------------------------------

    def _uses_responses(self) -> bool:
        """True quando há esforço de raciocínio diferente de ``none`` (o chat não aceita ferramentas assim)."""
        return bool(self._reasoning_effort) and self._reasoning_effort != "none"

    def _responses_input(self, messages: list[dict], system: str | None) -> tuple[list[dict], str | None]:
        """Converte o histórico (formato de chat normalizado) para os itens de ``input`` da API Responses."""
        instructions = system
        items: list[dict] = []
        for msg in self._build_messages(messages, None):
            role = msg.get("role")
            if role == "system":
                instructions = f"{instructions}\n\n{msg.get('content')}" if instructions else msg.get("content")
            elif role == "assistant":
                if msg.get("content"):
                    items.append({"role": "assistant", "content": msg["content"]})
                for tc in msg.get("tool_calls") or []:
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": tc["id"],
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        }
                    )
            elif role == "tool":
                items.append({"type": "function_call_output", "call_id": msg["tool_call_id"], "output": msg["content"]})
            else:
                items.append({"role": role, "content": msg.get("content") or ""})
        return items, instructions

    @staticmethod
    def _responses_tools(tools: list[dict]) -> list[dict]:
        """Ferramentas no formato da API Responses (campos ``name``/``parameters`` no nível do item)."""
        converted = []
        for tool in tools:
            fn = tool.get("function") or tool
            converted.append(
                {
                    "type": "function",
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                    "strict": False,
                }
            )
        return converted

    def _build_responses_payload(
        self, messages: list[dict], tools: list[dict] | None, system: str | None, max_tokens: int
    ) -> dict:
        items, instructions = self._responses_input(messages, system)
        payload: dict = {
            "model": self._model,
            "input": items,
            "reasoning": {"effort": self._reasoning_effort},
            "max_output_tokens": max(max_tokens, MIN_RESPONSES_TOKENS),
        }
        if instructions:
            payload["instructions"] = instructions
        if tools:
            payload["tools"] = self._responses_tools(tools)
        return payload

    def _parse_responses(self, data: dict, retry_count: int) -> LLMResponse:
        texts: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in data.get("output") or []:
            kind = item.get("type")
            if kind == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "output_text" and part.get("text"):
                        texts.append(part["text"])
            elif kind == "function_call":
                tool_calls.extend(
                    self._parse_tool_calls(
                        [
                            {
                                "id": item.get("call_id") or item.get("id"),
                                "function": {"name": item.get("name", ""), "arguments": item.get("arguments", "{}")},
                            }
                        ]
                    )
                )
        incomplete = (data.get("incomplete_details") or {}).get("reason")
        if tool_calls:
            finish_reason = "tool_calls"
        elif data.get("status") == "incomplete" and incomplete == "max_output_tokens":
            finish_reason = "length"
        else:
            finish_reason = "stop"
        usage = data.get("usage") or {}
        return LLMResponse(
            text="\n".join(texts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "cached_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0,
                "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
                "ttft_ms": None,
                "retry_count": retry_count,
            },
            versao_efetiva=compose_compatible_version(data.get("model"), None),
        )

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        if not self._uses_responses():
            return await super().generate(messages, tools, system, temperature, max_tokens)
        payload = self._build_responses_payload(messages, tools, system, max_tokens)
        data, retry_count = await self._post_with_retry("/responses", payload)
        return self._parse_responses(data, retry_count)
