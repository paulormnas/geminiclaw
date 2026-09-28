import os
os.environ["LLM_PROVIDER"] = "ollama"
os.environ["GEMINI_API_KEY"] = "dummy"

import pytest
import time
from unittest.mock import MagicMock, patch
from src.skills.code.sandbox import PythonSandbox, SandboxResult

@pytest.fixture
def mock_docker_client():
    with patch('src.skills.code.sandbox.docker.from_env') as mock_env:
        client = MagicMock()
        mock_env.return_value = client
        yield client

def test_sandbox_timeout_real(mock_docker_client):
    sandbox = PythonSandbox(timeout=1)
    
    # Mock container
    mock_container = MagicMock()
    mock_docker_client.containers.run.return_value = mock_container
    mock_container.get_archive.return_value = (iter([b""]), MagicMock())
    
    # Simula exec_run demorando 2 segundos (mais que o timeout de 1 segundo)
    def mock_exec_run(*args, **kwargs):
        time.sleep(1.5)
        mock_result = MagicMock()
        mock_result.output = b"slow"
        mock_result.exit_code = 0
        return mock_result

    mock_container.exec_run.side_effect = mock_exec_run
    
    # Executa o sandbox, deve estourar o timeout e chamar container.kill()
    result = sandbox.run(
        code="import time\ntime.sleep(10)",
        session_id="test_session",
        task_name="test_task",
        output_dir="/tmp/test_outputs"
    )
    
    # container.kill deve ter sido chamado pelo timer
    assert mock_container.kill.called
    assert result.timed_out is True
    assert "Timeout atingido" in result.stderr

def test_sandbox_network_disabled(mock_docker_client):
    sandbox = PythonSandbox()
    
    mock_container = MagicMock()
    mock_docker_client.containers.run.return_value = mock_container
    mock_container.get_archive.return_value = (iter([b""]), MagicMock())
    
    mock_result = MagicMock()
    mock_result.output = b"ok"
    mock_result.exit_code = 0
    mock_container.exec_run.return_value = mock_result
    
    # Sem setup_commands, rede deve estar desabilitada
    sandbox.run(
        code="print('hi')",
        session_id="test_session",
        task_name="test_task",
        output_dir="/tmp/test_outputs"
    )
    
    # Verifica chamadas do run
    run_kwargs = mock_docker_client.containers.run.call_args[1]
    assert run_kwargs["network_disabled"] is True
    
    # Com setup_commands, rede deve estar habilitada
    sandbox.run(
        code="print('hi')",
        session_id="test_session",
        task_name="test_task",
        output_dir="/tmp/test_outputs",
        setup_commands=[["pip", "install", "requests"]]
    )
    
    run_kwargs2 = mock_docker_client.containers.run.call_args[1]
    assert run_kwargs2["network_disabled"] is False


# ---------------------------------------------------------------------------
# Roadmap V15.2 / Spec G2 — injeção de scientific_helpers.py no sandbox
# ---------------------------------------------------------------------------

def test_extra_files_incluidos_no_tar(mock_docker_client, tmp_path):
    """extra_files deve ser incluído no tar enviado ao container junto do script.py."""
    sandbox = PythonSandbox()

    mock_container = MagicMock()
    mock_docker_client.containers.run.return_value = mock_container
    mock_container.get_archive.return_value = (iter([b""]), MagicMock())
    exec_result = MagicMock()
    exec_result.output = (b"ok", b"")
    exec_result.exit_code = 0
    mock_container.exec_run.return_value = exec_result

    sandbox.run(
        code="from scientific_helpers import save_experiment_artifacts",
        session_id="s1",
        task_name="t1",
        output_dir=str(tmp_path),
        extra_files={"scientific_helpers.py": "def save_experiment_artifacts(): pass"},
    )

    put_archive_args = mock_container.put_archive.call_args
    assert put_archive_args is not None
    dest_path, tar_bytes = put_archive_args[0]
    assert dest_path == "/outputs"

    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        names = tar.getnames()
    assert "script.py" in names
    assert "scientific_helpers.py" in names


def test_sem_extra_files_apenas_script_no_tar(mock_docker_client, tmp_path):
    """Sem extra_files, o tar contém apenas script.py (comportamento pré-G2 preservado)."""
    sandbox = PythonSandbox()

    mock_container = MagicMock()
    mock_docker_client.containers.run.return_value = mock_container
    mock_container.get_archive.return_value = (iter([b""]), MagicMock())
    exec_result = MagicMock()
    exec_result.output = (b"ok", b"")
    exec_result.exit_code = 0
    mock_container.exec_run.return_value = exec_result

    sandbox.run(
        code="print('sem libs cientificas')",
        session_id="s1",
        task_name="t1",
        output_dir=str(tmp_path),
    )

    dest_path, tar_bytes = mock_container.put_archive.call_args[0]

    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
        names = tar.getnames()
    assert names == ["script.py"]
