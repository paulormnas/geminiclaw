"""Provedor Anthropic (Claude) para o registro de provedores (ADR 011).

Implementa o contrato `LLMProvider` sobre a Messages API pelo SDK oficial `anthropic`.
Decisões de projeto, todas ligadas a restrições dos modelos atuais (Sonnet 5.5, Opus 5.5):

- **Sem `temperature`.** Os modelos atuais rejeitam (HTTP 400) valores de amostragem diferentes
  do padrão, então o parâmetro do contrato é ignorado. A qualidade é controlada por `effort`.
- **Raciocínio adaptativo por omissão.** Não enviamos `thinking`; o modelo decide quando pensar.
  O pensamento consome `max_tokens`, por isso há um piso (`_MIN_MAX_TOKENS`).
- **Blocos de pensamento devolvidos intactos.** No ciclo de ferramentas a API exige de volta,
  sem alteração, os blocos de pensamento (assinados) da resposta anterior. Eles são guardados
  em `LLMResponse.provider_data` e reenviados enquanto o restante da mensagem não tiver sido
  editado (a compressão de contexto pode reescrever o histórico).
- **Sem `tool_choice` forçado.** `any`/`tool` retornam 400; usamos o padrão (`auto`).
- **Recusas são erros explícitos** (`ProviderRefusalError`), com a categoria informada.
- **Retentativas próprias** (o SDK é criado com `max_retries=0`) para emitir a telemetria
  `connection_retry` que alimenta os limites de uso da sessão (V18).
"""

from __future__ import annotations

import asyncio
import json

import anthropic

from src.llm.base import LLMProvider, LLMResponse, ToolCall
from src.llm.retry import RETRY_BACKOFFS_SECONDS, emit_connection_retry, is_retryable_status
from src.logger import get_logger

logger = get_logger(__name__)

# O raciocínio adaptativo conta no limite de saída; abaixo disso a resposta pode ser cortada
# no meio do pensamento. Também é o teto recomendado para chamadas sem streaming.
_MIN_MAX_TOKENS = 16000
_REQUEST_TIMEOUT_SECONDS = 300.0
_VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")
_FALLBACK_BETA_HEADER = "server-side-fallback-2026-07-01"

# Recursos que dependem do modelo. Modelos fora destas listas (ex.: Haiku 4.5) rejeitam os parâmetros
# com HTTP 400, então o provedor simplesmente não os envia.
_EFFORT_MODEL_PREFIXES = ("claude-fable", "claude-mythos", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
                          "claude-opus-4-6", "claude-sonnet-5", "claude-sonnet-4-6")
_FALLBACK_MODEL_PREFIXES = ("claude-fable", "claude-opus-5", "claude-sonnet-5-5")


class ProviderRefusalError(RuntimeError):
    """O provedor recusou o pedido por política de segurança (`stop_reason == "refusal"`)."""

    def __init__(self, model: str, category: str | None, explanation: str | None):
        self.model = model
        self.category = category
        self.explanation = explanation
        detail = f" ({explanation})" if explanation else ""
        super().__init__(
            f"O modelo '{model}' recusou o pedido (categoria: {category or 'não informada'}){detail}."
        )


def _blocks_to_provider_data(content: list) -> list[dict]:
    """Serializa os blocos de uma resposta na forma aceita de volta pela API.

    Só os campos que a API aceita são mantidos, na ordem original da resposta.
    """
    blocks: list[dict] = []
    for block in content:
        kind = block.type
        if kind == "text":
            blocks.append({"type": "text", "text": block.text})
        elif kind == "thinking":
            blocks.append({"type": "thinking", "thinking": block.thinking, "signature": block.signature})
        elif kind == "redacted_thinking":
            blocks.append({"type": "redacted_thinking", "data": block.data})
        elif kind == "tool_use":
            blocks.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input or {})}
            )
    return blocks


def _tool_result_content(content: object) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


class AnthropicProvider(LLMProvider):
    """Provedor para os modelos Claude via Messages API."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        effort: str = "medium",
        refusal_fallback: bool = True,
    ):
        if not api_key:
            raise ValueError("Provedor 'anthropic' requer ANTHROPIC_API_KEY configurada em .env.")
        effort = (effort or "").strip().lower()
        if effort and effort not in _VALID_EFFORTS:
            raise ValueError(
                f"ANTHROPIC_EFFORT inválido: '{effort}'. Use um de {', '.join(_VALID_EFFORTS)} ou deixe vazio."
            )
        self._model = model
        self._effort = effort
        self._refusal_fallback = refusal_fallback
        # max_retries=0: a retentativa é feita aqui, para emitir a telemetria de conexão.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url or None,
            max_retries=0,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )

    # ------------------------------------------------------------------ conversão de entrada

    def _assistant_blocks(self, message: dict) -> list[dict]:
        """Blocos de conteúdo de uma mensagem `assistant` do histórico."""
        text = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        stored = (message.get("provider_data") or {}).get("content")
        if stored:
            stored_text = "".join(b["text"] for b in stored if b["type"] == "text")
            stored_ids = [b["id"] for b in stored if b["type"] == "tool_use"]
            if stored_text == text and stored_ids == [tc["id"] for tc in tool_calls]:
                return list(stored)
            logger.debug("provider_data descartado: a mensagem foi editada depois da resposta do modelo")

        blocks: list[dict] = []
        if text:
            blocks.append({"type": "text", "text": text})
        for tool_call in tool_calls:
            function = tool_call["function"]
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments) if arguments else {}
                except json.JSONDecodeError:
                    arguments = {"_raw": arguments}
            blocks.append(
                {"type": "tool_use", "id": tool_call["id"], "name": function["name"], "input": arguments}
            )
        return blocks

    def _convert_messages(self, messages: list[dict], system: str | None) -> tuple[str | None, list[dict]]:
        """Converte o histórico interno (formato OpenAI) para o da Messages API.

        Mensagens `system` viram o parâmetro `system`. Mensagens `tool` e `user` consecutivas
        formam um único turno `user` com os `tool_result` primeiro, como a API exige.
        """
        system_parts = [system] if system else []
        converted: list[dict] = []
        pending_results: list[dict] = []
        pending_texts: list[dict] = []

        def flush_user() -> None:
            nonlocal pending_results, pending_texts
            if pending_results or pending_texts:
                converted.append({"role": "user", "content": pending_results + pending_texts})
            pending_results, pending_texts = [], []

        for message in messages:
            role = message.get("role")
            if role == "system":
                content = message.get("content")
                if content and content != system:
                    system_parts.append(content)
            elif role == "user":
                content = message.get("content")
                if content:
                    pending_texts.append({"type": "text", "text": content})
            elif role == "tool":
                pending_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": message["tool_call_id"],
                        "content": _tool_result_content(message.get("content", "")),
                    }
                )
            elif role == "assistant":
                flush_user()
                blocks = self._assistant_blocks(message)
                if blocks:
                    converted.append({"role": "assistant", "content": blocks})
        flush_user()
        return ("\n\n".join(system_parts) or None), converted

    @staticmethod
    def _convert_tools(tools: list[dict]) -> list[dict]:
        """Converte ferramentas do formato OpenAI para o da Messages API."""
        converted = []
        for tool in tools:
            function = tool.get("function", tool)
            schema = function.get("parameters") or function.get("input_schema") or {}
            converted.append(
                {
                    "name": function["name"],
                    "description": function.get("description", ""),
                    "input_schema": {"type": "object", "properties": {}, **schema},
                }
            )
        return converted

    def _request_kwargs(
        self, messages: list[dict], tools: list[dict] | None, system: str | None, max_tokens: int
    ) -> dict:
        system_text, converted = self._convert_messages(messages, system)
        kwargs: dict = {
            "model": self._model,
            "max_tokens": max(max_tokens, _MIN_MAX_TOKENS),
            "messages": converted,
        }
        if system_text:
            kwargs["system"] = system_text
        if tools:
            kwargs["tools"] = self._convert_tools(tools)
        if self._effort and self._model.startswith(_EFFORT_MODEL_PREFIXES):
            kwargs["output_config"] = {"effort": self._effort}
        if self._refusal_fallback and self._model.startswith(_FALLBACK_MODEL_PREFIXES):
            kwargs["extra_headers"] = {"anthropic-beta": _FALLBACK_BETA_HEADER}
            kwargs["extra_body"] = {"fallbacks": "default"}
        return kwargs

    # ------------------------------------------------------------------ chamada e retentativa

    async def _create_with_retry(self, **kwargs) -> tuple[object, int]:
        """`messages.create` com retentativa limitada em erro de conexão, 429 e 5xx."""
        last_exc: Exception | None = None
        for attempt, backoff in enumerate((0.0, *RETRY_BACKOFFS_SECONDS)):
            if backoff:
                logger.warning(
                    "Retentativa ao provedor anthropic",
                    extra={"attempt": attempt, "backoff_seconds": backoff, "model": self._model},
                )
                emit_connection_retry("llm_provider:anthropic", str(last_exc))
                await asyncio.sleep(backoff)
            try:
                return await self._client.messages.create(**kwargs), attempt
            except anthropic.APIConnectionError as exc:
                last_exc = exc
            except anthropic.APIStatusError as exc:
                if not is_retryable_status(exc.status_code):
                    raise
                last_exc = exc
        logger.error("Provedor anthropic esgotou as retentativas", extra={"model": self._model})
        raise last_exc

    # ------------------------------------------------------------------ interface pública

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        # `temperature` é ignorado de propósito: os modelos atuais rejeitam valores não padrão.
        response, retry_count = await self._create_with_retry(
            **self._request_kwargs(messages, tools, system, max_tokens)
        )

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise ProviderRefusalError(
                self._model,
                getattr(details, "category", None),
                getattr(details, "explanation", None),
            )

        texts, thoughts, tool_calls = [], [], []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "thinking" and block.thinking:
                thoughts.append(block.thinking)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {})))

        # Só guarda os blocos quando o próprio modelo pedido respondeu; num fallback os blocos
        # de pensamento pertencem a outro modelo e não devem ser reenviados.
        served_by_fallback = any(block.type == "fallback" for block in response.content)
        provider_data = None
        if not served_by_fallback:
            provider_data = {"content": _blocks_to_provider_data(response.content)}

        if tool_calls:
            finish_reason = "tool_calls"
        elif response.stop_reason == "max_tokens":
            finish_reason = "length"
        else:
            finish_reason = "stop"

        usage = response.usage
        prompt_tokens = (
            (getattr(usage, "input_tokens", 0) or 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        )
        completion_tokens = getattr(usage, "output_tokens", 0) or 0
        return LLMResponse(
            text="".join(texts) or None,
            thought="\n".join(thoughts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "ttft_ms": None,
                "retry_count": retry_count,
            },
            provider_data=provider_data,
        )

    async def generate_stream(self, messages: list[dict], system: str | None = None):
        kwargs = self._request_kwargs(messages, None, system, _MIN_MAX_TOKENS)
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def health_check(self) -> bool:
        try:
            await self._client.with_options(timeout=5.0).models.retrieve(self._model)
            return True
        except Exception:
            return False

    @property
    def model_name(self) -> str:
        return self._model
