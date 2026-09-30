"""Amostrador de CPU, memória e temperatura para o benchmark (Linux / Raspberry Pi 5).

Lê direto de ``/proc`` e ``/sys``, sem dependências. A telemetria do projeto
(``hardware_snapshots``) grava uma amostra por subtarefa e o uso de CPU sai zerado, então não serve
para medir picos; este amostrador roda em outra thread, a cada ``interval`` segundos, durante a
execução inteira do benchmark.

Grandezas por amostra:
- CPU do sistema (%), média de todos os núcleos;
- memória usada do sistema (MB e %), ``MemTotal - MemAvailable``;
- temperatura da CPU (°C) e estado de *throttling* (``vcgencmd get_throttled``);
- CPU (% de um núcleo) e memória residente (MB) da árvore de processos do benchmark.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

# Bits de `vcgencmd get_throttled` (Raspberry Pi).
THROTTLE_BITS = {
    0x1: "subtensão agora",
    0x2: "frequência limitada agora",
    0x4: "throttling agora",
    0x8: "limite de temperatura agora",
    0x10000: "subtensão ocorreu",
    0x20000: "frequência limitada ocorreu",
    0x40000: "throttling ocorreu",
    0x80000: "limite de temperatura ocorreu",
}


# ----------------------------------------------------------------------------- leitores puros


def parse_cpu_times(stat_text: str) -> tuple[int, int]:
    """Extrai ``(total, ocioso)`` em jiffies da primeira linha (``cpu``) de ``/proc/stat``."""
    fields = [int(x) for x in stat_text.splitlines()[0].split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
    return sum(fields[:8]), idle


def parse_meminfo(meminfo_text: str) -> tuple[float, float]:
    """Extrai ``(total_mb, disponivel_mb)`` de ``/proc/meminfo``."""
    values = {}
    for line in meminfo_text.splitlines():
        key, _, rest = line.partition(":")
        if key in ("MemTotal", "MemAvailable"):
            values[key] = int(rest.split()[0]) / 1024.0
    return values["MemTotal"], values["MemAvailable"]


def parse_throttled(output: str) -> int | None:
    """Interpreta a saída de ``vcgencmd get_throttled`` (``throttled=0x50005``)."""
    _, _, value = output.strip().partition("=")
    try:
        return int(value, 16)
    except ValueError:
        return None


def describe_throttled(flags: int | None) -> list[str]:
    """Nomes legíveis dos bits ligados em ``flags``."""
    if not flags:
        return []
    return [name for bit, name in THROTTLE_BITS.items() if flags & bit]


def parse_proc_stat(stat_text: str) -> tuple[int, int, int]:
    """De ``/proc/<pid>/stat`` devolve ``(ppid, utime + stime, rss_paginas)``.

    O nome do processo fica entre parênteses e pode conter espaços; por isso o corte é feito
    depois do último ``)``.
    """
    after = stat_text[stat_text.rindex(")") + 2 :].split()
    ppid = int(after[1])
    jiffies = int(after[11]) + int(after[12])
    rss_pages = int(after[21])
    return ppid, jiffies, rss_pages


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text()
    except OSError:
        return None


def read_temperature_c() -> float | None:
    raw = _read("/sys/class/thermal/thermal_zone0/temp")
    return int(raw) / 1000.0 if raw and raw.strip().lstrip("-").isdigit() else None


def read_throttled() -> int | None:
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_throttled(out)


def process_tree(root_pid: int) -> dict[int, tuple[int, int]]:
    """Processos descendentes de ``root_pid`` (inclusive): ``{pid: (jiffies, rss_paginas)}``."""
    children: dict[int, list[int]] = {}
    stats: dict[int, tuple[int, int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        text = _read(f"/proc/{entry}/stat")
        if not text:
            continue
        try:
            ppid, jiffies, rss = parse_proc_stat(text)
        except (ValueError, IndexError):
            continue
        pid = int(entry)
        children.setdefault(ppid, []).append(pid)
        stats[pid] = (jiffies, rss)
    tree, stack = {}, [root_pid]
    while stack:
        pid = stack.pop()
        if pid in stats and pid not in tree:
            tree[pid] = stats[pid]
            stack.extend(children.get(pid, []))
    return tree


# ----------------------------------------------------------------------------- amostrador


class ResourceSampler(threading.Thread):
    """Coleta amostras de recursos até ``stop()`` e resume os picos e as médias."""

    def __init__(
        self,
        root_pid: int | None = None,
        interval: float = 1.0,
        *,
        read_stat: Callable[[], str | None] = lambda: _read("/proc/stat"),
        read_mem: Callable[[], str | None] = lambda: _read("/proc/meminfo"),
        read_temp: Callable[[], float | None] = read_temperature_c,
        read_throttle: Callable[[], int | None] = read_throttled,
        read_tree: Callable[[int], dict[int, tuple[int, int]]] = process_tree,
        clock: Callable[[], float] = time.monotonic,
        clock_ticks: int | None = None,
        page_size: int | None = None,
        throttle_every: float = 5.0,
    ) -> None:
        super().__init__(daemon=True, name="resource-sampler")
        self.root_pid = root_pid
        self.interval = interval
        self.samples: list[dict] = []
        self._stop_event = threading.Event()
        self._read_stat, self._read_mem = read_stat, read_mem
        self._read_temp, self._read_throttle, self._read_tree = read_temp, read_throttle, read_tree
        self._clock = clock
        self._ticks = clock_ticks or os.sysconf("SC_CLK_TCK")
        self._page = page_size or os.sysconf("SC_PAGE_SIZE")
        self._throttle_every = throttle_every
        self._flags_seen = 0

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        prev_cpu = self._cpu_times()
        prev_jiffies: dict[int, int] = {}
        prev_t = self._clock()
        start = prev_t
        last_throttle = float("-inf")
        while not self._stop_event.wait(self.interval):
            now = self._clock()
            dt = max(now - prev_t, 1e-6)
            sample: dict = {"t": round(now - start, 2)}

            cpu = self._cpu_times()
            if cpu and prev_cpu and cpu[0] > prev_cpu[0]:
                busy = (cpu[0] - prev_cpu[0]) - (cpu[1] - prev_cpu[1])
                sample["sys_cpu_pct"] = round(100.0 * busy / (cpu[0] - prev_cpu[0]), 1)
            prev_cpu = cpu or prev_cpu

            mem = self._memory()
            if mem:
                total, available = mem
                sample["mem_used_mb"] = round(total - available, 1)
                sample["mem_used_pct"] = round(100.0 * (total - available) / total, 1)

            sample["temp_c"] = self._read_temp()
            if now - last_throttle >= self._throttle_every:
                flags = self._read_throttle()
                last_throttle = now
                if flags is not None:
                    self._flags_seen |= flags
                    sample["throttled_flags"] = flags

            if self.root_pid is not None:
                tree = self._read_tree(self.root_pid)
                current = {pid: j for pid, (j, _r) in tree.items()}
                delta = sum(max(j - prev_jiffies.get(pid, 0), 0) for pid, j in current.items())
                sample["proc_cpu_pct"] = round(100.0 * delta / (self._ticks * dt), 1)  # % de um núcleo
                sample["proc_rss_mb"] = round(sum(r for _j, r in tree.values()) * self._page / 1048576, 1)
                sample["proc_count"] = len(tree)
                prev_jiffies = current

            self.samples.append(sample)
            prev_t = now

    def _cpu_times(self) -> tuple[int, int] | None:
        text = self._read_stat()
        return parse_cpu_times(text) if text else None

    def _memory(self) -> tuple[float, float] | None:
        text = self._read_mem()
        return parse_meminfo(text) if text else None

    def summary(self) -> dict:
        """Picos e médias por grandeza, mais os avisos de throttling vistos."""

        def stats(key: str) -> dict | None:
            values = [s[key] for s in self.samples if s.get(key) is not None]
            if not values:
                return None
            return {"max": max(values), "mean": round(sum(values) / len(values), 1)}

        return {
            "samples": len(self.samples),
            "interval_s": self.interval,
            "duration_s": self.samples[-1]["t"] if self.samples else 0,
            "sys_cpu_pct": stats("sys_cpu_pct"),
            "mem_used_mb": stats("mem_used_mb"),
            "mem_used_pct": stats("mem_used_pct"),
            "temp_c": stats("temp_c"),
            "proc_cpu_pct_of_one_core": stats("proc_cpu_pct"),
            "proc_rss_mb": stats("proc_rss_mb"),
            "max_processes": max((s.get("proc_count", 0) for s in self.samples), default=0),
            "throttled_flags": self._flags_seen,
            "throttled": describe_throttled(self._flags_seen),
        }
