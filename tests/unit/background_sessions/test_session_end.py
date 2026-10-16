"""Fim da sessão por modo e presença do terminal (v18.7-background-sessions, tarefas 4.1 a 4.5)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cli.session_process import watch_presence
from src.orchestration.autonomous_loop import AutonomousLoop
from src.orchestration.orchestrator import AgentResult, AgentTask
from src.orchestration.usage import (
    StopReason,
    UsageBudget,
    UsageTracker,
    clear_interrupt,
    clear_suspension,
    interrupt_requested,
    request_interrupt,
    request_suspension,
    suspension_requested,
)
from src.session.exit_codes import EXIT_AWAITING_RESEARCHER, exit_code_for
from src.session.presence import (
    END_EXIT,
    END_OBSOLETE,
    TIPO_DIRETO,
    TIPO_REPL,
    PresenceRow,
    TerminalAlreadyOpenError,
    TerminalPresence,
    terminal_present,
)
from tests.support.fake_clock import FakeClock
from tests.support.session_fakes import InMemoryPresenceStore
from tests.unit.test_autonomous_loop import _make_closing_test_orchestrator

pytestmark = pytest.mark.unit

BUDGET = UsageBudget(
    max_tokens=500_000, max_minutes=120, max_task_retries=3, max_connection_retries=20, closing_reserve_pct=0.05
)


@pytest.fixture(autouse=True)
def _clean_flags():
    clear_interrupt()
    clear_suspension()
    yield
    clear_interrupt()
    clear_suspension()


def _loop(orchestrator, *, mode="assisted", tokens=0):
    loop = AutonomousLoop(orchestrator)
    loop._session_mode = mode
    loop._usage_tracker = UsageTracker(
        BUDGET, execution_id="exec", token_reader=lambda: tokens, connection_retry_reader=lambda: 0,
        clock=lambda: 0.0, pending_stop=lambda: loop._pending_stop("exec"),
    )
    return loop


async def _run(loop):
    with (
        patch("src.orchestration.autonomous_loop.get_telemetry", return_value=MagicMock()),
        patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)),
    ):
        return await loop._run_complex_path("tarefa", "exec")


# -- sinalizador de suspensão (4.1) --------------------------------------------------------------------------------


def test_suspensao_e_o_ultimo_motivo_pendente_e_um_limite_prevalece():
    assert AutonomousLoop._pending_model_stop("exec") is None
    request_suspension()
    assert AutonomousLoop._pending_model_stop("exec") == StopReason.SUSPENDED
    request_interrupt()
    assert interrupt_requested() and AutonomousLoop._pending_model_stop("exec") == StopReason.INTERRUPTED

    clear_interrupt()
    tracker = UsageTracker(
        BUDGET, execution_id="e", token_reader=lambda: 10**9, connection_retry_reader=lambda: 0,
        clock=lambda: 0.0, pending_stop=lambda: StopReason.SUSPENDED,
    )
    assert tracker.check().stop_reason == StopReason.TOKENS  # o limite no mesmo ponto prevalece


def test_o_novo_motivo_tem_classe_de_saida_4():
    assert exit_code_for(StopReason.SUSPENDED.value) == EXIT_AWAITING_RESEARCHER


@pytest.mark.asyncio
async def test_suspensao_sem_carencia_fecha_sem_consolidar_e_marca_a_sessao():
    orchestrator = _make_closing_test_orchestrator([AgentTask(agent_id="researcher", prompt="p", task_name="t1")])
    loop = _loop(orchestrator)
    request_suspension()
    result = await _run(loop)

    orchestrator._run_planning_loop.assert_not_called()
    orchestrator._execute_agent.assert_not_called()  # nenhuma consolidação via LLM
    assert result.succeeded == 0
    kwargs = orchestrator.session_manager.update.call_args.kwargs
    assert kwargs["status"] == "suspensa_sem_pesquisador"
    assert kwargs["payload"]["motivo_parada"] == "suspensa_sem_pesquisador"
    assert kwargs["payload"]["checkpoint"]["consolidation_pending"] is True


@pytest.mark.asyncio
async def test_subtarefa_em_curso_termina_e_a_seguinte_nao_comeca():
    """Caso 4: o terminal sai com uma subtarefa em curso; ela conclui, a dependente não é despachada."""
    t1 = AgentTask(agent_id="developer", prompt="p1", task_name="t1")
    t2 = AgentTask(agent_id="developer", prompt="p2", task_name="t2", depends_on=["t1"])
    orchestrator = _make_closing_test_orchestrator([t1, t2])
    ran: list[str] = []

    async def execute(task, master_session_id=None):
        ran.append(task.task_name)
        request_suspension()  # o terminal saiu enquanto t1 rodava
        await asyncio.sleep(0.05)  # sem cancelamento: o que está em curso termina
        return AgentResult(agent_id="developer", session_id="s", status="success", response={"text": "ok"})

    orchestrator._execute_agent = AsyncMock(side_effect=execute)
    loop = _loop(orchestrator)
    result = await _run(loop)

    assert ran == ["t1"]
    assert result.succeeded >= 1
    kwargs = orchestrator.session_manager.update.call_args.kwargs
    assert kwargs["status"] == "suspensa_sem_pesquisador"
    assert kwargs["payload"]["motivo_parada"] == "suspensa_sem_pesquisador"
    assert orchestrator._execute_agent.await_count == 1  # t2 nunca chegou ao agente


@pytest.mark.asyncio
async def test_so_pedidos_pendentes_vira_aguarda_pesquisador():
    """Caso 3 (unidade): ``_suspend_session`` grava ``aguarda_pesquisador`` e o código de saída é 4."""
    orchestrator = _make_closing_test_orchestrator([])
    current = MagicMock(payload={"mode": "semi"})
    orchestrator.session_manager.get.return_value = current
    loop = _loop(orchestrator, mode="semi")
    result = await loop._suspend_session("exec", [], [], "Sessão aguarda o pesquisador")
    args, kwargs = orchestrator.session_manager.update.call_args
    assert args == ("exec",) and kwargs["status"] == "aguarda_pesquisador"
    assert kwargs["payload"]["motivo_parada"] == "aguarda_pesquisador"
    assert exit_code_for(kwargs["payload"]["motivo_parada"]) == EXIT_AWAITING_RESEARCHER
    assert result.results[-1].response["text"].startswith("Sessão aguarda")


# -- fechamento da requisição --------------------------------------------------------------------------------------


def test_status_pausados_continuam_retomaveis_e_o_codigo_de_saida_vai_ao_payload():
    from src.orchestration.orchestrator import Orchestrator
    from src.session.states import PAUSED_STATUSES, UNFINISHED_STATUSES
    from tests.support.session_fakes import FakeSessionManager

    assert set(PAUSED_STATUSES) <= set(UNFINISHED_STATUSES)
    manager = FakeSessionManager()
    manager.add("s1", "suspensa_sem_pesquisador", {"motivo_parada": "suspensa_sem_pesquisador"})
    orchestrator = Orchestrator(session_manager=manager, output_manager=MagicMock(), agent_runtime=MagicMock())
    orchestrator._record_exit_code("s1")
    assert manager.get("s1").payload["codigo_saida"] == 4 and manager.get("s1").status == "suspensa_sem_pesquisador"


# -- presença do terminal (4.3 e 4.5) ------------------------------------------------------------------------------


def _presence(store, clock, tipo=TIPO_REPL, **over):
    kwargs = dict(store=store, clock=clock.now, heartbeat_seconds=10, stale_seconds=60, pid=100, host="h1",
                  pid_alive=lambda pid: True)
    kwargs.update(over)
    return TerminalPresence(tipo, **kwargs)


def test_batimento_de_presenca_com_os_padroes_em_35_segundos():
    clock, store = FakeClock(), InMemoryPresenceStore()
    presence = _presence(store, clock)
    terminal_id = presence.start()
    beats = 0
    for _ in range(7):  # 35 s em passos de 5 s
        clock.advance(5)
        beats += presence.tick()
    assert beats == 3  # em 10, 20 e 30 s
    assert store.get(terminal_id).heartbeat_at == clock.now() - 5
    assert presence.is_present() and terminal_present(terminal_id, store=store, stale_seconds=60, clock=clock.now)


def test_presenca_envelhecida_nao_conta():
    clock, store = FakeClock(), InMemoryPresenceStore()
    terminal_id = _presence(store, clock).start()
    clock.advance(60)
    assert terminal_present(terminal_id, store=store, stale_seconds=60, clock=clock.now)
    clock.advance(1)  # 61 s sem batimento
    assert not terminal_present(terminal_id, store=store, stale_seconds=60, clock=clock.now)
    assert not terminal_present(None, store=store, clock=clock.now)
    assert not terminal_present("desconhecido", store=store, clock=clock.now)


def test_saida_normal_grava_ended_at_e_end_reason_saida():
    clock, store = FakeClock(), InMemoryPresenceStore()
    presence = _presence(store, clock)
    terminal_id = presence.start()
    clock.advance(3)
    presence.stop()
    row = store.get(terminal_id)
    assert row.ended_at == clock.now() and row.end_reason == END_EXIT
    assert not presence.is_present()
    assert store.last_repl_end() == row.ended_at


def test_segundo_repl_e_recusado_e_o_comando_direto_convive():
    clock, store = FakeClock(), InMemoryPresenceStore()
    _presence(store, clock).start()
    clock.advance(5)
    with pytest.raises(TerminalAlreadyOpenError, match="já há um terminal"):
        _presence(store, clock, pid=101).start()
    _presence(store, clock, TIPO_DIRETO, pid=102).start()  # o comando direto não é exclusivo
    assert len(store.rows) == 2


def test_presenca_velha_vira_obsoleta_e_nao_impede_a_abertura():
    clock, store = FakeClock(), InMemoryPresenceStore()
    old = _presence(store, clock).start()
    clock.advance(600)  # 10 minutos sem batimento
    new = _presence(store, clock, pid=101).start()
    assert store.get(old).end_reason == END_OBSOLETE and store.get(old).ended_at == clock.now()
    assert store.get(new).ended_at is None


def test_pid_morto_no_mesmo_host_e_obsoleto_mas_em_outro_host_vale_o_batimento():
    clock, store = FakeClock(), InMemoryPresenceStore()
    other_host = PresenceRow("outro", TIPO_REPL, 7, "h2", clock.now(), clock.now())
    store.insert(other_host)
    same_host = PresenceRow("local", TIPO_REPL, 8, "h1", clock.now(), clock.now())
    store.rows.pop("outro")
    store.insert(same_host)
    new = _presence(store, clock, pid=101, pid_alive=lambda pid: False)
    new.start()  # o REPL local de PID morto é obsoleto, mesmo com batimento recente
    assert store.get("local").end_reason == END_OBSOLETE
    store.insert(other_host)
    with pytest.raises(TerminalAlreadyOpenError):  # em outro host o PID não se confere: vale o batimento
        _presence(store, clock, pid=102, pid_alive=lambda pid: False).start()


def test_falha_de_batimento_nao_derruba_o_terminal():
    clock = FakeClock()

    class Broken(InMemoryPresenceStore):
        def touch(self, terminal_id, heartbeat_at):
            raise RuntimeError("banco fora")

    presence = _presence(Broken(), clock)
    presence.start()
    clock.advance(10)
    assert presence.tick() is False


# -- leitura da presença pela sessão assisted (4.3) ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_sessao_assisted_pede_suspensao_quando_o_terminal_some():
    present = iter([True, True, False])
    await asyncio.wait_for(watch_presence("t1", interval=0.01, present=lambda _tid: next(present)), 2)
    assert suspension_requested()


@pytest.mark.asyncio
async def test_sessao_assisted_sem_terminal_se_suspende_e_leitura_com_falha_nao_suspende():
    await asyncio.wait_for(watch_presence(None, interval=0.01, present=lambda _tid: False), 2)
    assert suspension_requested()
    clear_suspension()

    calls = []

    def flaky(_tid):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("banco fora")
        return False

    await asyncio.wait_for(watch_presence("t1", interval=0.01, present=flaky), 2)
    assert len(calls) == 3 and suspension_requested()  # só suspende quando consegue ler e vê a ausência
