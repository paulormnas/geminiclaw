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
def test_integracao_do_grafo_sem_age_e_pulada_rapido_ou_passa_com_banco_real():
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/integration/knowledge", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    elapsed = time.monotonic() - started
    summary = proc.stdout.strip().splitlines()[-1]
    assert proc.returncode == 0, proc.stdout[-2000:]
    assert " failed" not in summary and " error" not in summary, summary
    if " passed" not in summary:  # sem banco: tudo pulado, e rápido (antes: ~31 s por teste)
        assert "skipped" in summary and elapsed < 30, (elapsed, summary)
