"""Endurecimento do retorno de artefatos e da instalação de pacotes do sandbox.

Revisão de segurança STRIDE (v16-in-process-agents, 6.1; v16-sandbox-slim-image): o conteúdo
que o container grava em ``/outputs`` aparece no host pelo bind mount, então links simbólicos
para fora da pasta da tarefa precisam ser removidos, e uma instalação de pacotes que trava não
pode prender a thread do sandbox.
"""

import os
import stat
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.skills.code.sandbox import PythonSandbox, _purge_escaping_symlinks


@pytest.fixture
def sandbox(tmp_path: Path):
    with patch("src.skills.code.sandbox.docker.from_env") as mock_env:
        mock_env.return_value = MagicMock()
        yield PythonSandbox(work_dir=str(tmp_path / "work"))


@pytest.mark.unit
class TestPurgeEscapingSymlinks:
    def test_removes_only_links_that_leave_the_task_dir(self, tmp_path: Path) -> None:
        task = tmp_path / "tarefa"
        (task / "sub").mkdir(parents=True)
        outside = tmp_path / "host.txt"
        outside.write_text("segredo")
        (task / "real.txt").write_text("ok")
        (task / "sub" / "interno").symlink_to(task / "real.txt")  # fica dentro: preservado
        (task / "ataque").symlink_to(outside)  # arquivo do host
        (task / "sub" / "sobe").symlink_to("../../host.txt")  # relativo que escapa
        (task / "dir_ataque").symlink_to(tmp_path)  # diretório fora da tarefa

        removed = _purge_escaping_symlinks(task)

        assert sorted(removed) == ["ataque", "dir_ataque", os.path.join("sub", "sobe")]
        assert (task / "sub" / "interno").is_symlink()
        assert (task / "real.txt").read_text() == "ok"
        assert outside.read_text() == "segredo"

    def test_run_removes_symlink_created_through_the_bind_mount(
        self, sandbox: PythonSandbox, tmp_path: Path
    ) -> None:
        """Cenário: Symlink que escapa. O container escreve direto na pasta do host (bind mount)."""
        outside = tmp_path / "host_secret.txt"
        outside.write_text("segredo")
        outside.chmod(0o600)
        task_dir = tmp_path / "out" / "s" / "t"

        container = MagicMock()

        def run_container(**kwargs):
            (task_dir / "ataque").symlink_to(outside)  # o que o código no container faria
            (task_dir / "legitimo.txt").write_text("ok")
            return container

        sandbox.client.containers.run.side_effect = run_container
        container.exec_run.return_value = MagicMock(output=(b"", b""), exit_code=0)

        result = sandbox.run(code="pass", session_id="s", task_name="t", output_dir=str(tmp_path / "out"))

        assert not (task_dir / "ataque").is_symlink()
        assert (task_dir / "legitimo.txt").read_text() == "ok"
        assert stat.S_IMODE(os.stat(outside).st_mode) == 0o600
        assert "ataque" not in result.artifacts


@pytest.mark.unit
class TestSetupTimeout:
    def test_hung_package_install_is_killed_and_reported(self, tmp_path: Path) -> None:
        """Cenário: `uv pip install` trava (mirror lento); a thread não pode ficar presa."""
        killed = threading.Event()
        container = MagicMock()
        container.kill.side_effect = lambda: killed.set()

        def exec_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and cmd[:3] == ["uv", "pip", "install"]:
                killed.wait(timeout=10)  # só destrava quando o timer mata o container
                raise RuntimeError("container morto durante a instalação")
            return MagicMock(output=(b"", b""), exit_code=0)

        container.exec_run.side_effect = exec_run

        # O cliente do daemon é criado sob demanda (no primeiro uso), então o patch
        # precisa continuar ativo durante o run().
        with patch("src.skills.code.sandbox.docker.from_env") as mock_env:
            client = MagicMock()
            client.containers.run.return_value = container
            mock_env.return_value = client
            sandbox = PythonSandbox(setup_timeout=1, work_dir=str(tmp_path / "work"))

            result = sandbox.run(
                code="pass",
                session_id="s",
                task_name="t",
                output_dir=str(tmp_path),
                packages=["tabulate"],
            )

        assert killed.is_set()
        assert result.timed_out is True
        assert result.install_failed is True
        assert result.exit_code == -1
        assert "instalação dos pacotes" in result.stderr
        container.remove.assert_called()
