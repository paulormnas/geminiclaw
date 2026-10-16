"""REPL, iniciador e comando direto (v18.7-background-sessions, tarefas 3.5, 5.1 a 5.3)."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.cli.direct as direct
from src.cli.repl import Repl
from src.cli.session_start import (
    MEMORY_POLICY_ASK,
    MEMORY_POLICY_FAIL,
    LaunchRefused,
    exit_code_of,
    wait_foreground,
)
from src.session.exit_codes import EXIT_ERROR, EXIT_LOW_MEMORY
from src.session.presence import TerminalPresence
from tests.support.fake_clock import FakeClock
from tests.support.fake_gate import FakeGate
from tests.support.session_fakes import FakeSessionManager, InMemoryPresenceStore
from tests.support.starter_world import BUDGET, args, make_starter, patched_terminal

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]


class Out:
    def __init__(self):
        self.lines: list[str] = []

    def write(self, text: str) -> None:
        self.lines.append(text)

    def notify(self, text: str) -> None:
        self.lines.append(text)

    waiting_for_input = False

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def make_repl(tmp_path, *, inputs=(), available_mb=4096, manager=None, mode="auto", last_end=None):
    manager = manager or FakeSessionManager()
    answers = iter(inputs)
    out = Out()
    clock = FakeClock()
    store = InMemoryPresenceStore()
    presence = TerminalPresence("repl", store=store, clock=clock.now, pid_alive=lambda pid: True)
    starter, launched = make_starter(
        tmp_path, manager=manager, available_mb=available_mb, input_fn=lambda _p: next(answers, "sair")
    )
    starter._output = out.write
    starter.wait_registered = AsyncMock(return_value=SimpleNamespace(alias="sessao-01", pid=4242))
    repl = Repl(
        mode=mode, explicit_mode=None, budget=BUDGET, args=args(), starter=starter, manager=manager,
        presence=presence, input_fn=lambda p: next(answers, "sair"), console=out, now=clock.now,
        sweep_interval=3600, recover=lambda s: None, gate=FakeGate(), reminder_interval=3600,
    )
    repl._last_end = last_end
    return repl, launched, out, store, manager


def unfinished(manager, sid, status, motivo, *, alias=None, mode="auto", updated=0.0):
    sess = manager.add(sid, status, {"mode": mode, "motivo_parada": motivo, "prompt": f"tarefa {sid}"})
    sess.alias = alias or sid
    sess.updated_at = FakeClock().iso(updated)
    return sess


# -- nova-pesquisa e comandos (5.1) --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nova_pesquisa_lanca_em_segundo_plano_e_o_prompt_volta(tmp_path):
    repl, launched, out, store, _ = make_repl(tmp_path, inputs=["nova-pesquisa tarefa de teste", "sair"])
    assert repl.open() is None
    with patched_terminal():
        await repl.loop()
    repl.close()
    assert len(launched) == 1
    assert "iniciada em segundo plano (PID 4242)" in out.text and "sessao-01" in out.text
    row = next(iter(store.rows.values()))
    assert row.ended_at is not None and row.end_reason == "saida"  # `sair` grava a saída normal


@pytest.mark.asyncio
async def test_texto_livre_e_recusado_com_a_dica_e_comando_desconhecido_tambem(tmp_path):
    repl, launched, out, *_ = make_repl(tmp_path)
    for line in ("estude a base iris", "sessions-x"):
        assert await repl.handle(line) is True
    assert launched == [] and out.text.count("nova-pesquisa <tarefa>") == 2
    assert await repl.handle("nova-pesquisa") is True and "Use: nova-pesquisa" in out.text
    assert await repl.handle("SAIR") is False


@pytest.mark.asyncio
async def test_sessions_lista_as_pesquisas_e_os_containers_tem_nomes_novos(tmp_path):
    repl, _, out, _, manager = make_repl(tmp_path)
    unfinished(manager, "a-01", "aguarda_pesquisador", "aguarda_pesquisador")
    manager.add("b-01", "active", {"mode": "auto"}).alias = "b-01"
    with patch("src.cli.repl.show_sandboxes") as show, patch("src.cli.repl.stop_sandboxes") as stop:
        await repl.handle("sessions")
        assert "a-01" in out.text and "b-01" in out.text
        await repl.handle("sandboxes")
        await repl.handle("parar-sandboxes sess_1")
    show.assert_called_once()
    stop.assert_called_once_with(session_id="sess_1")


@pytest.mark.asyncio
async def test_parar_sandboxes_de_todas_as_pesquisas_exige_confirmacao(tmp_path):
    repl, *_ = make_repl(tmp_path, inputs=["n", "s"])
    with (
        patch("src.cli.repl.stop_sandboxes") as stop,
        patch("src.skills.code.sandbox.cleanup_all_sandbox_containers") as cleanup,
    ):
        await repl.handle("parar-sandboxes")  # "n": nada acontece
        stop.assert_not_called()
        cleanup.assert_not_called()
        await repl.handle("parar-sandboxes")  # "s": limpeza global explícita
    stop.assert_called_once_with(session_id=None)
    cleanup.assert_called_once()


# -- verificação de memória (casos 14 e 15) ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repl_abaixo_do_minimo_mostra_o_aviso_e_desiste_com_n(tmp_path):
    manager = FakeSessionManager()
    running = manager.add("iris-01", "active", {"mode": "auto"})
    running.alias, running.pid = "iris-01", 77
    repl, launched, out, *_ = make_repl(tmp_path, inputs=["n"], available_mb=300, manager=manager)
    with patched_terminal(), patch("src.config.MIN_AVAILABLE_MEMORY_MB", 512):
        await repl.handle("nova-pesquisa tarefa")
    assert launched == []
    assert "300" in out.text and "MIN_AVAILABLE_MEMORY_MB" in out.text and "iris-01" in out.text
    assert "cancelado" in out.text
    assert [s.id for s in manager.rows.values()] == ["iris-01"]  # nenhuma sessão nova


@pytest.mark.asyncio
async def test_repl_abaixo_do_minimo_inicia_mesmo_assim_com_s(tmp_path):
    repl, launched, *_ = make_repl(tmp_path, inputs=["s"], available_mb=300)
    with patched_terminal(), patch("src.config.MIN_AVAILABLE_MEMORY_MB", 512):
        await repl.handle("nova-pesquisa tarefa")
    assert len(launched) == 1


@pytest.mark.asyncio
async def test_comando_direto_abaixo_do_minimo_falha_com_5_antes_do_processo(tmp_path):
    starter, launched = make_starter(tmp_path, available_mb=300)
    with patched_terminal(), patch("src.config.MIN_AVAILABLE_MEMORY_MB", 512):
        with pytest.raises(LaunchRefused) as info:
            await starter.start_new(
                "tarefa", mode="auto", budget=BUDGET, args=args(), terminal_id=None, foreground=True,
                memory_policy=MEMORY_POLICY_FAIL,
            )
    assert info.value.code == EXIT_LOW_MEMORY and "300" in str(info.value) and "MIN_AVAILABLE_MEMORY_MB" in str(info.value)
    assert launched == []


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [MEMORY_POLICY_ASK, MEMORY_POLICY_FAIL])
async def test_memoria_desconhecida_nao_falha_so_registra_evento(tmp_path, policy):
    starter, launched = make_starter(tmp_path, available_mb=None)
    with patched_terminal(), patch("src.observability.telemetry.get_telemetry") as tel:
        await starter.start_new(
            "tarefa", mode="auto", budget=BUDGET, args=args(), terminal_id=None, foreground=False, memory_policy=policy
        )
    assert len(launched) == 1
    assert tel.return_value.record_agent_event.call_args.kwargs["event_type"] == "memoria_desconhecida"


@pytest.mark.asyncio
async def test_retomada_tambem_verifica_a_memoria_e_a_origem_nao_muda(tmp_path):
    manager = FakeSessionManager()
    origin = unfinished(manager, "a-01", "suspensa_sem_pesquisador", "suspensa_sem_pesquisador")
    starter, launched = make_starter(tmp_path, available_mb=300, manager=manager, input_fn=lambda _p: "n")
    prep = SimpleNamespace(
        mode="auto", prompt="p", accumulated={}, state=SimpleNamespace(source_session_id="a-01", completed={}),
    )
    before = (origin.status, dict(origin.payload), origin.updated_at)
    with (
        patched_terminal(),
        patch("src.config.MIN_AVAILABLE_MEMORY_MB", 512),
        patch("src.session.resume.prepare_resume", AsyncMock(return_value=prep)),
        patch("src.knowledge.factory.open_knowledge_runtime", return_value=None),
        patch("src.knowledge.factory.open_graph_store", return_value=MagicMock()),
    ):
        with pytest.raises(LaunchRefused, match="cancelado"):
            await starter.start_resume(
                "a-01", mode=None, budget=BUDGET, args=args(), terminal_id=None, foreground=False,
                memory_policy=MEMORY_POLICY_ASK,
            )
    assert launched == [] and (origin.status, origin.payload, origin.updated_at) == before
    assert "continued_by" not in origin.payload


@pytest.mark.asyncio
async def test_retomada_leva_a_confirmacao_de_sessao_resolvida_ao_lancamento(tmp_path):
    starter, launched = make_starter(tmp_path)
    prep = SimpleNamespace(
        mode="auto", prompt="p", accumulated={"tokens": 5, "minutos": 1}, state=SimpleNamespace(
            source_session_id="a-01", completed={"t1": 1}),
    )

    async def fake_prepare(**kw):
        assert kw["confirm"]("continuar explorando?") is True  # o terminal confirma, o processo só recebe o resultado
        return prep

    with (
        patched_terminal(),
        patch("src.session.resume.prepare_resume", fake_prepare),
        patch("src.knowledge.factory.open_knowledge_runtime", return_value=None),
        patch("src.knowledge.factory.open_graph_store", return_value=MagicMock()),
    ):
        started = await starter.start_resume(
            "a-01", mode=None, budget=BUDGET, args=args(), terminal_id="t", foreground=False,
            memory_policy=MEMORY_POLICY_FAIL, confirm=lambda q: True,
        )
    assert started.spec.tipo == "retomada" and started.spec.retomada == {
        "session_id": "a-01", "confirmado_resolvida": True}
    assert len(launched) == 1


# -- pesquisas não finalizadas ao abrir (casos 7, 8 e 9) -----------------------------------------------------------


@pytest.mark.asyncio
async def test_caso_7_lista_e_pergunta_so_das_nao_finalizadas_em_ordem_de_atualizacao(tmp_path):
    manager = FakeSessionManager()
    unfinished(manager, "a-01", "suspensa_sem_pesquisador", "suspensa_sem_pesquisador", updated=10)
    unfinished(manager, "b-01", "aguarda_pesquisador", "aguarda_pesquisador", updated=20)
    unfinished(manager, "c-01", "interrompida", "interrompida", updated=30)
    unfinished(manager, "d-01", "closed", "solucao_encontrada", updated=40)
    questions: list[str] = []
    answers = iter(["m", "m", "m"])

    repl, launched, out, *_ = make_repl(tmp_path, manager=manager, last_end=FakeClock().now() - 5)

    def ask(prompt):
        questions.append(prompt)
        return next(answers)

    repl._input = ask
    await repl.review_unfinished()
    repl.close()
    assert len(questions) == 3 and launched == []
    shown = out.text
    assert shown.index("a-01") < shown.index("b-01") < shown.index("c-01")
    assert "d-01" in shown and "solução encontrada" in shown.lower() or "solucao_encontrada" in shown
    assert "[r]etomar / [m]anter / [e]ncerrar" in questions[0]


@pytest.mark.asyncio
async def test_caso_8_retomar_cria_o_processo_pela_retomada_existente(tmp_path):
    manager = FakeSessionManager()
    origin = unfinished(manager, "a-01", "suspensa_sem_pesquisador", "suspensa_sem_pesquisador")
    repl, *_ = make_repl(tmp_path, inputs=["r"], manager=manager)
    repl.starter.start_resume = AsyncMock(return_value=MagicMock())
    repl._last_end = None
    await repl.review_unfinished()
    repl.close()
    kwargs = repl.starter.start_resume.await_args
    assert kwargs.args == (origin.id,) and kwargs.kwargs["mode"] is None and kwargs.kwargs["foreground"] is False
    assert kwargs.kwargs["memory_policy"] == MEMORY_POLICY_ASK


@pytest.mark.asyncio
async def test_caso_9_manter_nao_altera_e_encerrar_fecha_sem_chamar_llm(tmp_path):
    manager = FakeSessionManager()
    keep = unfinished(manager, "a-01", "suspensa_sem_pesquisador", "suspensa_sem_pesquisador", updated=10)
    close = unfinished(manager, "b-01", "aguarda_pesquisador", "aguarda_pesquisador", updated=20)
    before = (keep.status, dict(keep.payload), keep.updated_at)
    repl, launched, out, *_ = make_repl(tmp_path, inputs=["m", "e"], manager=manager)
    repl._last_end = None
    with patch("src.llm.session.build_session_routing", side_effect=AssertionError("sem chamada a LLM")):
        await repl.review_unfinished()
    repl.close()
    assert (keep.status, keep.payload, keep.updated_at) == before
    assert close.status == "closed" and close.payload["motivo_parada"] == "encerrada_pesquisador"
    assert (tmp_path / "outputs" / "b-01" / "relatorio_encerramento.md").exists()
    assert launched == []


@pytest.mark.asyncio
async def test_varredura_ao_abrir_marca_a_sessao_parada_e_a_pergunta_aparece(tmp_path):
    manager = FakeSessionManager()
    sess = manager.add("c-01", "active", {"mode": "auto"})
    sess.alias, sess.pid, sess.host = "c-01", 999, "outro-host"
    sess.updated_at = FakeClock().iso(-10_000)
    repl, _, out, *_ = make_repl(tmp_path, inputs=["m"], manager=manager)
    repl._last_end = None
    recovered = []
    repl._recover = recovered.append
    await repl.review_unfinished()
    repl.close()
    assert sess.status == "interrompida" and recovered and "parou sem fechar" in out.text


# -- um REPL por vez (caso 6) e ausência de cargas pesadas (5.3) ---------------------------------------------------


def test_segundo_repl_e_recusado_com_codigo_1(tmp_path):
    repl, _, out, store, _ = make_repl(tmp_path)
    assert repl.open() is None
    second = Repl(
        mode="auto", explicit_mode=None, budget=BUDGET, args=args(), starter=MagicMock(), manager=MagicMock(),
        presence=TerminalPresence("repl", store=store, pid=7, pid_alive=lambda pid: True), input_fn=lambda _p: "",
        console=out,
    )
    assert second.open() == EXIT_ERROR and "já há um terminal" in out.text
    repl.close()


def test_abrir_e_sair_do_repl_nao_carrega_embeddings_nem_clientes():
    code = (
        "import sys, asyncio, tempfile, pathlib\n"
        "from types import SimpleNamespace\n"
        "from src.cli.repl import Console, Repl\n"
        "from src.session.presence import TerminalPresence\n"
        "from tests.support.session_fakes import FakeSessionManager, InMemoryPresenceStore\n"
        "from tests.support.starter_world import BUDGET, args, make_starter\n"
        "class NoGate:\n"
        "    def pending(self, *a, **k): return []\n"
        "manager = FakeSessionManager()\n"
        "starter, _ = make_starter(pathlib.Path(tempfile.mkdtemp()), manager=manager)\n"
        "lines = iter(['sair'])\n"
        "repl = Repl(mode='auto', explicit_mode=None, budget=BUDGET, args=args(), starter=starter, manager=manager,\n"
        "            presence=TerminalPresence('repl', store=InMemoryPresenceStore(), pid_alive=lambda pid: True),\n"
        "            input_fn=lambda p: next(lines, 'sair'), console=Console(), sweep_interval=3600,\n"
        "            recover=lambda s: None, gate=NoGate(), reminder_interval=3600)\n"
        "assert repl.open() is None\n"
        "asyncio.run(repl.review_unfinished()); asyncio.run(repl.loop()); repl.close()\n"
        "heavy = [m for m in ('fastembed', 'qdrant_client', 'onnxruntime', 'google.genai', 'anthropic', 'openai')"
        " if m in sys.modules]\n"
        "print('HEAVY', heavy)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True, text=True, check=True,
    )
    assert "HEAVY []" in result.stdout


# -- comando direto (5.2 e códigos de saída) -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_com_assisted_e_recusado(capsys):
    code = await direct.start_research("t", args(), mode="assisted", budget=BUDGET, background=True)
    assert code == EXIT_ERROR and "assisted" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_background_imprime_apelido_e_pid_e_sai_com_0_sem_presenca(tmp_path, capsys):
    starter, launched = make_starter(tmp_path)
    starter.wait_registered = AsyncMock(return_value=SimpleNamespace(alias="iris-02", pid=555, id="s"))
    created = []
    with patched_terminal(), patch.object(direct, "sweep_stopped"):
        code = await direct.start_research(
            "t", args(), mode="auto", budget=BUDGET, background=True, starter=starter,
            presence_factory=lambda: created.append(1),
        )
    out = capsys.readouterr().out
    assert code == 0 and created == [] and len(launched) == 1
    assert "iris-02" in out and "555" in out


@pytest.mark.asyncio
async def test_primeiro_plano_registra_presenca_direto_espera_e_devolve_o_codigo(tmp_path):
    starter, launched = make_starter(tmp_path)
    clock, store = FakeClock(), InMemoryPresenceStore()
    proc = MagicMock(wait=MagicMock(return_value=3))
    starter._spawn = lambda *a, **k: proc
    with patched_terminal(), patch.object(direct, "sweep_stopped"):
        code = await direct.start_research(
            "t", args(), mode="auto", budget=BUDGET, background=False, starter=starter,
            presence_factory=lambda: TerminalPresence("direto", store=store, clock=clock.now),
        )
    assert code == 3
    row = next(iter(store.rows.values()))
    assert row.tipo == "direto" and row.end_reason == "saida"


@pytest.mark.asyncio
async def test_recusa_antes_do_processo_devolve_o_codigo_da_recusa(tmp_path, capsys):
    starter, launched = make_starter(tmp_path, available_mb=1)
    store = InMemoryPresenceStore()
    with patched_terminal(), patch.object(direct, "sweep_stopped"), patch("src.config.MIN_AVAILABLE_MEMORY_MB", 512):
        code = await direct.start_research(
            "t", args(), mode="auto", budget=BUDGET, background=False, starter=starter,
            presence_factory=lambda: TerminalPresence("direto", store=store),
        )
    assert code == EXIT_LOW_MEMORY and launched == []
    assert next(iter(store.rows.values())).ended_at is not None  # a presença não fica aberta


def test_codigo_de_saida_do_processo_morto_por_sinal():
    assert exit_code_of(0) == 0 and exit_code_of(3) == 3 and exit_code_of(-9) == 137 and exit_code_of(-2) == 130


def test_ctrl_c_no_comando_direto_e_repassado_ao_processo_da_sessao():
    child = (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGINT, lambda *a: sys.exit(130))\n"
        "print('pronto', flush=True)\n"
        "time.sleep(30)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", child], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "pronto"
    previous = signal.getsignal(signal.SIGINT)
    threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGINT)).start()
    start = time.monotonic()
    assert wait_foreground(proc) == 130
    assert time.monotonic() - start < 10
    assert signal.getsignal(signal.SIGINT) == previous  # o repasse é desfeito ao fim


def test_sessao_que_o_wait_encontra_so_com_pid_registrado(tmp_path):
    starter, _ = make_starter(tmp_path)
    started = SimpleNamespace(spec=SimpleNamespace(launch_id="l1"), proc=MagicMock(poll=MagicMock(return_value=1)),
                              path=tmp_path / "x.json")
    with pytest.raises(LaunchRefused, match="código 1"):
        asyncio.run(starter.wait_registered(started))
