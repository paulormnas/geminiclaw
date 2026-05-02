import pytest
from unittest.mock import patch, MagicMock
from src.runner import ContainerRunner

@patch("src.runner.asyncio.Semaphore")
@patch("src.runner.docker.from_env")
@patch("src.runner.PiHealthMonitor")
def test_container_runner_dynamic_limit_6gb(mock_health_class, mock_docker, mock_semaphore):
    """Testa se >= 6GB RAM resulta no limite 3."""
    mock_health = MagicMock()
    # 6GB = 6144 MB
    mock_health.get_memory_usage.return_value = {"available_mb": 6200.0}
    mock_health_class.return_value = mock_health

    runner = ContainerRunner()
    assert mock_semaphore.call_args_list[0].args[0] == 3

@patch("src.runner.asyncio.Semaphore")
@patch("src.runner.docker.from_env")
@patch("src.runner.PiHealthMonitor")
def test_container_runner_dynamic_limit_4gb(mock_health_class, mock_docker, mock_semaphore):
    """Testa se >= 3GB e < 6GB RAM resulta no limite 2."""
    mock_health = MagicMock()
    # 4GB = 4096 MB
    mock_health.get_memory_usage.return_value = {"available_mb": 4096.0}
    mock_health_class.return_value = mock_health

    runner = ContainerRunner()
    assert mock_semaphore.call_args_list[0].args[0] == 2

@patch("src.runner.asyncio.Semaphore")
@patch("src.runner.docker.from_env")
@patch("src.runner.PiHealthMonitor")
def test_container_runner_dynamic_limit_2gb(mock_health_class, mock_docker, mock_semaphore):
    """Testa se < 3GB RAM resulta no limite 1."""
    mock_health = MagicMock()
    # 2GB = 2048 MB
    mock_health.get_memory_usage.return_value = {"available_mb": 2048.0}
    mock_health_class.return_value = mock_health

    runner = ContainerRunner()
    assert mock_semaphore.call_args_list[0].args[0] == 1

@patch("src.runner.asyncio.Semaphore")
@patch("src.runner.docker.from_env")
@patch("src.runner.PiHealthMonitor")
def test_container_runner_dynamic_limit_fallback_macos(mock_health_class, mock_docker, mock_semaphore):
    """Testa se retorna 3 caso a leitura de memória falhe ou retorne None (macOS fallback)."""
    mock_health = MagicMock()
    mock_health.get_memory_usage.return_value = None  # Comportamento no macOS
    mock_health_class.return_value = mock_health

    runner = ContainerRunner()
    assert mock_semaphore.call_args_list[0].args[0] == 3

@patch("src.runner.asyncio.Semaphore")
@patch("src.runner.docker.from_env")
@patch("src.runner.PiHealthMonitor")
def test_container_runner_dynamic_limit_exception(mock_health_class, mock_docker, mock_semaphore):
    """Testa fallback em caso de exceção durante a leitura."""
    mock_health = MagicMock()
    mock_health.get_memory_usage.side_effect = Exception("Erro I/O")
    mock_health_class.return_value = mock_health

    runner = ContainerRunner()
    assert mock_semaphore.call_args_list[0].args[0] == 3
