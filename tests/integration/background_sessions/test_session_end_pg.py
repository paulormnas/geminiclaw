"""Fim da sessão por modo e presença, com processo real e PostgreSQL real (v18.7-background-sessions, tarefa 4.4 a 4.6).

O laço é o roteirizado de ``tests.support.session_process_recorded`` (ver a dúvida de spec 3.A em tasks.md): o
ciclo de vida da requisição, o batimento, o registro, a leitura da presença pela sessão ``assisted`` e o código de
saída são os reais.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.session.presence import END_EXIT, PgPresenceStore, TerminalAlreadyOpenError, TerminalPresence
from tests.support.pg import pg_db, skip_if_no_postgres, temp_database_url  # noqa: F401
from tests.support.session_harness import ROOT, SessionHarness

pytestmark = [pytest.mark.integration, pytest.mark.timeout(30), skip_if_no_postgres]

PASSOS_ASSISTED = [{"subtarefa": "s1", "dorme": 3}, {"subtarefa": "s2", "dorme": 1}]


@pytest.fixture
def harness(pg_db, tmp_path: Path):  # noqa: F811
    h = SessionHarness(tmp_path, pg_db)
    try:
        yield h
    finally:
        h.teardown()


@pytest.fixture
def presence(pg_db):  # noqa: F811
    opened: list[TerminalPresence] = []

    def make(tipo: str = "repl") -> TerminalPresence:
        p = TerminalPresence(tipo, store=PgPresenceStore())
        opened.append(p)
        return p

    yield make
    for p in opened:
        p.stop()


def _wait(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def _subtarefas(harness: SessionHarness, session_id: str) -> dict[str, str]:
    payload = harness.manager.get(session_id).payload
    return {s["nome"]: s["status"] for s in payload.get("subtarefas", [])}


def test_caso_3_so_pedidos_pendentes_aguarda_o_pesquisador_e_sai_com_4(harness: SessionHarness):
    launched = harness.launch(harness.spec(modo="semi"), scenario=harness.scenario(motivo="aguarda_pesquisador"))
    session = harness.wait_registered(launched)
    assert harness.wait_exit(launched) == 4
    final = harness.manager.get(session.id)
    assert final.status == "aguarda_pesquisador" and final.payload["motivo_parada"] == "aguarda_pesquisador"
    assert final.payload["codigo_saida"] == 4


def test_caso_4_terminal_sai_normalmente_subtarefa_termina_e_a_sessao_se_suspende(harness, presence):
    terminal = presence()
    terminal_id = terminal.start()
    terminal.start_heartbeat()
    launched = harness.launch(
        harness.spec(modo="assisted", terminal_id=terminal_id), scenario=harness.scenario(passos=PASSOS_ASSISTED)
    )
    session = harness.wait_registered(launched)
    assert _wait(lambda: _subtarefas(harness, session.id).get("s1") == "em_andamento")
    terminal.stop()  # o REPL sai normalmente com s1 em curso
    assert harness.wait_exit(launched, 12) == 4
    final = harness.manager.get(session.id)
    assert final.status == "suspensa_sem_pesquisador" and final.payload["motivo_parada"] == "suspensa_sem_pesquisador"
    assert _subtarefas(harness, session.id) == {"s1": "concluida"}  # s2 nunca começou
    assert not _pid_exists(launched.proc.pid)


def test_caso_5_queda_do_terminal_com_sigkill_suspende_sem_interromper_a_subtarefa(harness):
    terminal = subprocess.Popen(
        [sys.executable, "-m", "tests.support.presence_process"],
        stdout=subprocess.PIPE, text=True, cwd=ROOT, env=harness.env,
    )
    try:
        terminal_id = terminal.stdout.readline().strip()
        assert terminal_id
        launched = harness.launch(
            harness.spec(modo="assisted", terminal_id=terminal_id),
            scenario=harness.scenario(passos=[{"subtarefa": "s1", "dorme": 6}, {"subtarefa": "s2", "dorme": 1}]),
        )
        session = harness.wait_registered(launched)
        assert _wait(lambda: _subtarefas(harness, session.id).get("s1") == "em_andamento")
        terminal.send_signal(signal.SIGKILL)  # o REPL cai sem gravar ended_at
        killed_at = time.monotonic()
        assert harness.wait_exit(launched, 14) == 4
        assert time.monotonic() - killed_at < 14
        final = harness.manager.get(session.id)
        assert final.status == "suspensa_sem_pesquisador"
        assert _subtarefas(harness, session.id) == {"s1": "concluida"}  # concluída, não interrompida
    finally:
        terminal.kill()
        terminal.wait(timeout=5)


def test_modo_auto_ignora_o_terminal(harness, presence):
    terminal = presence()
    terminal_id = terminal.start()
    launched = harness.launch(
        harness.spec(modo="auto", terminal_id=terminal_id),
        scenario=harness.scenario(passos=[{"subtarefa": "s1", "dorme": 2}, {"subtarefa": "s2", "dorme": 1}]),
    )
    session = harness.wait_registered(launched)
    terminal.stop()  # o REPL sai; a sessão auto segue
    time.sleep(1.5)
    assert harness.manager.get(session.id).status == "active"
    assert harness.wait_exit(launched, 12) == 0
    assert _subtarefas(harness, session.id) == {"s1": "concluida", "s2": "concluida"}


def test_caso_6_um_repl_por_vez_e_presenca_velha_vira_obsoleta(presence):
    first = presence()
    first.start()
    with pytest.raises(TerminalAlreadyOpenError):
        presence().start()
    store = PgPresenceStore()
    store.touch(first.terminal_id, time.time() - 600)  # batimento de 10 minutos atrás
    second = presence()
    second.start()
    assert store.get(first.terminal_id).end_reason == "obsoleta"
    assert store.get(second.terminal_id).ended_at is None


def test_abertura_simultanea_deixa_so_um_repl(presence):
    results: list[str] = []

    def open_one() -> None:
        try:
            presence().start()
            results.append("ok")
        except TerminalAlreadyOpenError:
            results.append("recusado")

    threads = [threading.Thread(target=open_one) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(results) == ["ok", "recusado", "recusado", "recusado"]


def test_saida_normal_grava_ended_at_e_end_reason_saida_no_banco(presence):
    terminal = presence()
    terminal_id = terminal.start()
    terminal.stop()
    row = PgPresenceStore().get(terminal_id)
    assert row.ended_at is not None and row.end_reason == END_EXIT
    assert PgPresenceStore().last_repl_end() == pytest.approx(row.ended_at, abs=1)
    assert not terminal.is_present()


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
