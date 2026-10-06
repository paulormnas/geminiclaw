"""Cenários da v16-sandbox-slim-image que exigem a imagem real (Mac e Raspberry Pi 5).

Pulados quando não há daemon de containers ou quando a imagem ``SANDBOX_IMAGE`` não foi construída
(``bash scripts/build_images.sh``). Os pacotes sob demanda exigem rede do daemon.
"""

import os
import stat
from pathlib import Path

import docker
import pytest

from src import config
from src.skills.code.sandbox import PythonSandbox


def _image_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        client.images.get(config.SANDBOX_IMAGE)
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _image_available(),
        reason="Daemon de containers inacessível ou imagem do sandbox ausente (bash scripts/build_images.sh).",
    ),
]


def _run(tmp_path: Path, code: str, **kwargs):
    sandbox = PythonSandbox(work_dir=str(tmp_path / "work"))
    return sandbox.run(code=code, session_id="s", task_name="t", output_dir=str(tmp_path / "out"), **kwargs)


def test_conteudo_da_imagem(tmp_path: Path) -> None:
    """Cenário: Conteúdo da imagem. Sem código do projeto nem extras; conjunto básico importa sem rede."""
    code = (
        "import importlib.metadata as m, importlib.util, os\n"
        "assert not os.path.exists('/app/src') and not os.path.exists('/app/agents')\n"
        "for dist in ('docling', 'qdrant-client', 'google-genai', 'anthropic', 'fastembed'):\n"
        "    try:\n"
        "        m.version(dist)\n"
        "    except m.PackageNotFoundError:\n"
        "        continue\n"
        "    raise SystemExit(f'distribuição indevida: {dist}')\n"
        "import numpy, pandas, scipy, matplotlib, sklearn, seaborn\n"
        "print('ok')\n"
    )
    result = _run(tmp_path, code)
    assert result.exit_code == 0, result.stderr
    assert "ok" in result.stdout


def test_escrita_fora_das_areas_permitidas(tmp_path: Path) -> None:
    """Cenário: Escrita fora das áreas permitidas. Só /outputs, /deps e /tmp aceitam escrita."""
    code = (
        "import pathlib\n"
        "for bad in ('/opt/sandbox-venv/x', '/etc/x'):\n"
        "    try:\n"
        "        pathlib.Path(bad).write_text('x')\n"
        "    except OSError:\n"
        "        continue\n"
        "    raise SystemExit(f'gravou em {bad}')\n"
        "for ok in ('/outputs/ok.txt', '/tmp/ok.txt'):\n"
        "    pathlib.Path(ok).write_text('x')\n"
        "print('ok')\n"
    )
    result = _run(tmp_path, code)
    assert result.exit_code == 0, result.stderr


def test_dono_e_modo_dos_artefatos(tmp_path: Path) -> None:
    """Cenário: Dono dos artefatos. Pertence ao usuário do orquestrador, sem escrita para outros."""
    result = _run(tmp_path, "open('/outputs/grafico.png', 'wb').write(b'x')")
    assert result.exit_code == 0, result.stderr
    artifact = tmp_path / "out" / "s" / "t" / "grafico.png"
    info = artifact.stat()
    assert info.st_uid == os.getuid()
    assert not stat.S_IMODE(info.st_mode) & 0o002


def test_symlink_que_escapa(tmp_path: Path) -> None:
    """Cenário: Symlink que escapa. O link para fora é removido da pasta da subtarefa."""
    result = _run(tmp_path, "import os; os.symlink('/etc/passwd', '/outputs/link')")
    assert result.exit_code == 0, result.stderr
    assert not (tmp_path / "out" / "s" / "t" / "link").is_symlink()


def test_pacote_inexistente(tmp_path: Path) -> None:
    """Cenário: Pacote inexistente. O script não roda e o resultado traz install_failed."""
    result = _run(tmp_path, "print('nao deveria rodar')", packages=["pacote-que-nao-existe-123"])
    assert result.install_failed is True
    assert "pacote-que-nao-existe-123" in result.stderr
    assert "nao deveria rodar" not in result.stdout


def test_pacote_real_instalado_e_sem_rede_no_script(tmp_path: Path) -> None:
    """Cenários: Pacotes registrados e Desconexão antes do script (socket para fora falha)."""
    code = (
        "import socket, tabulate\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "except OSError:\n"
        "    print('sem rede')\n"
        "else:\n"
        "    raise SystemExit('rede disponível no script')\n"
    )
    result = _run(tmp_path, code, packages=["tabulate"])
    assert result.exit_code == 0, result.stderr
    assert "sem rede" in result.stdout
    assert any(p.startswith("tabulate==") for p in result.packages_installed)
    assert not any((tmp_path / "work").iterdir())
