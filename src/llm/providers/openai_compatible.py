import asyncio
import json
import time

import httpx

from src.llm.base import LLMProvider, LLMResponse, ToolCall
from src.llm.retry import RETRY_BACKOFFS_SECONDS, emit_connection_retry, is_retryable_status
from src.llm.versions import compose_compatible_version
from src.logger import get_logger

logger = get_logger(__name__)

# Backoff entre tentativas extras (após a primeira falha). ~3.5s de espera
# total no pior caso — evita travar o event loop do orquestrador no Pi 5
# esperando um servidor externo indisponível. Status transitórios (429/5xx)
# são avaliados por `is_retryable_status` (src/llm/retry.py).
_RETRY_BACKOFFS_SECONDS = RETRY_BACKOFFS_SECONDS


def _health_timeout() -> float:
    """Timeout do health check (``LLM_HEALTH_CHECK_TIMEOUT_SECONDS``), lido no uso."""
    from src import config

    return config.LLM_HEALTH_CHECK_TIMEOUT_SECONDS


class OpenAICompatibleProvider(LLMProvider):
    """Provedor para qualquer servidor que implemente `/chat/completions` com
    Tool Calling no formato da API da OpenAI — cobre llama.cpp server, vLLM,
    LM Studio e serviços hospedados compatíveis (ADR 011, V16).

    `base_url` deve incluir o prefixo de versão do servidor (ex.: `.../v1`).
    """

    def __init__(self, base_url: str | None, model: str, api_key: str | None = None):
        if not base_url:
            raise ValueError(
                "Provedor 'openai_compatible' requer OPENAI_COMPATIBLE_BASE_URL configurada em .env."
            )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # Timeout limitado (não infinito): este provedor também cobre serviços
        # hospedados, onde uma resposta pendurada não deve travar o host indefinidamente.
        self._client = httpx.AsyncClient(base_url=self._base_url, headers=headers, timeout=120.0)

    def _build_messages(self, messages: list[dict], system: str | None) -> list[dict]:
        if not system:
            return list(messages)
        first_msg = messages[0] if messages else None
        if first_msg and first_msg.get("role") == "system" and first_msg.get("content") == system:
            return list(messages)
        return [{"role": "system", "content": system}] + list(messages)

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
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        return payload

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        payload = self._build_payload(messages, tools, system, temperature, max_tokens)

        data, retry_count = await self._post_with_retry("/chat/completions", payload)

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = self._parse_tool_calls(message.get("tool_calls") or [])

        if tool_calls:
            finish_reason = "tool_calls"
        elif choice.get("finish_reason") == "length":
            finish_reason = "length"
        else:
            finish_reason = "stop"

        usage = data.get("usage") or {}
        return LLMResponse(
            text=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                # Parte do prompt lida do cache do servidor (cobrada a preço menor) e tokens de
                # raciocínio (já contidos em completion_tokens) — insumo de pricing e relatórios.
                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0,
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
                # Servidores compatíveis não expõem TTFT de forma padronizada.
                "ttft_ms": None,
                # Retentativas de conexão/429 desta chamada — insumo para v18-usage-limits.
                "retry_count": retry_count,
            },
            versao_efetiva=compose_compatible_version(data.get("model"), data.get("system_fingerprint")),
        )

    def _parse_tool_calls(self, raw_tool_calls: list[dict]) -> list[ToolCall]:
        tool_calls = []
        for tc in raw_tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    logger.warning(
                        "Argumentos de tool call inválidos (JSON malformado)",
                        extra={"tool_name": name},
                    )
                    args = {"_raw": raw_args}
            else:
                args = raw_args
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{name}_{int(time.time() * 1000)}",
                    name=name,
                    arguments=args,
                )
            )
        return tool_calls

    async def _post_with_retry(self, path: str, payload: dict) -> tuple[dict, int]:
        """POST com retentativa limitada em 429/5xx/erro de conexão.

        Returns:
            Tupla (corpo da resposta decodificado, número de retentativas feitas).
        """
        last_exc: Exception | None = None
        for attempt, backoff in enumerate((0.0, *_RETRY_BACKOFFS_SECONDS)):
            if backoff:
                logger.warning(
                    "Retentativa ao provedor openai_compatible",
                    extra={"attempt": attempt, "backoff_seconds": backoff, "model": self._model},
                )
                emit_connection_retry("llm_provider:openai_compatible", str(last_exc))
                await asyncio.sleep(backoff)
            try:
                response = await self._client.post(path, json=payload)
            except httpx.TransportError as exc:
                last_exc = exc
                continue

            if is_retryable_status(response.status_code):
                last_exc = httpx.HTTPStatusError(
                    f"Status retentável {response.status_code}",
                    request=response.request,
                    response=response,
                )
                continue

            if response.is_error:
                # O corpo da resposta diz o que a API recusou; raise_for_status() o descartaria.
                raise httpx.HTTPStatusError(
                    f"{response.status_code} em {response.request.url}: {response.text[:800]}",
                    request=response.request,
                    response=response,
                )
            return response.json(), attempt

        logger.error(
            "Provedor openai_compatible esgotou as retentativas",
            extra={"model": self._model},
        )
        raise last_exc

    async def generate_stream(self, messages: list[dict], system: str | None = None):
        payload = {
            "model": self._model,
            "messages": self._build_messages(messages, system),
            "stream": True,
        }
        async with self._client.stream("POST", "/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield content

    async def health_check(self) -> bool:
        try:
            response = await self._client.get("/models", timeout=_health_timeout())
            return response.status_code == 200
        except Exception:
            return False

    async def check_availability(self) -> str | None:
        """Confere que o modelo está em ``/models`` quando o servidor lista modelos."""
        response = await self._client.get("/models", timeout=_health_timeout())
        response.raise_for_status()
        try:
            listed = {item.get("id") for item in response.json().get("data", []) if isinstance(item, dict)}
        except ValueError:
            return None
        return None if not listed or self._model in listed else "modelo_nao_instalado"

    @property
    def model_name(self) -> str:
        return self._model
