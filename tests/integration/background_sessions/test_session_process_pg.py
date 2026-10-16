"""Processo da sessão real, com PostgreSQL real (v18.7-background-sessions, tarefas 3.2, 3.5 e 3.8).

O processo é o ``src.cli.session_process`` com o laço roteirizado de ``tests.support.session_process_recorded``
(nenhuma chamada paga). O harness encerra o grupo de processos no teardown.
"""

from __future__ import annotations

import re
import signal
from pathlib import Path

import pytest

from tests.support.pg import pg_db, skip_if_no_postgres, temp_database_url  # noqa: F401
from tests.support.session_harness import SessionHarness

pytestmark = [pytest.mark.integration, pytest.mark.timeout(30), skip_if_no_postgres]


@pytest.fixture
def harness(pg_db, tmp_path: Path):  # noqa: F811
    h = SessionHarness(tmp_path, pg_db)
    try:
        yield h
    finally:
        h.teardown()


def test_registro_do_processo_apelido_e_arquivo_de_lancamento_apagado(harness: SessionHarness):
    """Scenarios: Prompt fora da linha de comando; processo grava pid, host, alias e batimento."""
    launched = harness.launch(harness.spec("tarefa com segredo no prompt"), scenario=harness.scenario(passos=[{"dorme": 1}]))
    session = harness.wait_registered(launched)
    assert session.pid == launched.proc.pid and session.host
    assert re.fullmatch(r"sessao-\d{2}", session.alias or "")
    assert session.resumo == "tarefa com segredo no prompt"
    assert session.payload["launch_id"] == launched.spec.launch_id
    assert not launched.path.exists()  # lido e apagado ao iniciar
    cmdline = " ".join(launched.proc.args)
    assert "segredo" not in cmdline and cmdline.endswith(f"--launch {launched.path}")
    assert harness.wait_exit(launched) == 0


def test_fim_por_objetivo_atingido_fecha_a_sessao_e_o_processo_sai_sozinho(harness: SessionHarness):
    """Caso 1: respostas levam ao critério de solução; o processo termina sem intervenção."""
    launched = harness.launch(scenario=harness.scenario(motivo="solucao_encontrada"))
    session = harness.wait_registered(launched)
    assert harness.wait_exit(launched) == 0
    final = harness.wait_status(session.id, ("closed", "success", "failed"))
    assert final.payload["motivo_parada"] == "solucao_encontrada"


def test_parada_por_limite_sai_com_3(harness: SessionHarness):
    """Caso 2: ``limite_tokens`` fecha a sessão e o processo sai com o código do limite."""
    launched = harness.launch(scenario=harness.scenario(motivo="limite_tokens"))
    session = harness.wait_registered(launched)
    assert harness.wait_exit(launched) == 3
    assert harness.manager.get(session.id).payload["motivo_parada"] == "limite_tokens"


def test_contexto_alterado_depois_da_confirmacao_sai_com_1_sem_sessao(harness: SessionHarness):
    launched = harness.launch(harness.spec(digest="confirmado-antes"))
    assert harness.wait_exit(launched) == 1
    assert harness.manager.find_by_launch_id(launched.spec.launch_id) is None
    assert "mudou depois da confirmação" in harness.tail(launched)
    assert not launched.path.exists()


def test_sigint_pede_fechamento_gracioso_e_sai_com_130(harness: SessionHarness):
    """Scenario: Interrupção da sessão lançada pelo REPL (SIGINT ao PID registrado)."""
    launched = harness.launch(scenario=harness.scenario(passos=[{"dorme": 8}]))
    session = harness.wait_registered(launched)
    harness.send(launched, signal.SIGINT)
    assert harness.wait_exit(launched, 10) == 130
    assert harness.manager.get(session.id).payload["motivo_parada"] == "interrompida_pesquisador"


def test_duas_sessoes_recebem_apelidos_diferentes(harness: SessionHarness):
    first = harness.launch(scenario=harness.scenario(passos=[{"dorme": 2}]))
    s1 = harness.wait_registered(first)
    second = harness.launch(scenario=harness.scenario(passos=[{"dorme": 2}]))
    s2 = harness.wait_registered(second)
    assert s1.alias != s2.alias and s1.pid != s2.pid
    harness.wait_exit(first)
    harness.wait_exit(second)


def test_batimento_grava_loop_beat_at(harness: SessionHarness):
    launched = harness.launch(scenario=harness.scenario(passos=[{"dorme": 3}]))
    session = harness.wait_registered(launched)
    first = harness.manager.get(session.id).loop_beat_at
    import time

    time.sleep(2.5)
    later = harness.manager.get(session.id).loop_beat_at
    assert later is not None and later != first
    harness.wait_exit(launched)
