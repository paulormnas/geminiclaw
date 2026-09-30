"""Controle de recursos do runtime em processo (Roadmap V15 / V16, ADR 014).

Antes do ADR 014 o ``ContainerRunner`` limitava quantos containers de agente rodavam ao
mesmo tempo e esperava o Raspberry Pi esfriar ou liberar memória antes de iniciar outro.
Com os agentes no processo do orquestrador essas proteções precisam continuar existindo,
porque sem elas o ``asyncio.gather`` do laço autônomo dispararia todas as subtarefas
prontas de uma vez. Este módulo concentra as três proteções:

- limite de agentes simultâneos, calculado pela RAM disponível e limitado por
  ``MAX_CONCURRENT_AGENTS``;
- limite extra para inferência local (Ollama), que satura a CPU do Pi;
- espera por temperatura e memória (``HEALTH_CHECK_ENABLED``), com falha explícita.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from src.config import (
    HEALTH_CHECK_ENABLED,
    MAX_CONCURRENT_AGENTS,
    MAX_LOCAL_LLM_CONCURRENT,
    PI_MIN_AVAILABLE_MEMORY_MB,
    PI_TEMPERATURE_LIMIT,
)
from src.health import PiHealthMonitor
from src.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_LIMIT = 3
_HEALTH_MAX_WAIT_SECONDS = 60
_HEALTH_POLL_SECONDS = 5


def calculate_dynamic_limit(health: PiHealthMonitor) -> int:
    """Calcula quantos agentes podem rodar juntos a partir da RAM disponível.

    Args:
        health: Monitor de saúde do sistema.

    Returns:
        3 com 6 GB ou mais livres, 2 com 3 GB ou mais, 1 abaixo disso; 3 quando a leitura
        de memória não está disponível (ex.: macOS). O resultado nunca passa de
        ``MAX_CONCURRENT_AGENTS``.
    """
    limit = _DEFAULT_LIMIT
    try:
        memory = health.get_memory_usage()
        if memory and "available_mb" in memory:
            available_gb = memory["available_mb"] / 1024.0
            if available_gb >= 6.0:
                limit = 3
            elif available_gb >= 3.0:
                limit = 2
            else:
                limit = 1
            logger.info(f"Limite dinâmico de agentes simultâneos: {limit} (RAM livre: {available_gb:.2f} GB)")
        else:
            logger.warning("Falha ao ler memória (provavelmente macOS). Usando o limite padrão.")
    except Exception as exc:  # noqa: BLE001 — a leitura de memória é opcional
        logger.warning(f"Erro ao calcular o limite de recursos, usando o padrão ({_DEFAULT_LIMIT}): {exc}")
    return max(1, min(limit, MAX_CONCURRENT_AGENTS))


async def wait_for_health(
    health: PiHealthMonitor,
    max_wait_seconds: float = _HEALTH_MAX_WAIT_SECONDS,
    poll_seconds: float = _HEALTH_POLL_SECONDS,
) -> None:
    """Aguarda a temperatura e a memória livre ficarem dentro dos limites.

    Args:
        health: Monitor de saúde do sistema.
        max_wait_seconds: Tempo máximo total de espera.
        poll_seconds: Intervalo entre verificações.

    Raises:
        RuntimeError: Se os limites continuarem excedidos após ``max_wait_seconds``.
    """
    waited = 0.0
    while waited < max_wait_seconds:
        temperature = health.get_temperature()
        memory = health.get_memory_usage()

        if temperature is not None and temperature > 70.0:
            logger.warning("Temperatura do sistema elevada", extra={"temperature": temperature})

        reasons = []
        if temperature is not None and temperature >= PI_TEMPERATURE_LIMIT:
            reasons.append(f"Temperatura alta ({temperature} >= {PI_TEMPERATURE_LIMIT})")
        if memory is not None and memory["available_mb"] < PI_MIN_AVAILABLE_MEMORY_MB:
            reasons.append(f"Memória livre baixa ({memory['available_mb']} < {PI_MIN_AVAILABLE_MEMORY_MB})")
        if not reasons:
            return

        logger.warning(
            "Aguardando resfriamento/liberação de memória",
            extra={"reasons": reasons, "waited_seconds": waited},
        )
        await asyncio.sleep(poll_seconds)
        waited += poll_seconds

    raise RuntimeError("Timeout aguardando saúde do sistema. Limites excedidos por muito tempo.")


class ResourceGuard:
    """Regula quantos agentes executam ao mesmo tempo e quando é seguro iniciar um."""

    def __init__(
        self,
        health: PiHealthMonitor | None = None,
        max_concurrent: int | None = None,
        local_llm_concurrent: int | None = None,
    ) -> None:
        """Cria o regulador.

        Args:
            health: Monitor de saúde (padrão: um novo ``PiHealthMonitor``).
            max_concurrent: Limite fixo de agentes simultâneos; se omitido, é calculado
                pela RAM livre.
            local_llm_concurrent: Limite de execuções simultâneas com inferência local;
                se omitido, usa ``MAX_LOCAL_LLM_CONCURRENT``.
        """
        self._health = health or PiHealthMonitor()
        self.limit = max_concurrent if max_concurrent is not None else calculate_dynamic_limit(self._health)
        self._semaphore = asyncio.Semaphore(self.limit)
        self._local_semaphore = asyncio.Semaphore(local_llm_concurrent or MAX_LOCAL_LLM_CONCURRENT)

    @asynccontextmanager
    async def slot(self, provider: str | None = None) -> AsyncIterator[None]:
        """Reserva uma vaga de execução pelo tempo do bloco.

        Args:
            provider: Nome do provedor do agente; ``"ollama"`` exige também a vaga de
                inferência local.

        Raises:
            RuntimeError: Se a saúde do sistema não se recuperar a tempo.
        """
        async with self._semaphore:
            if provider == "ollama":
                async with self._local_semaphore:
                    await self._ensure_healthy()
                    yield
            else:
                await self._ensure_healthy()
                yield

    async def _ensure_healthy(self) -> None:
        if HEALTH_CHECK_ENABLED:
            await wait_for_health(self._health)
