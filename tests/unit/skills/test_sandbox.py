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
