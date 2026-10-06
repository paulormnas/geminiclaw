"""Provedor Google Gemini (google-genai) para o registro de provedores (ADR 011).

Regras da API atual (Gemini 3.x) que moldam este módulo:

- Resultados de ferramenta voltam num turno de papel ``user`` (o papel ``function`` foi
  recusado com HTTP 400), e resultados de chamadas paralelas ficam no mesmo turno.
- Cada ``functionCall`` do modelo traz uma ``thought_signature`` que precisa ser devolvida
  intacta no histórico; sem ela a API responde HTTP 400. As partes da resposta são guardadas em
  ``LLMResponse.provider_data`` e reenviadas enquanto a mensagem não foi editada (a compressão
  de contexto pode reescrevê-la).
- A chamada é assíncrona (``client.aio``): a versão anterior usava a chamada síncrona dentro de
  ``async def`` e congelava o event loop, compartilhado por todos os agentes do processo.
- Tokens de pensamento são cobrados como saída e entram em ``completion_tokens``.
- Em erro 429 (limite de requisições) o provedor troca por ``fallback_model`` e mantém a troca
  por ``_FALLBACK_STICKY_SECONDS``, para não repetir a espera a cada chamada.
"""

import asyncio
import base64
import json
import time

from google import genai
from google.genai import types as genai_types

from src.config import GEMINI_API_KEY
from src.llm.base import LLMProvider, LLMResponse, ToolCall
from src.llm.retry import RETRY_BACKOFFS_SECONDS, emit_connection_retry, is_retryable_error
from src.logger import get_logger

logger = get_logger(__name__)

# Os tokens de pensamento do Gemini 3.x contam em max_output_tokens; um teto baixo (ex.: 10 na triagem)
# é consumido todo pelo raciocínio e a resposta volta vazia. Piso análogo ao do provedor Anthropic.
_MIN_MAX_TOKENS = 8192
_FALLBACK_STICKY_SECONDS = 120.0


def _is_rate_limit(exc: BaseException) -> bool:
    message = str(exc)
    return "429" in message or "RESOURCE_EXHAUSTED" in message


def _encode_signature(signature: bytes | None) -> str | None:
    return base64.b64encode(signature).decode("ascii") if signature else None


def _decode_signature(signature: str | None) -> bytes | None:
    return base64.b64decode(signature) if signature else None


class GoogleProvider(LLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
    ):
        self._api_key = api_key or GEMINI_API_KEY
        if not model:
            raise ValueError("GoogleProvider requer o nome do modelo (resolvido pelo roteador de modelos).")
        self._model = model
        self._fallback_model = fallback_model if fallback_model and fallback_model != self._model else None
        self._fallback_until = 0.0
        self._last_model_used = self._model
        self._client = genai.Client(api_key=self._api_key)

    # ------------------------------------------------------------------ entrada

    def _assistant_parts(self, msg: dict) -> list[genai_types.Part]:
        """Partes de uma mensagem ``assistant`` do histórico, com as assinaturas de pensamento."""
        text = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        stored = (msg.get("provider_data") or {}).get("parts")
        if stored:
            stored_text = "".join(p["text"] for p in stored if p["type"] == "text")
            stored_calls = [p["name"] for p in stored if p["type"] == "function_call"]
            if stored_text == text and stored_calls == [tc["function"]["name"] for tc in tool_calls]:
                parts = []
                for p in stored:
                    signature = _decode_signature(p.get("thought_signature"))
                    if p["type"] == "text":
                        parts.append(genai_types.Part(text=p["text"], thought_signature=signature))
                    else:
                        parts.append(
                            genai_types.Part(
                                function_call=genai_types.FunctionCall(name=p["name"], args=p["args"]),
                                thought_signature=signature,
                            )
                        )
                return parts
            logger.debug("provider_data descartado: a mensagem foi editada depois da resposta do modelo")

        parts = [genai_types.Part(text=text)] if text else []
        for tc in tool_calls:
            args = tc["function"]["arguments"]
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args else {}
                except json.JSONDecodeError:
                    args = {"_raw": args}
            parts.append(
                genai_types.Part(function_call=genai_types.FunctionCall(name=tc["function"]["name"], args=args))
            )
        return parts

    def _to_contents(self, messages: list[dict]) -> list[genai_types.Content]:
        """Converte o histórico interno (formato OpenAI) para ``Content`` do Gemini.

        Mensagens ``system`` são ignoradas (a instrução vai em ``system_instruction``); mensagens
        ``tool`` consecutivas e o texto de usuário que as segue formam um único turno ``user``.
        """
        contents: list[genai_types.Content] = []

        def add(role: str, parts: list[genai_types.Part]) -> None:
            if not parts:
                return
            if contents and contents[-1].role == role == "user":
                contents[-1].parts.extend(parts)
            else:
                contents.append(genai_types.Content(role=role, parts=parts))

        pending_responses: list[genai_types.Part] = []
        for msg in messages:
            role = msg.get("role")
            if role == "system":
                continue
            if role == "tool":
                pending_responses.append(
                    genai_types.Part(
                        function_response=genai_types.FunctionResponse(
                            name=msg.get("name") or msg.get("tool_call_id") or "unknown",
                            response={"result": msg.get("content") or ""},
                        )
                    )
                )
                continue
            if pending_responses:
                add("user", pending_responses)
                pending_responses = []
            if role == "assistant":
                add("model", self._assistant_parts(msg))
            else:
                content = msg.get("content") or ""
                add("user", [genai_types.Part(text=content)] if content else [])
        if pending_responses:
            add("user", pending_responses)
        return contents

    @staticmethod
    def _to_tools(tools: list[dict]) -> list[genai_types.Tool]:
        functions = [
            genai_types.FunctionDeclaration(
                name=t["function"]["name"],
                description=t["function"]["description"],
                parameters=t["function"]["parameters"],
            )
            for t in tools
            if t.get("type") == "function"
        ]
        return [genai_types.Tool(function_declarations=functions)] if functions else []

    # ------------------------------------------------------------------ chamada

    def _current_model(self) -> str:
        if self._fallback_model and time.monotonic() < self._fallback_until:
            return self._fallback_model
        return self._model

    async def _call_with_retry(self, model: str, contents, config):
        """``generate_content`` assíncrono com retentativa limitada e telemetria de conexão."""
        last_exc: Exception | None = None
        for attempt, backoff in enumerate((0.0, *RETRY_BACKOFFS_SECONDS)):
            if backoff:
                logger.warning(
                    "Retentativa ao provedor Google GenAI",
                    extra={"attempt": attempt, "backoff_seconds": backoff, "model": model},
                )
                emit_connection_retry("llm_provider:google", str(last_exc))
                await asyncio.sleep(backoff)
            try:
                response = await self._client.aio.models.generate_content(
                    model=model, contents=contents, config=config
                )
                self._last_model_used = model
                return response
            except Exception as exc:  # noqa: BLE001 — classificado por is_retryable_error
                last_exc = exc
                if not is_retryable_error(exc):
                    raise
        logger.error("Provedor Google GenAI esgotou as retentativas", extra={"model": model})
        raise last_exc

    async def _generate_content(self, contents, config):
        model = self._current_model()
        try:
            return await self._call_with_retry(model, contents, config)
        except Exception as exc:  # noqa: BLE001
            if self._fallback_model and model != self._fallback_model and _is_rate_limit(exc):
                logger.warning(
                    "Limite de requisições atingido; usando o modelo de fallback",
                    extra={"model": model, "fallback": self._fallback_model},
                )
                self._fallback_until = time.monotonic() + _FALLBACK_STICKY_SECONDS
                return await self._call_with_retry(self._fallback_model, contents, config)
            raise

    # ------------------------------------------------------------------ interface pública

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max(max_tokens, _MIN_MAX_TOKENS),
            system_instruction=system,
        )
        if tools:
            config.tools = self._to_tools(tools)

        try:
            response = await self._generate_content(self._to_contents(messages), config)
        except Exception as exc:
            logger.error(f"Erro na requisição ao Google GenAI: {str(exc)}")
            raise

        texts: list[str] = []
        thoughts: list[str] = []
        tool_calls: list[ToolCall] = []
        stored: list[dict] = []
        candidate = response.candidates[0] if response.candidates else None
        parts = candidate.content.parts if candidate and candidate.content and candidate.content.parts else []
        for part in parts:
            signature = _encode_signature(part.thought_signature)
            if part.thought:
                if part.text:
                    thoughts.append(part.text)
            elif part.function_call:
                fc = part.function_call
                args = dict(fc.args or {})
                # Google não tem um id único por chamada como a OpenAI; usa-se o nome da função.
                tool_calls.append(ToolCall(id=fc.name, name=fc.name, arguments=args))
                stored.append({"type": "function_call", "name": fc.name, "args": args, "thought_signature": signature})
            elif part.text is not None:
                texts.append(part.text)
                stored.append({"type": "text", "text": part.text, "thought_signature": signature})

        finish_reason = "stop"
        if candidate is not None:
            if str(candidate.finish_reason).endswith("MAX_TOKENS"):
                finish_reason = "length"
            elif tool_calls:
                finish_reason = "tool_calls"

        usage_metadata = response.usage_metadata
        prompt_tokens = (usage_metadata.prompt_token_count or 0) if usage_metadata else 0
        # Tokens de pensamento são cobrados como saída.
        completion_tokens = (
            ((usage_metadata.candidates_token_count or 0) + (getattr(usage_metadata, "thoughts_token_count", 0) or 0))
            if usage_metadata
            else 0
        )
        return LLMResponse(
            text="".join(texts) or None,
            thought="\n".join(thoughts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": (usage_metadata.total_token_count or 0) if usage_metadata else 0,
                "cached_tokens": (getattr(usage_metadata, "cached_content_token_count", 0) or 0) if usage_metadata else 0,
                # V11.2.3 — Google GenAI não expõe TTFT na API atual; None mantém o schema do Ollama.
                "ttft_ms": None,
            },
            provider_data={"parts": stored} if stored else None,
        )

    async def generate_stream(self, messages: list[dict], system: str | None = None):
        response = await self.generate(messages, system=system)
        if response.text:
            yield response.text

    async def health_check(self) -> bool:
        """Consulta os metadados do modelo (``models.get``): não gera texto nem gasta tokens."""
        try:
            await self._client.aio.models.get(model=self._model)
            return True
        except Exception:
            return False

    async def check_availability(self) -> str | None:
        await self._client.aio.models.get(model=self._model)
        return None

    @property
    def model_name(self) -> str:
        """Modelo que atendeu a última chamada (o de fallback, se a troca por limite estiver ativa)."""
        return self._last_model_used
