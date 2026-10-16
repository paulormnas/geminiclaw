"""Backend simulado do ``HealthMonitor`` no formato do ``psutil`` (v18.7-resource-monitor-config).

Memória, CPU e sensores de temperatura roteirizados por chamada, plataforma sem ``sensors_temperatures`` (como o macOS)
e leituras que levantam exceção. Nenhuma chamada ao sistema. Reutilizado pelas mudanças V18.7 seguintes.
"""

from __future__ import annotations

from collections import namedtuple
from collections.abc import Sequence

MB = 1024 * 1024
Memory = namedtuple("Memory", "total available percent")
Temp = namedtuple("Temp", "label current high critical")


class FakePsutilBackend:
    """Imita o módulo ``psutil`` para o monitor.

    Args:
        total_mb: Memória total simulada.
        available_mb: Memória disponível simulada; uma lista é consumida uma leitura por chamada (a última se repete).
        cpu: Uso de CPU simulado (% ou lista, como a memória).
        temperatures: ``None`` = plataforma sem ``sensors_temperatures`` (macOS); mapa sensor -> temperatura (°C, ou
            lista de leituras sucessivas) simula o Linux.
        memory_error: A leitura de memória levanta ``OSError``.
        cpu_error: A leitura de CPU levanta ``OSError``.
        temperature_error: ``sensors_temperatures()`` levanta ``OSError``.
    """

    def __init__(
        self,
        *,
        total_mb: float = 8192.0,
        available_mb: float | Sequence[float] = 4096.0,
        cpu: float | Sequence[float] = 20.0,
        temperatures: dict[str, float | Sequence[float]] | None = None,
        memory_error: bool = False,
        cpu_error: bool = False,
        temperature_error: bool = False,
    ) -> None:
        self._total_mb = total_mb
        self._available = list(available_mb) if isinstance(available_mb, Sequence) else [available_mb]
        self._cpu = list(cpu) if isinstance(cpu, Sequence) else [cpu]
        self._temperatures = temperatures
        self._memory_error, self._cpu_error, self._temperature_error = memory_error, cpu_error, temperature_error
        self.calls = {"virtual_memory": 0, "cpu_percent": 0, "sensors_temperatures": 0}
        if temperatures is not None:
            self.sensors_temperatures = self._sensors  # só existe quando a plataforma o expõe

    @staticmethod
    def _next(values: list[float], calls: int) -> float:
        return values[min(calls - 1, len(values) - 1)]

    def virtual_memory(self) -> Memory:
        self.calls["virtual_memory"] += 1
        if self._memory_error:
            raise OSError("leitura de memória indisponível (dublê)")
        available = self._next(self._available, self.calls["virtual_memory"])
        return Memory(
            total=int(self._total_mb * MB),
            available=int(available * MB),
            percent=(self._total_mb - available) / self._total_mb * 100.0,
        )

    def cpu_percent(self, interval: float | None = None) -> float:
        self.calls["cpu_percent"] += 1
        if self._cpu_error:
            raise OSError("leitura de CPU indisponível (dublê)")
        return self._next(self._cpu, self.calls["cpu_percent"])

    def _sensors(self) -> dict[str, list[Temp]]:
        self.calls["sensors_temperatures"] += 1
        if self._temperature_error:
            raise OSError("sensores indisponíveis (dublê)")
        out: dict[str, list[Temp]] = {}
        for name, value in (self._temperatures or {}).items():
            readings = list(value) if isinstance(value, Sequence) else [value]
            current = self._next(readings, self.calls["sensors_temperatures"])
            out[name] = [Temp(label="", current=current, high=None, critical=None)]
        return out
