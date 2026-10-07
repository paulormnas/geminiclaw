"""Sem Apache AGE acessível, os testes de integração do grafo são pulados na coleta, sem espera de 30 s cada.

Um ``pytestmark`` em ``conftest.py`` não se aplica aos módulos de teste; sem o hook de coleta, cada teste esperava o
``getconn(timeout=30)`` do pool contra o banco fictício de ``tests/conftest.py`` e terminava em falha.
"""

import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_integracao_do_grafo_sem_age_e_pulada_rapido():
    import psycopg

    from src import config

    try:
        psycopg.connect(config.DATABASE_URL, connect_timeout=2).close()
    except Exception:  # noqa: BLE001 - sem banco: é o cenário deste teste
        pass
    else:
        pytest.skip("Há um PostgreSQL acessível: os testes do grafo rodam de verdade (outras exigências de ambiente).")
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/integration/knowledge", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    elapsed = time.monotonic() - started
    summary = proc.stdout.strip().splitlines()[-1]
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert " failed" not in summary and " error" not in summary, summary
    assert "skipped" in summary and " passed" not in summary and elapsed < 30, (elapsed, summary)  # antes: ~31 s cada
