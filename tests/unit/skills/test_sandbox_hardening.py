"""Endurecimento do retorno de artefatos e da instalação de pacotes do sandbox.

Revisão de segurança STRIDE (v16-in-process-agents, 6.1): o conteúdo devolvido pelo
container vem de código gerado por LLM e é extraído no host, então o tar não pode
escrever fora da pasta da tarefa nem alterar permissões de arquivos externos.
"""

import io
import os
import stat
import tarfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.skills.code.sandbox import PythonSandbox, _is_safe_tar_member, _purge_escaping_symlinks


@pytest.fixture
def sandbox():
    with patch("src.skills.code.sandbox.docker.from_env") as mock_env:
        mock_env.return_value = MagicMock()
        yield PythonSandbox()


def _member(name: str, kind: bytes = tarfile.REGTYPE, linkname: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = kind
    info.linkname = linkname
    info.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
    return info


@pytest.mark.unit
class TestIsSafeTarMember:
    @pytest.mark.parametrize(
        "name,kind,linkname",
        [
            ("outputs/resultado.csv", tarfile.REGTYPE, ""),
            ("outputs/graficos", tarfile.DIRTYPE, ""),
            ("outputs/atalho.txt", tarfile.SYMTYPE, "resultado.csv"),  # link relativo interno
            ("outputs/copia.csv", tarfile.LNKTYPE, "outputs/resultado.csv"),  # link físico interno
        ],
    )
    def test_safe_members_are_accepted(self, tmp_path: Path, name, kind, linkname) -> None:
        assert _is_safe_tar_member(_member(name, kind, linkname), tmp_path) is True

    @pytest.mark.parametrize(
        "name,kind,linkname",
        [
            ("../fora.txt", tarfile.REGTYPE, ""),
            ("outputs/../../fora.txt", tarfile.REGTYPE, ""),
            ("/etc/cron.d/job", tarfile.REGTYPE, ""),
            ("outputs/passwd", tarfile.SYMTYPE, "/etc/passwd"),  # link absoluto
            ("outputs/sobe", tarfile.SYMTYPE, "../../../etc/passwd"),  # link relativo que escapa
            ("outputs/dur", tarfile.LNKTYPE, "../../segredo"),  # link físico que escapa
            ("outputs/dev", tarfile.CHRTYPE, ""),  # dispositivo
            ("outputs/fifo", tarfile.FIFOTYPE, ""),
        ],
    )
    def test_dangerous_members_are_rejected(self, tmp_path: Path, name, kind, linkname) -> None:
        assert _is_safe_tar_member(_member(name, kind, linkname), tmp_path) is False


def _tar_bytes(entries: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for info, data in entries:
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)
    return buf.getvalue()


@pytest.mark.unit
class TestExtractTarArchive:
    def test_extracts_only_safe_members(self, sandbox: PythonSandbox, tmp_path: Path) -> None:
        dest = tmp_path / "tarefa"
        dest.mkdir()
        outside = tmp_path / "segredo.txt"
        outside.write_text("original")

        entries = [
            (_member("outputs", tarfile.DIRTYPE), None),
            (_member("outputs/ok.txt"), b"conteudo"),
            (_member("../escapou.txt"), b"x"),
            (_member("outputs/atalho", tarfile.SYMTYPE, str(outside)), None),
        ]
        sandbox._extract_tar_archive(iter([_tar_bytes(entries)]), dest)

        assert (dest / "outputs" / "ok.txt").read_text() == "conteudo"
        assert not (tmp_path / "escapou.txt").exists()
        assert not (dest / "outputs" / "atalho").exists()
        assert outside.read_text() == "original"


@pytest.mark.unit
class TestRunDoesNotTouchFilesOutsideSession:
    def test_escaping_symlink_never_changes_outside_permissions(
        self, sandbox: PythonSandbox, tmp_path: Path
    ) -> None:
        """Cenário: código no sandbox cria um symlink para um arquivo do host."""
        outside = tmp_path / "host_secret.txt"
        outside.write_text("segredo")
        outside.chmod(0o600)

        container = MagicMock()
        sandbox.client.containers.run.return_value = container
        result_exec = MagicMock()
        result_exec.output = (b"", b"")
        result_exec.exit_code = 0
        container.exec_run.return_value = result_exec
        container.get_archive.return_value = (
            iter([_tar_bytes([
                (_member("outputs", tarfile.DIRTYPE), None),
                (_member("outputs/ataque", tarfile.SYMTYPE, str(outside)), None),
                (_member("outputs/legitimo.txt"), b"ok"),
            ])]),
            MagicMock(),
        )

        result = sandbox.run(code="pass", session_id="s", task_name="t", output_dir=str(tmp_path / "out"))

        assert stat.S_IMODE(os.stat(outside).st_mode) == 0o600
        task_dir = tmp_path / "out" / "s" / "t"
        assert not (task_dir / "ataque").exists()
        assert (task_dir / "legitimo.txt").read_text() == "ok"
        assert "legitimo.txt" in result.artifacts


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
        """O container escreve direto na pasta do host (bind mount), sem passar pelo tar."""
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
        container.get_archive.side_effect = RuntimeError("sem tar neste teste")

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
            sandbox = PythonSandbox(setup_timeout=1)

            result = sandbox.run(
                code="pass",
                session_id="s",
                task_name="t",
                output_dir=str(tmp_path),
                setup_commands=[["uv", "pip", "install", "pandas"]],
            )

        assert killed.is_set()
        assert result.timed_out is True
        assert result.exit_code == -1
        assert "instalação de pacotes" in result.stderr
        container.remove.assert_called()
