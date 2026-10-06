"""Retorno dos artefatos do sandbox pelo bind mount (ADR 018 §3), sem cópia por ``get_archive``."""

import os
os.environ["LLM_PROVIDER"] = "ollama"
os.environ["GEMINI_API_KEY"] = "dummy"

import io
import tarfile
from unittest.mock import MagicMock, patch

import pytest

from src.skills.code.sandbox import PythonSandbox


@pytest.fixture
def mock_docker_client():
    with patch('src.skills.code.sandbox.docker.from_env') as mock_env:
        client = MagicMock()
        mock_env.return_value = client
        yield client


@pytest.mark.unit
def test_sandbox_bind_mount_transfer(mock_docker_client, tmp_path):
    """Cenário: Sem cópia duplicada. O script entra por put_archive e os artefatos voltam pelo bind mount."""
    sandbox = PythonSandbox(work_dir=str(tmp_path / "work"))

    mock_container = MagicMock()
    output_dir = tmp_path / "outputs"
    session_id = "test_session"
    task_name = "test_task"
    task_dir = output_dir / session_id / task_name

    def run_container(**kwargs):
        # O que o código no container faria: gravar em /outputs (a pasta do host montada).
        (task_dir / "result.txt").write_text("artifact content")
        return mock_container

    mock_docker_client.containers.run.side_effect = run_container
    mock_container.exec_run.return_value = MagicMock(output=(b"hello world\n", b""), exit_code=0)

    result = sandbox.run(
        code="print('hello world')",
        session_id=session_id,
        task_name=task_name,
        output_dir=str(output_dir),
    )

    # 1. O volume mapeia a pasta da subtarefa do host para /outputs, com leitura e escrita
    run_kwargs = mock_docker_client.containers.run.call_args[1]
    host_path = str(task_dir.resolve())
    assert run_kwargs["volumes"][host_path] == {"bind": "/outputs", "mode": "rw"}
    assert len(run_kwargs["volumes"]) == 1  # sem pacotes, não há /deps

    # 2. O script é injetado por put_archive, com o dono do orquestrador
    mock_container.put_archive.assert_called_once()
    path_arg, data_arg = mock_container.put_archive.call_args[0]
    assert path_arg == "/outputs"
    with tarfile.open(fileobj=io.BytesIO(data_arg), mode='r') as tar:
        assert "script.py" in tar.getnames()
        member = tar.getmember("script.py")
        assert (member.uid, member.gid) == (os.getuid(), os.getgid())
        assert member.mode == 0o644
        assert tar.extractfile("script.py").read().decode() == "print('hello world')"

    # 3. Os artefatos não são copiados de volta por get_archive
    mock_container.get_archive.assert_not_called()

    # 4. O artefato gravado pelo bind mount é reportado
    assert (task_dir / "result.txt").read_text() == "artifact content"
    assert result.stdout == "hello world\n"
    assert "result.txt" in result.artifacts
    mock_container.remove.assert_called()


@pytest.mark.unit
def test_sandbox_does_not_open_permissions(mock_docker_client, tmp_path):
    """Cenário: Dono dos artefatos. A pasta da subtarefa segue a umask do usuário, sem chmod 777."""
    sandbox = PythonSandbox(work_dir=str(tmp_path / "work"))
    container = MagicMock()
    container.exec_run.return_value = MagicMock(output=(b"", b""), exit_code=0)
    mock_docker_client.containers.run.return_value = container

    previous = os.umask(0o022)
    try:
        with patch("src.skills.code.sandbox.os.chmod") as chmod:
            sandbox.run(code="pass", session_id="s", task_name="t", output_dir=str(tmp_path / "out"))
    finally:
        os.umask(previous)

    chmod.assert_not_called()
    mode = (tmp_path / "out" / "s" / "t").stat().st_mode & 0o777
    assert mode == 0o755  # umask 022 aplicada; sem escrita para outros
    for call in container.exec_run.call_args_list:
        cmd = call.args[0] if call.args else call.kwargs.get("cmd")
        assert "chmod" not in str(cmd) and "chown" not in str(cmd)
