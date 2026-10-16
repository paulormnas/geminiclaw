"""REPL e comando direto contra o processo da sessão real e o PostgreSQL real (v18.7-background-sessions, tarefa 5).

O iniciador e o REPL são os de produção; o processo da sessão roda o laço roteirizado (dúvida de spec 3.A). O roteamento
é offline e o vínculo de projeto é o contorno ``sem_grafo``.
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import psutil
import pytest

import src.cli.direct as direct
from src.cli.repl import Repl
from src.cli.session_start import MEMORY_POLICY_FAIL
from src.session.presence import PgPresenceStore, TerminalPresence
from src.session.watch import SessionWatch
from tests.support.pg import pg_db, skip_if_no_postgres, temp_database_url  # noqa: F401
from tests.support.session_harness import SessionHarness
from tests.support.session_process_recorded import _offline_routing
from tests.support.starter_world import BUDGET, args

pytestmark = [pytest.mark.integration, pytest.mark.timeout(45), skip_if_no_postgres]


@pytest.fixture
def harness(pg_db, tmp_path: Path):  # noqa: F811
    h = SessionHarness(tmp_path, pg_db)
    try:
        yield h
    finally:
        h.teardown()


@contextmanager
def terminal_patches():
    async def routing(*_a, **_k):
        return _offline_routing()

    with (
        patch("src.llm.session.build_session_routing", routing),
        patch("src.cli.session_start.print_session_banner"),
        patch("src.cli.session_start._project_marked_unlimited", lambda _p: False),
    ):
        yield


def make_repl(h: SessionHarness, inputs=()):
    answers = iter(inputs)
    lines: list[str] = []
    console = type("C", (), {"write": lines.append, "notify": lines.append, "waiting_for_input": False})()
    starter = h.starter(input_fn=lambda _p: next(answers, ""), output_fn=lines.append)
    repl = Repl(
        mode="auto", explicit_mode=None, budget=BUDGET, args=args(), starter=starter, manager=h.manager,
        presence=TerminalPresence("repl", store=PgPresenceStore()), input_fn=lambda _p: next(answers, "sair"),
        console=console, sweep_interval=3600, recover=lambda s: None,
    )
    return repl, lines


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_repl_livre_durante_a_pesquisa(harness: SessionHarness):
    """Scenario: o prompt volta antes do fim da sessão; a sessão tem PID vivo diferente do REPL e apelido."""
    harness.use_scenario(harness.scenario(passos=[{"dorme": 3}]))
    repl, lines = make_repl(harness, ["nova-pesquisa estudar a base iris", "sair"])
    assert repl.open() is None
    with terminal_patches():
        started_at = time.monotonic()
        asyncio.run(repl.loop())
        elapsed = time.monotonic() - started_at
    session = harness.manager.list_orchestrator()[0]
    assert session.status == "active" and elapsed < 10  # o REPL já saiu e a sessão segue
    assert session.pid != os.getpid() and psutil.pid_exists(session.pid)
    assert session.host and session.alias == "sessao-01" and session.resumo == "estudar a base iris"
    assert session.terminal_id == repl.presence.terminal_id
    repl.close()
    row = PgPresenceStore().get(session.terminal_id)
    assert row.ended_at is not None and row.end_reason == "saida"
    assert wait_for(lambda: harness.manager.get(session.id).status != "active")


def test_caso_8_retomar_pela_pergunta_do_repl_cria_processo_novo_que_continua_a_origem(harness: SessionHarness):
    harness.use_scenario(harness.scenario(motivo="aguarda_pesquisador"))
    first, _ = make_repl(harness)
    assert first.open() is None
    with terminal_patches():
        asyncio.run(first.handle("nova-pesquisa estudar iris"))
    origin = harness.manager.list_orchestrator()[0]
    assert wait_for(lambda: harness.manager.get(origin.id).status == "aguarda_pesquisador")
    first.close()

    harness.use_scenario(harness.scenario(motivo="solucao_encontrada"))
    second, lines = make_repl(harness, ["r"])
    assert second.open() is None
    with terminal_patches(), patch("src.knowledge.factory.open_knowledge_runtime", return_value=None), patch(
        "src.knowledge.factory.open_graph_store", side_effect=RuntimeError("sem grafo")
    ):
        asyncio.run(second.review_unfinished())
    second.close()
    assert wait_for(lambda: harness.manager.get(origin.id).payload.get("continued_by"))
    new_id = harness.manager.get(origin.id).payload["continued_by"]
    new = harness.manager.get(new_id)
    assert new.payload["continues_session_id"] == origin.id and new.alias == origin.alias  # herda o apelido
    assert wait_for(lambda: harness.manager.get(new_id).status in ("closed", "success", "failed"))


def test_caso_10_sigkill_no_processo_da_sessao_vira_interrompida_e_a_pergunta_aparece(harness: SessionHarness):
    harness.use_scenario(harness.scenario(passos=[{"dorme": 20}]))
    repl, _ = make_repl(harness)
    assert repl.open() is None
    with terminal_patches():
        asyncio.run(repl.handle("nova-pesquisa estudar iris"))
    session = harness.manager.list_orchestrator()[0]
    os.kill(session.pid, signal.SIGKILL)
    assert wait_for(lambda: not psutil.pid_exists(session.pid) or psutil.Process(session.pid).status() == "zombie")
    recovered: list[str] = []
    marked = SessionWatch(harness.manager, recover=lambda s: recovered.append(s.id)).sweep()
    assert [s.id for s in marked] == [session.id] and recovered == [session.id]
    assert harness.manager.get(session.id).status == "interrompida"
    repl.close()
    # ao reabrir o REPL a sessão aparece na pergunta de retomada
    reopened, lines = make_repl(harness, ["m"])
    assert reopened.open() is None
    asyncio.run(reopened.review_unfinished())
    reopened.close()
    assert any("[r]etomar" in line or session.alias in line for line in lines)


def test_laco_travado_e_marcado_mesmo_com_o_batimento_recente(harness: SessionHarness):
    """O batimento em thread segue vivo (updated_at recente), mas o laço sem sinal por 5 s é travamento."""
    harness.use_scenario(harness.scenario(passos=[{"bloqueia": 6}]))
    repl, _ = make_repl(harness)
    assert repl.open() is None
    with terminal_patches():
        asyncio.run(repl.handle("nova-pesquisa estudar iris"))
    session = harness.manager.list_orchestrator()[0]
    watch = SessionWatch(harness.manager, stale_seconds=60, loop_stale_seconds=2)
    assert wait_for(lambda: bool(watch.sweep()), timeout=15)
    assert harness.manager.get(session.id).status == "interrompida"
    repl.close()


# -- comando direto (caso 12) --------------------------------------------------------------------------------------


def run_direct(h: SessionHarness, **kwargs) -> int:
    starter = h.starter()
    with terminal_patches(), patch.object(direct, "sweep_stopped"):
        return asyncio.run(direct.start_research("tarefa", args(), mode="auto", budget=BUDGET, starter=starter, **kwargs))


def test_primeiro_plano_so_termina_depois_do_processo_e_sai_com_0(harness: SessionHarness):
    harness.use_scenario(harness.scenario(passos=[{"dorme": 1}], motivo="solucao_encontrada"))
    started = time.monotonic()
    assert run_direct(harness, background=False) == 0
    assert time.monotonic() - started >= 1
    session = harness.manager.list_orchestrator()[0]
    assert session.payload["motivo_parada"] == "solucao_encontrada"
    rows = [r for r in [PgPresenceStore().get(session.terminal_id)] if r]
    assert rows and rows[0].tipo == "direto" and rows[0].end_reason == "saida"  # presença do comando direto


def test_codigo_do_limite_e_3(harness: SessionHarness):
    harness.use_scenario(harness.scenario(motivo="limite_tokens"))
    assert run_direct(harness, background=False) == 3


def test_ctrl_c_no_comando_direto_fecha_com_checkpoint_e_sai_com_130(harness: SessionHarness):
    harness.use_scenario(harness.scenario(passos=[{"subtarefa": "s1", "dorme": 10}]))
    def interrupt_when_active() -> None:  # o Ctrl+C só chega depois que o laço da sessão está ativo
        if wait_for(lambda: any(s.payload.get("subtarefas") for s in harness.manager.list_orchestrator()), 30):
            os.kill(os.getpid(), signal.SIGINT)

    watcher = threading.Thread(target=interrupt_when_active, daemon=True)
    watcher.start()
    code = run_direct(harness, background=False)
    watcher.join(5)
    assert code == 130
    session = harness.manager.list_orchestrator()[0]
    assert session.payload["motivo_parada"] == "interrompida_pesquisador"


def test_background_imprime_apelido_e_pid_sai_com_0_e_a_sessao_segue_sem_terminal(harness: SessionHarness, capsys):
    harness.use_scenario(harness.scenario(passos=[{"dorme": 2}]))
    assert run_direct(harness, background=True) == 0
    out = capsys.readouterr().out
    session = harness.manager.list_orchestrator()[0]
    assert session.alias in out and str(session.pid) in out and session.terminal_id is None
    assert wait_for(lambda: harness.manager.get(session.id).status != "active")


def test_sessao_lancada_pelo_repl_recebe_sigint_e_o_repl_continua_aberto(harness: SessionHarness):
    harness.use_scenario(harness.scenario(passos=[{"subtarefa": "s1", "dorme": 10}]))
    repl, _ = make_repl(harness)
    assert repl.open() is None
    with terminal_patches():
        asyncio.run(repl.handle("nova-pesquisa estudar iris"))
    session = harness.manager.list_orchestrator()[0]
    assert wait_for(lambda: harness.manager.get(session.id).payload.get("subtarefas"))  # o laço já está ativo
    os.kill(session.pid, signal.SIGINT)
    assert wait_for(lambda: harness.manager.get(session.id).status != "active", timeout=15)
    assert harness.manager.get(session.id).payload["motivo_parada"] == "interrompida_pesquisador"
    assert PgPresenceStore().get(repl.presence.terminal_id).ended_at is None  # o REPL segue aberto
    repl.close()


def test_memoria_abaixo_do_minimo_no_comando_direto_nao_cria_sessao(harness: SessionHarness):
    starter = harness.starter(monitor=__import__("types").SimpleNamespace(get_memory_usage=lambda: {"available_mb": 1}))
    with terminal_patches(), patch.object(direct, "sweep_stopped"), patch("src.config.MIN_AVAILABLE_MEMORY_MB", 512):
        code = asyncio.run(direct.start_research("t", args(), mode="auto", budget=BUDGET, background=False, starter=starter))
    assert code == 5 and harness.manager.list_orchestrator() == []
    assert MEMORY_POLICY_FAIL == "falhar"
