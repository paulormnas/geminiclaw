"""Aviso de proteção térmica desligada (v18.7-resource-monitor-config, tarefas 2.5 e 2.6; parecer de segurança)."""

from __future__ import annotations

import pytest

from src import config
from src.host.health import HealthMonitor, reset_warnings_for_tests, thermal_protection_warning
from tests.support.env_override import env_override
from tests.support.fake_psutil_backend import FakePsutilBackend

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset():
    reset_warnings_for_tests()
    yield
    reset_warnings_for_tests()


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING" and "TEMPERATURE_LIMIT" in r.getMessage()]


def test_aviso_no_linux_com_sensor_legivel_e_sem_limite(monkeypatch, caplog):
    """Scenario: Aviso no Linux com sensor legível e sem limite (um único WARNING em duas inicializações)."""
    monkeypatch.setattr(config, "TEMPERATURE_LIMIT", None)
    monitor = HealthMonitor(backend=FakePsutilBackend(temperatures={"cpu_thermal": 55.0}), system="Linux")
    with caplog.at_level("WARNING"):
        first = thermal_protection_warning(monitor)
        second = thermal_protection_warning(monitor)
    assert first and second and "TEMPERATURE_LIMIT" in first
    assert len(_warnings(caplog)) == 1


def test_sem_aviso_com_limite_definido(monkeypatch, caplog):
    monkeypatch.setattr(config, "TEMPERATURE_LIMIT", 80.0)
    monitor = HealthMonitor(backend=FakePsutilBackend(temperatures={"cpu_thermal": 55.0}), system="Linux")
    with caplog.at_level("WARNING"):
        assert thermal_protection_warning(monitor) is None
    assert not _warnings(caplog)


def test_sem_aviso_sem_leitura_ou_fora_do_linux(monkeypatch, caplog):
    monkeypatch.setattr(config, "TEMPERATURE_LIMIT", None)
    sem_leitura = HealthMonitor(backend=FakePsutilBackend(temperatures={}), system="Linux")
    macos = HealthMonitor(backend=FakePsutilBackend(temperatures={"cpu_thermal": 55.0}), system="Darwin")
    with caplog.at_level("WARNING"):
        assert thermal_protection_warning(sem_leitura) is None
        assert thermal_protection_warning(macos) is None
    assert not _warnings(caplog)


def test_cabecalho_do_repl_mostra_o_aviso(monkeypatch, capsys):
    import src.cli.banner as cli_main

    monkeypatch.setattr(config, "TEMPERATURE_LIMIT", None)
    monkeypatch.setattr(
        cli_main, "thermal_protection_warning",
        lambda: thermal_protection_warning(
            HealthMonitor(backend=FakePsutilBackend(temperatures={"cpu_thermal": 55.0}), system="Linux")
        ),
    )
    cli_main.print_session_banner("auto", context_dir="inexistente")
    assert "TEMPERATURE_LIMIT" in capsys.readouterr().out


def test_inicializacao_nao_falha_com_o_limite_indefinido():
    with env_override({}) as load:
        module = load()
        assert module.TEMPERATURE_LIMIT is None


# --- Instantâneo de hardware (spec ``operation-metrics``) --------------------------------------------------------


def _loop_with(monitor):
    from unittest.mock import MagicMock

    from src.orchestration.autonomous_loop import AutonomousLoop

    loop = AutonomousLoop(orchestrator=MagicMock())
    loop._health_monitor = monitor  # noqa: SLF001
    return loop


def test_instantaneo_no_macos_sem_sensor(monkeypatch):
    """Scenario: macOS sem sensor (``cpu_temp_c`` e ``is_throttled`` nulos, memória lida)."""
    from unittest.mock import MagicMock

    telemetry = MagicMock()
    monkeypatch.setattr("src.orchestration.autonomous_loop.get_telemetry", lambda: telemetry)
    monkeypatch.setattr(config, "TEMPERATURE_LIMIT", 75.0)
    monitor = HealthMonitor(backend=FakePsutilBackend(available_mb=3000.0, cpu=12.0), system="Darwin")
    _loop_with(monitor)._record_hardware_snapshot("sessao-1", "tarefa")  # noqa: SLF001
    kwargs = telemetry.record_hardware_snapshot.call_args.kwargs
    assert kwargs["cpu_temp_c"] is None and kwargs["is_throttled"] is None
    assert kwargs["mem_available_mb"] == 3000.0 and kwargs["cpu_usage_pct"] == 12.0


def test_instantaneo_com_limitacao_derivada(monkeypatch):
    """Scenario: Limitação derivada (limite 75 e 77,0 °C: ``is_throttled`` verdadeiro)."""
    from unittest.mock import MagicMock

    telemetry = MagicMock()
    monkeypatch.setattr("src.orchestration.autonomous_loop.get_telemetry", lambda: telemetry)
    monkeypatch.setattr(config, "TEMPERATURE_LIMIT", 75.0)
    monitor = HealthMonitor(backend=FakePsutilBackend(temperatures={"cpu_thermal": 77.0}), system="Linux")
    _loop_with(monitor)._record_hardware_snapshot("sessao-1", None)  # noqa: SLF001
    kwargs = telemetry.record_hardware_snapshot.call_args.kwargs
    assert kwargs["cpu_temp_c"] == 77.0 and kwargs["is_throttled"] is True


def test_pico_de_temperatura_nulo_no_resumo_e_nas_metricas(monkeypatch):
    """Sem leitura de temperatura, o resumo e as métricas de operação dizem desconhecido/``null``."""
    from unittest.mock import MagicMock

    from src.observability.telemetry import TelemetryCollector
    from src.report.operation_metrics import CostResourcesReader

    peaks = {"max_temp_c": None, "max_cpu_pct": 10.0, "max_mem_pct": 50.0, "min_mem_available_mb": 3000.0,
             "throttle_incidents": None}
    collector = TelemetryCollector()
    monkeypatch.setattr(collector, "get_hardware_peaks", lambda execution_id: peaks)
    monkeypatch.setattr(collector, "get_token_summary", lambda execution_id: {})
    monkeypatch.setattr(collector, "get_derived_metrics", lambda execution_id: {"peak_mem_pressure_pct": None})
    assert "Pico de Temperatura CPU: desconhecido" in collector.get_summarized_stats("e1")

    telemetry = MagicMock()
    telemetry.get_usage_by_task.return_value = []
    telemetry.get_hardware_peaks.return_value = peaks
    telemetry.get_average_cpu.return_value = None
    monkeypatch.setattr("src.observability.telemetry.get_telemetry", lambda: telemetry)
    node = CostResourcesReader().read("e1")["no"]
    assert node["temperatura_pico_c"] is None
