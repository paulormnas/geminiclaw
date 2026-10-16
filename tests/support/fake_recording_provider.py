"""Provedor LLM simulado que registra o que recebe (v18.7-benchmark-fixes, tarefa 3.0).

Implementa a interface de provedor sem rede: guarda, por chamada, o ``system`` e as ``messages``; devolve respostas
roteirizadas em ordem (a última se repete); aceita latência simulada por chamada e erros roteirizados (429 com e sem
marcador de cota, 503 e esgotamento de cota com status e mensagem configuráveis). Reutilizado pelas mudanças V18.7
seguintes em vez de criar outro provedor de teste.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from src.llm.base import LLMProvider, LLMResponse
from src.llm.quota import ProviderQuotaExhausted

SPENDING_CAP_MESSAGE = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'Your project has exceeded its monthly spending cap. "
    "Please go to AI Studio at https://ai.studio/spend to manage your project spend cap.', "
    "'status': 'RESOURCE_EXHAUSTED'}}"
)
PER_MINUTE_MESSAGE = (
    "429 RESOURCE_EXHAUSTED. You exceeded your current quota, please check your plan and billing details."
)


class ScriptedError(Exception):
    """Erro roteirizado de um provedor, com status HTTP e mensagem."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = status_code


@dataclass
class RecordedCall:
    """Uma chamada recebida pelo provedor simulado."""

    system: str | None
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None


@dataclass
class FakeRecordingProvider(LLMProvider):
    """Provedor simulado: ``script`` é a lista de respostas (texto, ``LLMResponse`` ou exceção) devolvidas em ordem.

    Args:
        script: Itens consumidos um por chamada; o último se repete. Vazio devolve ``"ok"``.
        latency_seconds: Espera simulada em cada chamada.
        name: Valor de ``model_name``.
    """

    script: list[Any] = field(default_factory=list)
    latency_seconds: float = 0.0
    name: str = "fake-model"
    calls: list[RecordedCall] = field(default_factory=list)

    # -- erros roteirizados ---------------------------------------------------------------------------------------

    @staticmethod
    def rate_limit_error() -> ScriptedError:
        """429 por minuto (transitório): sem marcador de cota."""
        return ScriptedError(429, PER_MINUTE_MESSAGE)

    @staticmethod
    def service_unavailable() -> ScriptedError:
        return ScriptedError(503, "503 Service Unavailable")

    @staticmethod
    def spending_cap_error() -> ScriptedError:
        """429 de teto de gasto mensal do Google."""
        return ScriptedError(429, SPENDING_CAP_MESSAGE)

    @staticmethod
    def quota_exhausted(provider: str = "google", model: str = "fake-model", status: int = 429) -> ProviderQuotaExhausted:
        return ProviderQuotaExhausted(provider, model, status, SPENDING_CAP_MESSAGE)

    # -- interface de provedor ------------------------------------------------------------------------------------

    async def generate(self, messages, tools=None, system=None, temperature=0.7, max_tokens=4096, **kwargs):
        self.calls.append(RecordedCall(system=system, messages=list(messages), tools=tools))
        if self.latency_seconds:
            await asyncio.sleep(self.latency_seconds)
        if not self.script:
            return LLMResponse(text="ok")
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, LLMResponse):
            return item
        return LLMResponse(text=str(item))

    async def generate_stream(self, messages, system=None):
        yield (await self.generate(messages, system=system)).text or ""

    async def health_check(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return self.name
