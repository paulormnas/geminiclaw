"""Detecção de plataforma (v16-platform-images, cenários 6.1)."""

from __future__ import annotations

import pytest

from src.host.platform_info import detect_board, detect_platform, normalize_arch

pytestmark = pytest.mark.unit

PI5 = "Raspberry Pi 5 Model B Rev 1.0\x00"


def test_raspberry_pi_5() -> None:
    info = detect_platform(system="Linux", machine="aarch64", device_tree_text=PI5, page_size=16384,
                           daemon_info={"OSType": "linux", "Architecture": "aarch64"})
    assert info.id == "linux/arm64/pi5/16k" and info.target == "linux/arm64" and info.board == "pi5"


def test_macos_com_docker_desktop_usa_a_arquitetura_do_daemon() -> None:
    info = detect_platform(system="Darwin", machine="arm64", page_size=16384,
                           daemon_info={"OSType": "linux", "Architecture": "aarch64"})
    assert info.host_os == "darwin" and info.target == "linux/arm64" and info.id == "linux/arm64"
    assert info.page_size is None  # a página do host macOS não vale para a VM


def test_linux_x86_64() -> None:
    info = detect_platform(system="Linux", machine="x86_64", page_size=4096,
                           daemon_info={"OSType": "linux", "Architecture": "x86_64"})
    assert info.id == "linux/amd64" and info.host_arch == "amd64"


def test_daemon_diferente_do_host_vale_o_daemon() -> None:
    info = detect_platform(system="Linux", machine="x86_64", page_size=4096,
                           daemon_info={"OSType": "linux", "Architecture": "aarch64"})
    assert info.target == "linux/arm64"


def test_sem_daemon_nao_ha_alvo_e_o_id_usa_o_host() -> None:
    info = detect_platform(system="Linux", machine="aarch64", page_size=4096)
    assert info.target is None and info.id == "linux/arm64"


def test_pagina_diferente_de_4k_entra_no_id_fora_do_pi() -> None:
    info = detect_platform(system="Linux", machine="aarch64", page_size=16384,
                           daemon_info={"OSType": "linux", "Architecture": "aarch64"})
    assert info.id == "linux/arm64/16k"


def test_pi5_com_pagina_de_4k_nao_inclui_o_tamanho() -> None:
    info = detect_platform(system="Linux", machine="aarch64", device_tree_text=PI5, page_size=4096,
                           daemon_info={"OSType": "linux", "Architecture": "aarch64"})
    assert info.id == "linux/arm64/pi5"


@pytest.mark.parametrize("raw, expected", [("aarch64", "arm64"), ("ARM64", "arm64"), ("x86_64", "amd64"),
                                           ("amd64", "amd64"), ("s390x", "s390x"), ("", None), (None, None)])
def test_normalizacao_de_arquitetura(raw, expected) -> None:
    assert normalize_arch(raw) == expected


def test_placa_so_para_pi5() -> None:
    assert detect_board("Raspberry Pi 4 Model B") is None and detect_board(None) is None
    assert detect_board(PI5) == "pi5"


def test_modulo_platform_utils_foi_removido() -> None:
    """Cenário "Módulo removido": nada importa ``src.platform_utils``."""
    import importlib.util
    from pathlib import Path

    assert importlib.util.find_spec("src.platform_utils") is None
    src = Path(__file__).resolve().parents[3] / "src"
    assert not [p for p in src.rglob("*.py") if "platform_utils" in p.read_text(encoding="utf-8")]
