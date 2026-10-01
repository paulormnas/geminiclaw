"""Provedor da API da OpenAI (modelos GPT-6 em diante, ex.: ``gpt-6-luna``).

Reaproveita o protocolo ``/chat/completions`` de :class:`OpenAICompatibleProvider`, com as
diferenças dos modelos de raciocínio atuais da OpenAI:

- o limite de saída vai em ``max_completion_tokens`` (``max_tokens`` é rejeitado) e inclui os
  tokens de raciocínio, então o teto padrão é maior que o dos modelos sem raciocínio;
- ``temperature`` não é enviada (só o valor padrão é aceito);
- a chave é obrigatória e falha cedo, com mensagem acionável.
"""

from __future__ import annotations

import json

from src.llm.providers.openai_compatible import OpenAICompatibleProvider

DEFAULT_BASE_URL = "https://api.openai.com/v1"
# Raciocínio consome parte de max_completion_tokens; um teto baixo devolveria resposta vazia.
MIN_COMPLETION_TOKENS = 8192


class OpenAIProvider(OpenAICompatibleProvider):
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
