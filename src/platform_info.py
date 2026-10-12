"""Identificação da plataforma de execução (v16-platform-images, design §2; ADR 018 §5).

Detecta sistema operacional e arquitetura do host, a arquitetura do **daemon** de containers (o alvo das imagens: no
macOS o Docker Desktop roda uma VM Linux), a placa (Raspberry Pi 5) e o tamanho de página. As funções são puras: recebem
as fontes (texto do ``device-tree``, ``info()`` do daemon) como argumentos, para teste sem hardware.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEVICE_TREE_MODEL = Path("/proc/device-tree/model")
_ARCH_ALIASES = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64", "x64": "amd64"}
_BASE_PAGE_SIZE = 4096


def normalize_arch(value: str | None) -> str | None:
    """``aarch64`` vira ``arm64``, ``x86_64`` vira ``amd64``; outras passam em minúsculas; vazio vira ``None``."""
    if not value:
        return None
    key = value.strip().lower()
    return _ARCH_ALIASES.get(key, key)


def detect_board(device_tree_text: str | None) -> str | None:
    """``"pi5"`` quando o texto do ``device-tree`` indica um Raspberry Pi 5; ``None`` caso contrário."""
    if device_tree_text and "raspberry pi 5" in device_tree_text.replace("\x00", "").lower():
        return "pi5"
    return None


@dataclass(frozen=True)
class PlatformInfo:
    """Plataforma de execução. ``daemon_arch`` é ``None`` quando o daemon de containers não foi consultado."""

    host_os: str
    host_arch: str | None
    daemon_os: str | None
    daemon_arch: str | None
    board: str | None
    page_size: int | None

    @property
    def target(self) -> str | None:
        """Plataforma alvo das imagens (``linux/<arquitetura do daemon>``), ou ``None`` sem daemon."""
        if not self.daemon_os or not self.daemon_arch:
            return None
        return f"{self.daemon_os}/{self.daemon_arch}"

    @property
    def id(self) -> str:
        """Identificador usado em ``validada_em``: ``linux/arm64/pi5/16k``, ``linux/arm64`` ou ``linux/amd64``.

        Placa e tamanho de página só entram quando relevantes (Pi e página diferente de 4K), pois foram o que causou
        falha real (ADR 018 §4). Sem daemon, usa a arquitetura do host.
        """
        parts = [self.daemon_os or "linux", self.daemon_arch or self.host_arch or "desconhecida"]
        if self.board:
            parts.append(self.board)
        if self.page_size and self.page_size != _BASE_PAGE_SIZE:
            parts.append(f"{self.page_size // 1024}k")
        return "/".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "id": self.id, "target": self.target}


def detect_platform(
    *,
    system: str | None = None,
    machine: str | None = None,
    device_tree_text: str | None = None,
    page_size: int | None = None,
    daemon_info: Mapping[str, Any] | None = None,
) -> PlatformInfo:
    """Monta o :class:`PlatformInfo` a partir das fontes dadas (padrão: o sistema atual).

    Args:
        system: ``platform.system()``.
        machine: ``platform.machine()``.
        device_tree_text: Conteúdo de ``/proc/device-tree/model``.
        page_size: ``os.sysconf("SC_PAGE_SIZE")`` (Linux).
        daemon_info: ``client.info()`` do daemon de containers; ``None`` se não consultado.
    """
    host_os = (system if system is not None else platform.system()).lower()
    host_arch = normalize_arch(machine if machine is not None else platform.machine())
    daemon_os = None
    daemon_arch = None
    if daemon_info:
        daemon_os = str(daemon_info.get("OSType") or "linux").lower()
        daemon_arch = normalize_arch(str(daemon_info.get("Architecture") or ""))
    return PlatformInfo(
        host_os=host_os,
        host_arch=host_arch,
        daemon_os=daemon_os,
        daemon_arch=daemon_arch,
        board=detect_board(device_tree_text),
        page_size=page_size if host_os == "linux" else None,
    )


def read_device_tree(path: Path = DEVICE_TREE_MODEL) -> str | None:
    """Texto do ``device-tree`` (``None`` fora de uma placa com ``device-tree``)."""
    try:
        return path.read_text(errors="ignore")
    except OSError:
        return None


def read_page_size() -> int | None:
    """Tamanho de página do host (Linux); ``None`` onde ``SC_PAGE_SIZE`` não existe."""
    try:
        return int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, ValueError, OSError):
        return None


def detect_current(daemon_info: Mapping[str, Any] | None = None) -> PlatformInfo:
    """Detecta a plataforma do processo atual (lê ``device-tree`` e o tamanho de página reais)."""
    return detect_platform(
        device_tree_text=read_device_tree(), page_size=read_page_size(), daemon_info=daemon_info
    )
