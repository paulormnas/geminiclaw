"""Amostrador de recursos por plataforma: ``/proc`` no Linux, ``psutil`` no macOS (``scripts.benchmark.resources``)."""

from __future__ import annotations

import os
import time

import pytest

from scripts import host_resources
from scripts.benchmark import resources

pytestmark = pytest.mark.unit


def test_linux_usa_os_leitores_de_proc():
    sampler = resources.make_sampler(root_pid=1, interval=0.5, host_os="linux")
    assert sampler._cpu_times_fn is None and sampler._read_tree is resources.process_tree  # noqa: SLF001


@pytest.mark.parametrize("host_os", ["darwin", "windows"])
def test_fora_do_linux_usa_psutil_sem_throttling(host_os):
    sampler = resources.make_sampler(root_pid=1, interval=0.5, host_os=host_os)
    assert sampler._cpu_times_fn is resources.psutil_cpu_times  # noqa: SLF001
    assert sampler._read_tree is resources.psutil_process_tree  # noqa: SLF001
    assert sampler._read_throttle() is None  # noqa: SLF001


def test_leitores_psutil_devolvem_numeros_do_processo_atual():
    total, idle = resources.psutil_cpu_times()
    memory_total, memory_available = resources.psutil_memory()
    tree = resources.psutil_process_tree(os.getpid())
    assert total > idle >= 0 and memory_total > memory_available > 0
    assert os.getpid() in tree and tree[os.getpid()][1] > 0  # RSS em bytes
    assert resources.psutil_process_tree(2**22) == {}  # PID inexistente: vazio, sem erro


def test_amostrador_psutil_mede_o_proprio_processo_de_ponta_a_ponta():
    sampler = resources.make_sampler(root_pid=os.getpid(), interval=0.05, host_os="darwin")
    sampler.start()
    time.sleep(0.4)
    sampler.stop()
    sampler.join()
    summary = sampler.summary()
    assert summary["samples"] >= 2 and summary["mem_used_mb"]["max"] > 0
    assert summary["proc_rss_mb"]["max"] > 1 and summary["max_processes"] >= 1


def test_script_identifica_o_sistema_e_o_leitor(monkeypatch):
    info = host_resources.identify()
    assert info["leitor_de_recursos"] in ("proc", "psutil")
    assert (info["host_os"] == "linux") == (info["leitor_de_recursos"] == "proc")
    out = host_resources.sample(0.3, 0.05, None)
    assert out["samples"] >= 2
