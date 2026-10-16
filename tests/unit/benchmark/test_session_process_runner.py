"""Runner do benchmark com o processo da sessão (v18.7-background-sessions, tarefas 6.1 a 6.3)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import psutil
import pytest

from scripts.benchmark.run_benchmark import anomalies, stop_class
from tests.unit.benchmark.test_harness_v18_6 import _run_fake_combination

pytestmark = pytest.mark.unit

CHILD_IGNORING_TERM = (
    "import os, signal, subprocess, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "child = subprocess.Popen([sys.executable, '-c', "
    "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(600)'])\n"
    "open(sys.argv[1], 'w').write(str(child.pid))\n"
    "time.sleep(600)\n"
)


def _alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_tempo_limite_encerra_o_grupo_inteiro_inclusive_o_filho_que_ignora_sigterm(monkeypatch, tmp_path: Path):
    pid_file = tmp_path / "filho.pid"
    started = time.monotonic()
    result = _run_fake_combination(
        monkeypatch, tmp_path, command=[sys.executable, "-c", CHILD_IGNORING_TERM, str(pid_file)],
        timeout=2, kill_grace_seconds=1,
    )
    assert result["status"] == "timeout"
    child = int(pid_file.read_text())
    deadline = started + 5
    while time.monotonic() < deadline and _alive(child):
        time.sleep(0.1)
    assert not _alive(child)  # 5 s depois do início nenhum processo do grupo existe


def test_uma_sessao_por_vez_a_segunda_comeca_depois_do_fim_da_primeira(monkeypatch, tmp_path: Path):
    script = (
        "import os, sys, time\n"
        "path = sys.argv[1]\n"
        "start = time.time(); time.sleep(1); end = time.time()\n"
        "open(path, 'w').write(f'{os.getpid()} {start} {end}')\n"
    )
    records = []
    for index in range(2):
        out = tmp_path / f"run{index}.txt"
        result = _run_fake_combination(monkeypatch, tmp_path, command=[sys.executable, "-c", script, str(out)])
        assert result["status"] == "exit 0"
        pid, start, end = out.read_text().split()
        records.append((int(pid), float(start), float(end)))
    first, second = records
    assert second[1] > first[2] and not _alive(first[0])


def test_fim_normal_nao_deixa_processo_orfao_no_grupo(monkeypatch, tmp_path: Path):
    pid_file = tmp_path / "orfao.pid"
    script = (
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "open(sys.argv[1], 'w').write(str(child.pid))\n"
    )
    result = _run_fake_combination(monkeypatch, tmp_path, command=[sys.executable, "-c", script, str(pid_file)])
    assert result["status"] == "exit 0"
    orphan = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and _alive(orphan):
        time.sleep(0.1)
    assert not _alive(orphan)


# -- anomalias por código de saída (6.1) ---------------------------------------------------------------------------


def _result(status: str, stop: str | None) -> dict:
    return {"status": status, "stop_reason": stop, "session": "s", "outcome": {"subtasks": 3},
            "operation_metrics": {}}


def test_exit_4_e_anomalia_aguarda_o_pesquisador():
    problems = anomalies_text(_result("exit 4", "aguarda_pesquisador"))
    assert "aguarda o pesquisador" in problems


def test_codigo_divergente_do_motivo_e_anomalia():
    assert "código de saída divergente" in anomalies_text(_result("exit 0", "limite_tokens"))


def test_exit_0_com_solucao_encontrada_nao_tem_anomalia_de_parada_nem_de_codigo():
    assert anomalies_text(_result("exit 0", "solucao_encontrada")) == ""


@pytest.mark.parametrize("stop", ["versao_modelo", "planos_rejeitados"])
def test_exit_3_de_versao_modelo_e_planos_rejeitados_nao_diverge(stop):
    assert "código de saída divergente" not in anomalies_text(_result("exit 3", stop))


@pytest.mark.parametrize(
    "stop", ["aguarda_pesquisador", "suspensa_sem_pesquisador", "encerrada_pesquisador", "pausada_pesquisador",
             "interrompida_pesquisador", "interrompida"],
)
def test_motivos_de_ausencia_do_pesquisador_sao_interrupcao_e_anomalia(stop):
    assert stop_class(stop) == "interrupcao"
    assert anomalies_text(_result("exit 4" if "aguarda" in stop or "suspensa" in stop else "exit 130", stop))


def test_demais_classes_nao_mudam():
    assert stop_class("versao_modelo") == "limite" and stop_class("limite_tokens") == "limite"
    assert stop_class("hipoteses_nao_testadas") == "hipoteses_nao_testadas"
    assert stop_class("solucao_encontrada") == "criterio_pesquisa" and stop_class(None) is None


def anomalies_text(result: dict) -> str:
    return " | ".join(anomalies(result))


def test_timeout_nao_acusa_codigo_divergente():
    assert "código de saída divergente" not in anomalies_text(_result("timeout", "limite_tempo"))
    assert os.name == "posix"
