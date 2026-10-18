"""Acompanhamento e comandos contra o PostgreSQL real (session-continuity 2.3 e 3.4)."""

from __future__ import annotations

import asyncio
import os
import re
import time

import psycopg
import pytest

from src.cli.progress_view import EventsThread, send_command, show_history, show_overview
from src.cli.session_process import watch_commands
from src.orchestration import usage
from src.session.events import EventReader
from src.session.inbox import SessionInbox
from src.session.manager import SessionManager
from tests.support.fake_gate import FakeGate
from tests.support.pg import pg_db, skip_if_no_postgres, temp_database_url  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.timeout(20), skip_if_no_postgres]

SUJO = "ok \x1b]0;titulo\x07 \x1b[2J fim ‮"


class Console:
    def __init__(self):
        self.lines: list[str] = []

    def notify(self, text):
        self.lines.append(text)

    write = notify


def _sessao_com_alias(manager: SessionManager, alias: str) -> object:
    session = manager.create("orchestrator")
    manager.register_process(session.id, pid=os.getpid(), host=__import__("socket").gethostname(),
                             process_started_at=None, terminal_id=None, alias=alias, resumo="r")
    return manager.get(session.id)


def _insere(pg_url: str, session_id: str, resumo: str, seq: int = 1) -> None:
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("INSERT INTO session_events (session_id, seq, tipo, resumo) VALUES (%s, %s, 'parada', %s)",
                     (session_id, seq, resumo))


def test_sequencia_de_controle_gravada_direto_na_tabela_nao_chega_ao_terminal(pg_db):  # noqa: F811
    """Scenario: o terminal saneia de novo, porque a tabela é gravável pelo papel principal."""
    manager = SessionManager()
    session = _sessao_com_alias(manager, "iris-01")
    _insere(pg_db, session.id, SUJO)
    saidas = Console()
    EventsThread(EventReader(), manager, saidas, 1).poll()
    show_history(EventReader(), session, saidas.write)
    show_overview(manager, EventReader(), FakeGate(), saidas.write, time.time(), lambda ids: {})
    # As cores do próprio terminal (SGR) são esperadas; qualquer outra sequência vinda da tabela, não.
    texto = re.sub(r"\x1b\[[0-9;]*m", "", "\n".join(saidas.lines))
    for proibido in ("\x1b", "\x07", "‮"):
        assert proibido not in texto
    assert texto.count("ok ") >= 3 and texto.count("fim") >= 3  # impresso, no histórico e na lista


def test_pesquisas_mostra_estado_pendentes_e_ultimo_evento(pg_db):  # noqa: F811
    manager = SessionManager()
    session = _sessao_com_alias(manager, "iris-01")
    fechada = manager.create("orchestrator")
    manager.update(fechada.id, status="closed", payload={"motivo_parada": "solucao_encontrada"})
    _insere(pg_db, session.id, "plano 1 aprovado: 2 subtarefas")
    gate = FakeGate()
    gate.request("aprovar_hipotese", "h4", "Aprovar h4?", ("aprovar", "rejeitar", "editar"), session_id=session.id)
    saidas = Console()
    show_overview(manager, EventReader(), gate, saidas.write, time.time(), lambda ids: {session.id: 0.5})
    texto = "\n".join(saidas.lines)
    assert "iris-01" in texto and "1 pedido(s) pendente(s)" in texto and "US$ 0,50" in texto
    assert "plano 1 aprovado" in texto and "closed" in texto


def test_comando_chega_pela_caixa_e_a_sessao_o_aplica(pg_db):  # noqa: F811
    manager = SessionManager()
    session = _sessao_com_alias(manager, "iris-01")
    saidas = Console()
    assert send_command(manager, "iris-01", "pausar", None, saidas.write) is True
    assert send_command(manager, "iris-01", "cancelar", "testar_svm", saidas.write) is True
    assert SessionInbox().pending_count(session.id) == 2

    async def um_ciclo():
        tarefa = asyncio.ensure_future(watch_commands(session.id, interval=0.05))
        await asyncio.sleep(0.4)
        tarefa.cancel()

    asyncio.run(um_ciclo())
    assert usage.pause_requested() and usage.is_cancelled("testar_svm")
    assert SessionInbox().pending_count(session.id) == 0  # consumidos
    assert SessionInbox().take_commands(session.id) == []


def test_sessao_sem_processo_e_recusada(pg_db):  # noqa: F811
    manager = SessionManager()
    session = manager.create("orchestrator")
    manager.register_process(session.id, pid=1, host="h", process_started_at=None, terminal_id=None,
                             alias="b-01", resumo="r")
    manager.update(session.id, status="aguarda_pesquisador", payload={"motivo_parada": "aguarda_pesquisador"})
    saidas = Console()
    assert send_command(manager, "b-01", "pausar", None, saidas.write) is False
    assert "aguarda_pesquisador" in "\n".join(saidas.lines) and "retomar b-01" in "\n".join(saidas.lines)
    assert SessionInbox().pending_count(session.id) == 0
