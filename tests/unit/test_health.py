"""Monitor de recursos multiplataforma (v18.7-resource-monitor-config, requisito "Monitor de recursos multiplataforma")."""

from __future__ import annotations

import subprocess

import pytest

from src import config
from src.host.health import HealthMonitor, reset_warnings_for_tests
from tests.support.fake_psutil_backend import FakePsutilBackend

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(config, "TEMPERATURE_LIMIT", None)
    monkeypatch.setattr(config, "TEMPERATURE_SENSOR", "")
    reset_warnings_for_tests()


def test_temperatura_indisponivel_no_macos():
    """Scenario: Temperatura indisponível no macOS (sem ``sensors_temperatures``)."""
    monitor = HealthMonitor(backend=FakePsutilBackend(available_mb=2048.0), system="Darwin")
    assert monitor.get_temperature() is None
    assert monitor.get_memory_usage()["available_mb"] == 2048.0
    assert monitor.is_throttled() is None


def test_nenhum_valor_fixo_no_macos():
    monitor = HealthMonitor(backend=FakePsutilBackend(total_mb=16384.0, available_mb=1000.0, cpu=3.5), system="Darwin")
    assert monitor.get_memory_usage() == {"total_mb": 16384.0, "available_mb": 1000.0, "percent": 93.9}
    assert monitor.get_cpu_usage() == 3.5


def test_nenhum_subprocesso(monkeypatch):
    """Scenario: Nenhum subprocesso (os quatro métodos, backend Linux simulado)."""
    def boom(*args, **kwargs):
        raise AssertionError("subprocesso criado")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(config, "TEMPERATURE_LIMIT", 75.0)
    monitor = HealthMonitor(backend=FakePsutilBackend(temperatures={"cpu_thermal": 60.0}), system="Linux")
    assert monitor.get_temperature() == 60.0
    assert monitor.get_memory_usage() is not None
    assert monitor.get_cpu_usage() == 20.0
    assert monitor.is_throttled() is False


def test_leitura_de_memoria_que_falha():
    """Scenario: Leitura de memória que falha (nunca o antigo valor fixo)."""
    assert HealthMonitor(backend=FakePsutilBackend(memory_error=True)).get_memory_usage() is None


def test_leitura_de_cpu_e_de_sensores_que_falham():
    monitor = HealthMonitor(backend=FakePsutilBackend(cpu_error=True, temperatures={"x": 1.0}, temperature_error=True))
    assert monitor.get_cpu_usage() is None
    assert monitor.get_temperature() is None


def test_sensor_escolhido(monkeypatch, caplog):
    """Scenario: Sensor escolhido (maior leitura, sensor nomeado e sensor inexistente)."""
    monitor = HealthMonitor(
        backend=FakePsutilBackend(temperatures={"cpu_thermal": 61.0, "nvme": 48.0}), system="Linux"
    )
    assert monitor.get_temperature() == 61.0
    monkeypatch.setattr(config, "TEMPERATURE_SENSOR", "nvme")
    assert monitor.get_temperature() == 48.0
    monkeypatch.setattr(config, "TEMPERATURE_SENSOR", "inexistente")
    with caplog.at_level("WARNING"):
        assert monitor.get_temperature() is None
        assert monitor.get_temperature() is None
    assert len([r for r in caplog.records if "Sensor de temperatura não encontrado" in r.getMessage()]) == 1


def test_sem_sensores_listados():
    assert HealthMonitor(backend=FakePsutilBackend(temperatures={}), system="Linux").get_temperature() is None


def test_limitacao_termica_derivada(monkeypatch):
    """Scenario: Limitação térmica derivada (76,0 -> True, 60,0 -> False, desconhecida -> None)."""
    monkeypatch.setattr(config, "TEMPERATURE_LIMIT", 75.0)
    monitor = HealthMonitor(backend=FakePsutilBackend(temperatures={"cpu_thermal": [76.0, 60.0]}), system="Linux")
    assert monitor.is_throttled() is True
    assert monitor.is_throttled() is False
    assert HealthMonitor(backend=FakePsutilBackend(), system="Darwin").is_throttled() is None


def test_monitor_real_le_o_computador_sem_inventar_valores():
    memory = HealthMonitor().get_memory_usage()
    assert memory is not None and memory["total_mb"] > 0 and 0 <= memory["percent"] <= 100
