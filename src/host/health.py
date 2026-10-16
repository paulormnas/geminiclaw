"""Monitor de recursos multiplataforma (Linux e macOS) sobre ``psutil`` (ADR 023 §1.1).

Lê memória, CPU e temperatura sem executar comando externo. Leitura que a plataforma não expõe ou que falha vem como
``None`` (desconhecida): nenhum método devolve valor fixo ou estimado (AGENTS.md §1.6). Quem consome trata ``None``
explicitamente (``src/agent_runtime/resources.py``, telemetria).
"""

from __future__ import annotations

import platform
from typing import Any

import psutil

from src import config
from src.logger import get_logger

logger = get_logger(__name__)

_MB = 1024 * 1024
_CPU_SAMPLE_SECONDS = 0.1

_sensor_warned = False
_thermal_warned = False


class HealthMonitor:
    """Lê memória, CPU e temperatura do computador em que o processo roda.

    O backend é injetável (testes): qualquer objeto com ``virtual_memory()``, ``cpu_percent(interval)`` e,
    opcionalmente, ``sensors_temperatures()`` (ausente em macOS) no formato do ``psutil``.
    """

    def __init__(self, *, backend: Any | None = None, system: str | None = None) -> None:
        self._backend = backend if backend is not None else psutil
        self.system = system or platform.system()

    def get_temperature(self) -> float | None:
        """Temperatura da CPU em °C, ou ``None`` se desconhecida.

        Com ``TEMPERATURE_SENSOR`` vazio vale a maior leitura entre os sensores; com valor, só o sensor de mesmo nome.
        """
        global _sensor_warned
        reader = getattr(self._backend, "sensors_temperatures", None)
        if reader is None:
            return None
        try:
            sensors = reader()
        except Exception as exc:  # noqa: BLE001 - a leitura é opcional: falha vira desconhecida
            logger.debug("Falha ao ler temperatura", extra={"error": str(exc)})
            return None
        if not sensors:
            return None
        wanted = config.TEMPERATURE_SENSOR
        if wanted:
            if wanted not in sensors:
                if not _sensor_warned:
                    _sensor_warned = True
                    logger.warning(
                        "Sensor de temperatura não encontrado",
                        extra={"sensor": wanted, "disponiveis": sorted(sensors)},
                    )
                return None
            entries = list(sensors[wanted])
        else:
            entries = [entry for group in sensors.values() for entry in group]
        values = [float(entry.current) for entry in entries if getattr(entry, "current", None) is not None]
        return max(values) if values else None

    def get_memory_usage(self) -> dict[str, float] | None:
        """Memória em MB (``total_mb``, ``available_mb``, ``percent``), ou ``None`` se desconhecida."""
        try:
            memory = self._backend.virtual_memory()
            return {
                "total_mb": round(memory.total / _MB, 2),
                "available_mb": round(memory.available / _MB, 2),
                "percent": round(float(memory.percent), 2),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falha ao ler memória", extra={"error": str(exc)})
            return None

    def get_cpu_usage(self) -> float | None:
        """Uso da CPU em %, medido em 100 ms, ou ``None`` se desconhecido."""
        try:
            return round(float(self._backend.cpu_percent(interval=_CPU_SAMPLE_SECONDS)), 2)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falha ao ler CPU", extra={"error": str(exc)})
            return None

    def is_throttled(self) -> bool | None:
        """Temperatura frente a ``TEMPERATURE_LIMIT``; ``None`` sem limite configurado ou sem leitura."""
        limit = config.TEMPERATURE_LIMIT
        if limit is None:
            return None
        temperature = self.get_temperature()
        if temperature is None:
            return None
        return temperature >= limit


THERMAL_PROTECTION_OFF_MESSAGE = (
    "Proteção térmica desligada: há sensor de temperatura legível, mas TEMPERATURE_LIMIT não está definido. "
    "Declare TEMPERATURE_LIMIT (°C) no .env."
)


def thermal_protection_warning(monitor: HealthMonitor | None = None) -> str | None:
    """Mensagem de proteção térmica desligada, ou ``None`` se não se aplica.

    Aplica-se no Linux, com temperatura legível e ``TEMPERATURE_LIMIT`` indefinido. Registra ``WARNING`` uma única vez
    por processo; devolve a mensagem em toda chamada aplicável (o REPL a mostra no cabeçalho). Nunca falha.
    """
    global _thermal_warned
    if config.TEMPERATURE_LIMIT is not None:
        return None
    monitor = monitor or HealthMonitor()
    if monitor.system != "Linux" or monitor.get_temperature() is None:
        return None
    if not _thermal_warned:
        _thermal_warned = True
        logger.warning(THERMAL_PROTECTION_OFF_MESSAGE)
    return THERMAL_PROTECTION_OFF_MESSAGE


def reset_warnings_for_tests() -> None:
    """Zera os avisos de uma vez por processo (testes)."""
    global _sensor_warned, _thermal_warned
    _sensor_warned = False
    _thermal_warned = False
