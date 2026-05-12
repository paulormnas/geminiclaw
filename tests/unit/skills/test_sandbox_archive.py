import os
os.environ["LLM_PROVIDER"] = "ollama"
os.environ["GEMINI_API_KEY"] = "dummy"

import pytest
import io
import tarfile
from unittest.mock import MagicMock, patch, ANY
from src.skills.code.sandbox import PythonSandbox, SandboxResult

@pytest.fixture
def mock_docker_client():
    with patch('src.skills.code.sandbox.docker.from_env') as mock_env:
        client = MagicMock()
        mock_env.return_value = client
        yield client

def test_sandbox_archive_transfer(mock_docker_client, tmp_path):
    sandbox = PythonSandbox()
    
    mock_container = MagicMock()
    mock_docker_client.containers.run.return_value = mock_container
    
    # Mock exec_run for the main script
    mock_exec_result = MagicMock()
    mock_exec_result.output = (b"hello world\n", b"")
    mock_exec_result.exit_code = 0
    mock_container.exec_run.return_value = mock_exec_result
    
    # Mock get_archive to return a dummy tar
    def mock_get_archive(path):
        f = io.BytesIO()
        with tarfile.open(fileobj=f, mode='w') as tar:
            content = b"artifact content"
            info = tarfile.TarInfo(name="result.txt")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        f.seek(0)
        return (iter([f.read()]), MagicMock()) # get_archive returns a tuple (generator, stat)

    mock_container.get_archive.side_effect = mock_get_archive
    
    output_dir = tmp_path / "outputs"
    session_id = "test_session"
    task_name = "test_task"
    
    result = sandbox.run(
        code="print('hello world')",
        session_id=session_id,
        task_name=task_name,
        output_dir=str(output_dir)
    )
    
    # 1. Verify containers.run was called WITHOUT volumes
    run_kwargs = mock_docker_client.containers.run.call_args[1]
    assert "volumes" not in run_kwargs or run_kwargs["volumes"] is None
    
    # 2. Verify put_archive was called to inject the script
    mock_container.put_archive.assert_called_once()
    path_arg, data_arg = mock_container.put_archive.call_args[0]
    assert path_arg == "/outputs"
    
    # Verify script content inside the tar data
    with tarfile.open(fileobj=io.BytesIO(data_arg), mode='r') as tar:
        assert "script.py" in tar.getnames()
        f = tar.extractfile("script.py")
        assert f.read().decode() == "print('hello world')"
    
    # 3. Verify get_archive was called to retrieve results
    mock_container.get_archive.assert_called_with("/outputs")
    
    # 4. Verify artifacts were saved locally
    local_artifact = output_dir / session_id / task_name / "result.txt"
    assert local_artifact.exists()
    assert local_artifact.read_text() == "artifact content"
    
    assert result.stdout == "hello world\n"
    assert "result.txt" in result.artifacts
