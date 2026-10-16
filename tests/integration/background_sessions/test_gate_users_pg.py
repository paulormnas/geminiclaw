"""Usuários do gate persistente contra o PostgreSQL real (persistent-human-gate, tarefas 2.3, 2.4, 3.1 e 3.2)."""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gate.persistent_gate import PersistentGate, TerminalGate
from src.gate.types import Source
from src.knowledge.gate_approver import PersistentGateApprover, PersistentGateConfirmer
from src.knowledge.hypothesis_cycle import ApprovalItem, SolutionStatus
from src.orchestration.orchestrator import AgentTask, Orchestrator
from src.orchestration.usage import UsageBudget
from tests.support.pg import pg_db, skip_if_no_postgres, temp_database_url  # noqa: F401
from tests.support.session_harness import SessionHarness

pytestmark = [pytest.mark.integration, pytest.mark.timeout(45), skip_if_no_postgres]

UNLIMITED = dataclasses.asdict(UsageBudget(None, None, 3, 3, 0.05, None, True))


def test_resolve_e_idempotente_e_a_sessao_reaproveita_o_pedido_da_cadeia(pg_db):  # noqa: F811
    terminal, session = TerminalGate(), PersistentGate()
    first = terminal.resolve("confirmar_problema", "proj-1", source=Source.TERMINAL, approved=True)
    again = terminal.resolve("confirmar_problema", "proj-1", source=Source.TERMINAL, approved=False)
    assert again.id == first.id and again.estado == "autorizada"  # a decisão anterior do pesquisador vale
    req = session.request("aprovar_hipotese", "h1", "?", ("aprovar", "rejeitar", "editar"), session_id="s1")
    assert session.find_in_chain("aprovar_hipotese", "h1", ["s2", "s1"]).id == req.id
    assert session.find_in_chain("aprovar_hipotese", "h1", ["s3"]) is None


def item(hid="h1") -> ApprovalItem:
    return ApprovalItem(id=hid, enunciado="R2 > 0,9", origem="researcher", justificativa="j", prioridade=0.5)


def test_aprovador_e_confirmador_no_banco_real_com_retomada(pg_db):  # noqa: F811
    terminal, session = TerminalGate(), PersistentGate()
    PersistentGateApprover(session, "s1", project_id="p")([item()])
    PersistentGateConfirmer(session, "s1", project_id="p")(SolutionStatus(True, hypothesis_id="h1"))
    pend = {r.decisao: r for r in session.pending(["s1"])}
    assert set(pend) == {"aprovar_hipotese", "decidir_objetivo_atingido"}
    terminal.answer(pend["aprovar_hipotese"].id, source=Source.TERMINAL, resposta={"acao": "aprovar"})
    terminal.answer(pend["decidir_objetivo_atingido"].id, source=Source.TERMINAL, resposta={"acao": "encerrar"})
    # a sessão retomada (s2) aplica o que foi respondido enquanto estava fora, uma vez só
    resumed = PersistentGateApprover(session, "s2", ["s2", "s1"], "p")
    assert set(resumed([item()])) == {"h1"}
    assert session.find_in_chain("aprovar_hipotese", "h1", ["s2", "s1"]) is None  # consumido: uso único
    assert PersistentGateConfirmer(session, "s2", ["s2", "s1"], "p")(SolutionStatus(True, hypothesis_id="h1")) == "encerrar"
    assert session.pending(["s1", "s2"]) == []  # nenhum pedido duplicado


def test_pergunta_do_agente_respondida_pelo_terminal_no_banco_real(pg_db):  # noqa: F811
    from unittest.mock import patch

    from tests.support.session_fakes import FakeSessionManager

    manager = FakeSessionManager()
    manager.add("s1", "active", {"mode": "assisted"})
    orch = Orchestrator(session_manager=manager, output_manager=SimpleNamespace(base_dir=None), agent_runtime=None)
    orch.human_gate = PersistentGate()
    terminal = TerminalGate()

    def answer_later() -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            pending = terminal.pending(["s1"])
            if pending:
                terminal.answer(pending[0].id, source=Source.TERMINAL, resposta={"texto": "Use /outputs/dados.csv"})
                return
            time.sleep(0.05)

    thread = threading.Thread(target=answer_later)
    thread.start()
    task = AgentTask(agent_id="researcher", prompt="p", task_name="t1")
    with patch("src.config.GATE_ASK_WAIT_SECONDS", 10), patch("src.config.GATE_POLL_SECONDS", 0.1):
        answer = asyncio.run(orch._ask_researcher_core("Onde está o dataset?", "", "", [], task, "s1"))
    thread.join(5)
    assert answer == "Use /outputs/dados.csv"
    assert terminal.pending(["s1"]) == []  # consumido


@pytest.fixture
def harness(pg_db, tmp_path: Path):  # noqa: F811
    h = SessionHarness(tmp_path, pg_db)
    try:
        yield h
    finally:
        h.teardown()


def unlimited_spec(h: SessionHarness):
    stamp = datetime.now(timezone.utc).isoformat()
    return h.spec(orcamento=UNLIMITED, ilimitado={"origem": "cli", "confirmado_em": stamp})


def test_modo_sem_limite_so_inicia_com_o_pedido_do_terminal_para_aquele_lancamento(harness: SessionHarness):
    spec = unlimited_spec(harness)
    terminal = TerminalGate()
    terminal.resolve("ativar_modo_sem_limite", "OUTRO-LANCAMENTO", source=Source.TERMINAL, approved=True)
    refused = harness.launch(spec)
    assert harness.wait_exit(refused) == 2  # nem o pedido de outro lançamento nem a falta dele valem
    assert harness.manager.find_by_launch_id(spec.launch_id) is None

    ok_spec = unlimited_spec(harness)
    terminal.resolve("ativar_modo_sem_limite", ok_spec.launch_id, source=Source.TERMINAL, approved=True)
    accepted = harness.launch(ok_spec, scenario=harness.scenario(passos=[{"dorme": 1}]))
    session = harness.wait_registered(accepted)
    assert session.payload["budget"]["unlimited"] is True
    assert harness.wait_exit(accepted) == 0
    reuse = harness.launch(dataclasses.replace(ok_spec, launch_id=ok_spec.launch_id))  # a autorização é de uso único
    assert harness.wait_exit(reuse) in (1, 2)
