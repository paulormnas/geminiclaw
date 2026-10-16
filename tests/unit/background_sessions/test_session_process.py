"""Processo da sessão, batimento com sinal do laço e limpeza de sandboxes (v18.7-background-sessions, 3.2 a 3.7)."""

from __future__ import annotations

import asyncio
import builtins
import dataclasses
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.cli.session_process as session_process
from src.cli.session_process import (
    SessionRunner,
    StdinForbiddenError,
    chain_session_ids,
    install_input_guard,
    register_session_process,
)
from src.orchestration.usage import UsageBudget
from src.session.exit_codes import EXIT_ERROR, EXIT_INTERRUPTED, EXIT_SESSION_LOST
from src.session.heartbeat import LoopTick, SessionHeartbeat
from src.session.launcher import LaunchSpec, write_launch_file
from tests.support.fake_clock import FakeClock
from tests.support.session_fakes import FakeSessionManager

pytestmark = pytest.mark.unit

BUDGET = dataclasses.asdict(UsageBudget(1000, 10.0, 3, 3, 0.05, 1_000_000))


def make_spec(**over) -> LaunchSpec:
    base = dict(
        tipo="nova",
        prompt="tarefa",
        modo="auto",
        orcamento=BUDGET,
        contexto={"dir": "input_context", "digest": "diferente"},
        primeiro_plano=False,
    )
    base.update(over)
    return LaunchSpec(**base)


# -- stdin proibido ------------------------------------------------------------------------------------------------


def test_input_levanta_stdin_forbidden_error():
    original = builtins.input
    try:
        install_input_guard()
        with pytest.raises(StdinForbiddenError):
            input("pergunta?")
        with pytest.raises(StdinForbiddenError):
            asyncio.run(asyncio.to_thread(input, "dentro de uma thread"))
    finally:
        builtins.input = original


# -- lançamento recusado -------------------------------------------------------------------------------------------


def test_contexto_alterado_depois_da_confirmacao_sai_com_1_sem_sessao(tmp_path: Path, capsys):
    ctx = tmp_path / "input_context"
    ctx.mkdir()
    (ctx / "a.txt").write_text("conteúdo novo")
    runner = SessionRunner(make_spec(contexto={"dir": str(ctx), "digest": "confirmado-antes"}))
    with patch("src.orchestration.orchestrator.Orchestrator") as orchestrator:
        assert asyncio.run(runner.run()) == EXIT_ERROR
    orchestrator.assert_not_called()  # nem o orquestrador nem a sessão chegam a existir
    assert "mudou depois da confirmação" in capsys.readouterr().out


def test_main_recusa_lancamento_invalido(tmp_path: Path, capsys):
    bad = tmp_path / "x.json"
    bad.write_text("[]")
    with patch("src.egress.routing.install_provider_resolver"):
        assert session_process.main(["--launch", str(bad)]) == EXIT_ERROR
    assert "Lançamento recusado" in capsys.readouterr().err
    assert not bad.exists()


def test_main_roda_o_runner_e_devolve_o_codigo(tmp_path: Path):
    path = write_launch_file(make_spec(), tmp_path)

    class Runner:
        def __init__(self, spec):
            self.spec = spec

        async def run(self):
            return 3

    original_input, original_sigint = builtins.input, session_process.signal.getsignal(session_process.signal.SIGINT)
    try:
        with patch("src.egress.routing.install_provider_resolver"):
            code = session_process.main(["--launch", str(path)], runner_factory=Runner)
    finally:
        builtins.input = original_input
        session_process.signal.signal(session_process.signal.SIGINT, original_sigint)
    assert code == 3 and not path.exists()


# -- registro do processo e código de saída ------------------------------------------------------------------------


def test_registro_grava_pid_host_apelido_e_resumo():
    manager = FakeSessionManager()
    manager.register_process = MagicMock()
    manager.aliases_in_use = MagicMock(return_value=["iris-01"])
    created = manager.create("orchestrator", "s1")
    alias = register_session_process(manager, created, make_spec(prompt="estudar iris"), title="Iris Dataset")
    assert alias == "irisdataset-01" or alias.startswith("irisdataset")
    kwargs = manager.register_process.call_args.kwargs
    assert kwargs["pid"] > 0 and kwargs["host"] and kwargs["process_started_at"]
    assert kwargs["alias"] == alias and kwargs["resumo"] == "estudar iris"


def test_retomada_herda_o_apelido_da_origem():
    manager = FakeSessionManager()
    manager.register_process = MagicMock()
    source = manager.create("orchestrator", "origem")
    source.alias = "iris-03"
    spec = make_spec(tipo="retomada", retomada={"session_id": "origem", "confirmado_resolvida": False})
    assert register_session_process(manager, manager.create("orchestrator", "nova"), spec, title=None) == "iris-03"


def test_codigo_de_saida_vem_do_motivo_gravado_na_sessao():
    manager = FakeSessionManager()
    manager.add("s1", "closed", {"motivo_parada": "limite_tokens"})
    manager.add("s2", "closed", {"motivo_parada": "solucao_encontrada"})
    manager.add("s3", "closed", {})
    runner = SessionRunner(make_spec())
    assert runner._exit_code_from_session(manager, EXIT_ERROR, "s1") == 3
    assert runner._exit_code_from_session(manager, EXIT_ERROR, "s2") == 0
    assert runner._exit_code_from_session(manager, EXIT_ERROR, "s3") == EXIT_ERROR
    assert runner._exit_code_from_session(manager, 7, "inexistente") == 7


def test_cadeia_da_sessao_lista_os_antecessores():
    manager = FakeSessionManager()
    manager.add("a", "closed", {})
    manager.add("b", "closed", {"continues_session_id": "a"})
    manager.add("c", "active", {"continues_session_id": "b"})
    assert chain_session_ids(manager, "c") == ["c", "b", "a"]
    manager.add("x", "active", {"continues_session_id": "x"})  # ciclo defensivo
    assert chain_session_ids(manager, "x") == ["x"]


# -- sessão perdida ------------------------------------------------------------------------------------------------


def test_sessao_perdida_remove_so_os_sandboxes_da_cadeia_cancela_e_arma_a_saida():
    manager = FakeSessionManager()
    manager.add("a", "closed", {})
    manager.add("b", "interrompida", {"continues_session_id": "a", "continued_by": "z"})
    runner = SessionRunner(make_spec(), orchestrator=SimpleNamespace(session_manager=manager))
    runner._loop, runner._task = MagicMock(), MagicMock()
    timer = MagicMock()
    with (
        patch("src.skills.code.sandbox.cleanup_sandbox_containers") as cleanup,
        patch.object(session_process.threading, "Timer", return_value=timer) as timer_cls,
    ):
        runner._on_session_lost("b")
    cleanup.assert_called_once_with(["b", "a"])
    runner._loop.call_soon_threadsafe.assert_called_once_with(runner._task.cancel)
    assert timer_cls.call_args.args[1].__name__ == "<lambda>" and timer.daemon is True
    timer.start.assert_called_once()
    assert EXIT_SESSION_LOST == 6


def test_cancelamento_por_sessao_perdida_sai_com_6_e_por_interrupcao_com_130():
    from src.session.launcher import context_digest

    async def go(lost: bool) -> int:
        orchestrator = SimpleNamespace(
            session_manager=FakeSessionManager(), _lost_sessions={"s1"} if lost else set(), session_lost_handler=None
        )

        async def handle_request(*_a, **_k):
            raise asyncio.CancelledError

        orchestrator.handle_request = handle_request
        spec = make_spec(contexto={"dir": "inexistente", "digest": context_digest("inexistente")})
        runner = SessionRunner(spec, orchestrator=orchestrator)
        runner.session_id = "s1"
        with patch("src.research_data.context_loader.ContextLoader") as loader:
            loader.return_value.load.return_value = None
            return await runner.run()

    async def routed(*_a, **_k):
        return MagicMock()

    with patch("src.llm.session.build_session_routing", routed):
        assert asyncio.run(go(True)) == EXIT_SESSION_LOST
        assert asyncio.run(go(False)) == EXIT_INTERRUPTED


# -- batimento com sinal do laço (§1.8) ----------------------------------------------------------------------------


def test_sinal_do_laco_idade_e_iso_com_relogio_falso():
    clock = FakeClock()
    tick = LoopTick(10, clock=clock.now)
    assert tick.age() == 0
    clock.advance(400)
    assert tick.age() == 400 and tick.iso().endswith("+00:00")


def test_tique_do_laco_atualiza_e_para():
    async def go():
        tick = LoopTick(0.01).start()
        first = tick.last
        await asyncio.sleep(0.1)
        advanced = tick.last > first
        tick.stop()
        await asyncio.sleep(0.05)
        stopped = tick._task.done()
        return advanced, stopped

    assert asyncio.run(go()) == (True, True)


def test_recusa_por_continued_by_aciona_o_processo_antigo_uma_vez():
    lost = threading.Event()
    calls = []
    beat = SessionHeartbeat(
        lambda: False, lambda: False, interval=0.01, is_lost=lambda: True,
        on_lost=lambda: (calls.append(1), lost.set()),
    ).start()
    assert lost.wait(2)
    beat._thread.join(2)
    assert beat.lost and calls == [1] and not beat._thread.is_alive()


def test_recusa_sem_continuacao_tenta_reafirmar_e_nao_declara_perda():
    reasserted = threading.Event()

    def reassert():
        reasserted.set()
        return True

    beat = SessionHeartbeat(lambda: False, reassert, interval=0.01, is_lost=lambda: True, on_lost=lambda: 1 / 0).start()
    assert reasserted.wait(2)
    time.sleep(0.05)
    beat.stop()
    assert not beat.lost and beat.reasserted >= 1


def test_laco_lento_nao_apaga_o_batimento_e_o_laco_parado_nao_reafirma():
    """Padrões 300/30/900 com ``FakeClock``: o batimento segue atualizando; o sinal do laço envelhece à parte."""
    clock = FakeClock()
    tick = LoopTick(10, clock=clock.now)
    stale_limit = 900
    beats = []
    for _ in range(14):  # 14 batimentos de 30 s = 420 s sem novo tique do laço
        clock.advance(30)
        beats.append((clock.now(), tick.iso()))
    assert tick.age() == 420 and tick.age() < stale_limit  # laço lento (<900 s): continua reafirmável
    assert len({b[1] for b in beats}) == 1  # loop_beat_at ficou em t=0 enquanto updated_at andou
    clock.advance(500)
    assert tick.age() >= stale_limit  # 920 s: travamento, não lentidão


def test_orquestrador_reafirma_so_com_laco_vivo_e_declara_perda_se_continuada():
    from src.orchestration.orchestrator import Orchestrator

    manager = FakeSessionManager()
    manager.add("s1", "interrompida", {"continued_by": "s2"})
    manager.heartbeat = MagicMock(return_value=False)
    manager.reassert_active = MagicMock(return_value=False)
    orchestrator = Orchestrator(session_manager=manager, output_manager=MagicMock(), agent_runtime=MagicMock())
    handled = threading.Event()
    orchestrator.session_lost_handler = lambda sid: handled.set()

    async def go():
        with (
            patch("src.config.SESSION_HEARTBEAT_SECONDS", 0.01),
            patch("src.config.SESSION_LOOP_TICK_SECONDS", 0.01),
        ):
            heartbeat = orchestrator._start_heartbeat("s1")
            await asyncio.to_thread(handled.wait, 2)
            await asyncio.to_thread(heartbeat.stop)

    asyncio.run(go())
    assert handled.is_set() and "s1" in orchestrator._lost_sessions
    assert manager.heartbeat.call_args.args[1]  # o batimento leva loop_beat_at


# -- limpeza de sandboxes por sessão (§6.1) ------------------------------------------------------------------------


def _container(session_id: str):
    c = MagicMock()
    c.labels = {"project": "geminiclaw", "session_id": session_id}
    return c


def test_containers_de_duas_sessoes_so_o_da_sessao_perdida_e_removido():
    from src.skills.code import sandbox

    c1, c2 = _container("s1"), _container("s2")
    client = MagicMock()
    client.containers.list.return_value = [c1, c2]
    with patch.object(sandbox.docker, "from_env", return_value=client):
        assert sandbox.cleanup_sandbox_containers(["s1"]) == 1
        assert sandbox.cleanup_sandbox_containers([]) == 0
    c1.remove.assert_called_once_with(force=True)
    c2.remove.assert_not_called()


def test_limpeza_global_remove_todos_e_so_existe_como_funcao_explicita():
    from src.skills.code import sandbox

    containers = [_container("s1"), _container("s2")]
    client = MagicMock()
    client.containers.list.return_value = containers
    with patch.object(sandbox.docker, "from_env", return_value=client):
        assert sandbox.cleanup_all_sandbox_containers() == 2
    assert not hasattr(session_process, "cleanup_all_sandbox_containers")


def test_container_de_preparacao_leva_o_rotulo_da_sessao(tmp_path: Path):
    from src.skills.code.sandbox import PythonSandbox

    with patch("src.skills.code.sandbox.docker.from_env", return_value=MagicMock()):
        sandbox = PythonSandbox(work_dir=str(tmp_path / "work"))
    client = MagicMock()
    sandbox._client = client
    sandbox._create_prep_container({}, "s1", "tarefa")
    labels = client.containers.run.call_args.kwargs["labels"]
    assert labels["session_id"] == "s1" and labels["geminiclaw.role"] == "sandbox-prep"


def test_diretorio_de_lancamento_nunca_e_montado_no_sandbox():
    root = Path(__file__).resolve().parents[3] / "src" / "skills" / "code" / "sandbox.py"
    source = root.read_text(encoding="utf-8")
    assert ".launch" not in source  # o sandbox só monta outputs/<session_id>/<tarefa>
