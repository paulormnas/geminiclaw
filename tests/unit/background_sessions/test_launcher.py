"""Lançamento do processo da sessão (v18.7-background-sessions, tarefas 3.1 e 3.5)."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.session.launcher as launcher
from src.session.launcher import (
    LaunchError,
    LaunchSpec,
    check_memory,
    context_digest,
    filtered_env,
    read_launch_file,
    spawn_session,
    summarize_task,
    wait_registered,
    write_launch_file,
)
from src.session.manager import Session
from tests.support.fake_clock import FakeClock

pytestmark = pytest.mark.unit


def make_spec(**over) -> LaunchSpec:
    base = dict(
        tipo="nova",
        prompt="tarefa de teste com acentuação",
        modo="auto",
        orcamento={"max_tokens": 1000},
        contexto={"dir": "input_context", "digest": "abc"},
        primeiro_plano=False,
    )
    base.update(over)
    return LaunchSpec(**base)


def session(pid: int | None = 1, sid: str = "s1") -> Session:
    return Session(id=sid, agent_id="orchestrator", status="active", created_at="", updated_at="", payload={}, pid=pid)


# -- validação do arquivo de lançamento (dado não confiável) -------------------------------------------------------


def test_lancamento_valido_faz_ida_e_volta():
    spec = make_spec(terminal_id=str(uuid.uuid4()), ilimitado={"origem": "cli", "confirmado_em": "2026-10-16"})
    assert LaunchSpec.from_dict(json.loads(spec.to_json())) == spec


@pytest.mark.parametrize(
    "mudanca",
    [
        {"versao_lancamento": 2},
        {"launch_id": "../../etc/passwd"},
        {"modo": "livre"},
        {"tipo": "outra"},
        {"prompt": "x" * 200_001},
        {"prompt": 7},
        {"orcamento": []},
        {"contexto": {"dir": "x"}},
        {"terminal_id": "nao-uuid"},
        {"ilimitado": {"origem": "cli"}},
        {"tipo": "retomada", "retomada": {"session_id": "../x"}},
        {"tipo": "retomada", "retomada": None},
    ],
)
def test_lancamento_invalido_e_recusado(mudanca):
    data = json.loads(make_spec().to_json()) | mudanca
    with pytest.raises(LaunchError):
        LaunchSpec.from_dict(data)


def test_lancamento_que_nao_e_objeto_e_recusado():
    with pytest.raises(LaunchError):
        LaunchSpec.from_dict(["x"])


def test_arquivo_0600_diretorio_0700_e_apagado_na_leitura(tmp_path: Path):
    spec = make_spec()
    path = write_launch_file(spec, tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert read_launch_file(path) == spec
    assert not path.exists()


def test_escrita_recusa_sobrescrever_e_launch_id_invalido(tmp_path: Path):
    spec = make_spec()
    write_launch_file(spec, tmp_path)
    with pytest.raises(FileExistsError):
        write_launch_file(spec, tmp_path)
    with pytest.raises(LaunchError):
        write_launch_file(make_spec(launch_id="../fora"), tmp_path)


def test_leitura_recusa_link_simbolico(tmp_path: Path):
    real = write_launch_file(make_spec(), tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(LaunchError, match="regular"):
        read_launch_file(link)


def test_leitura_recusa_dono_diferente(tmp_path: Path):
    path = write_launch_file(make_spec(), tmp_path)
    with patch("src.session.launcher.os.getuid", return_value=os.getuid() + 1):
        with pytest.raises(LaunchError, match="dono"):
            read_launch_file(path)


def test_leitura_de_json_corrompido_apaga_e_recusa(tmp_path: Path):
    path = tmp_path / f"{uuid.uuid4()}.json"
    path.write_text("{não é json", encoding="utf-8")
    with pytest.raises(LaunchError):
        read_launch_file(path)
    assert not path.exists()


# -- digest do contexto, resumo e ambiente -------------------------------------------------------------------------


def test_digest_do_contexto_muda_com_conteudo_e_nome(tmp_path: Path):
    ctx = tmp_path / "input_context"
    assert context_digest(ctx) == context_digest(tmp_path / "inexistente")
    ctx.mkdir()
    (ctx / "a.txt").write_text("um")
    first = context_digest(ctx)
    (ctx / "a.txt").write_text("dois")
    second = context_digest(ctx)
    (ctx / "a.txt").rename(ctx / "b.txt")
    assert len({first, second, context_digest(ctx)}) == 3


def test_resumo_da_tarefa_sem_llm():
    assert summarize_task("  uma   tarefa\n curta ") == "uma tarefa curta"
    resumo = summarize_task("palavra " * 100, limit=40)
    assert len(resumo) == 40 and resumo.endswith("…")


def test_ambiente_filtrado_retira_negados_e_marca_o_processo():
    env = filtered_env(
        {"PATH": "/bin", "SEGREDO": "x", "OUTRO": "y", "SESSION_ENV_DENYLIST": "SEGREDO, OUTRO"},
        denylist=["EXTRA"],
    )
    assert "SEGREDO" not in env and "OUTRO" not in env
    assert env["PATH"] == "/bin"
    assert env["SESSION_ENV_DENYLIST"] == "SEGREDO, OUTRO"  # o processo relê o .env e refaz o filtro
    assert env["GEMINICLAW_SESSION_PROCESS"] == "1"
    assert filtered_env({"EXTRA": "z"}, denylist=["EXTRA"]).get("EXTRA") is None


def test_nome_negado_no_dotenv_nao_chega_ao_processo(tmp_path: Path):
    """Simula a releitura do ``.env``: ``load_dotenv`` reintroduz o nome; o filtro pós-carga o retira."""
    code = (
        "import os, dotenv\n"
        "dotenv.load_dotenv = lambda *a, **k: os.environ.setdefault('SEGREDO_TESTE', 'abc')\n"
        "import src.config\n"
        "print('SEGREDO_TESTE' in os.environ)\n"
    )
    root = Path(__file__).resolve().parents[3]
    run = lambda marker: subprocess.run(  # noqa: E731
        ["python", "-c", code],
        cwd=root,
        env={**filtered_env(os.environ), "SESSION_ENV_DENYLIST": "SEGREDO_TESTE"} if marker else os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert run(marker=True) == "False"
    assert run(marker=False) == "True"  # fora do processo da sessão o .env vale normalmente


# -- verificação de memória (casos 14 e 15) ------------------------------------------------------------------------


def monitor(available_mb):
    return SimpleNamespace(get_memory_usage=lambda: None if available_mb is None else {"available_mb": available_mb})


def test_memoria_abaixo_do_minimo_cita_os_valores():
    check = check_memory(monitor(300), [session(sid="iris-01")], minimum_mb=512)
    assert not check.ok and not check.unknown
    assert "300" in check.message() and "MIN_AVAILABLE_MEMORY_MB" in check.message()
    assert [s.id for s in check.running] == ["iris-01"]


def test_memoria_suficiente_e_desconhecida():
    assert check_memory(monitor(512), minimum_mb=512).ok
    unknown = check_memory(monitor(None), minimum_mb=512)
    assert unknown.unknown and not unknown.ok and "desconhecida" in unknown.message()


# -- criação do processo ------------------------------------------------------------------------------------------


def test_spawn_em_segundo_plano_so_leva_o_caminho_e_grava_log_0600(tmp_path: Path):
    launch = tmp_path / f"{uuid.uuid4()}.json"
    launch.write_text("{}")
    with patch.object(launcher.subprocess, "Popen") as popen:
        spawn_session(launch, foreground=False, log_dir=tmp_path / "logs", module="outro.modulo")
    args = popen.call_args.args[0]
    assert args[1:] == ["-m", "outro.modulo", "--launch", str(launch)]  # nada do prompt na linha de comando
    kwargs = popen.call_args.kwargs
    assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["start_new_session"] is True
    assert kwargs["env"]["GEMINICLAW_SESSION_PROCESS"] == "1"
    log = tmp_path / "logs" / f"{launch.stem}.log"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600 and stat.S_IMODE(log.parent.stat().st_mode) == 0o700


def test_spawn_em_primeiro_plano_herda_saida_e_grupo(tmp_path: Path):
    with patch.object(launcher.subprocess, "Popen") as popen:
        spawn_session(tmp_path / "x.json", foreground=True)
    kwargs = popen.call_args.kwargs
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert "start_new_session" not in kwargs and "stdout" not in kwargs


# -- espera pelo registro ------------------------------------------------------------------------------------------


class FakeManager:
    def __init__(self, sessions):
        self.sessions = list(sessions)
        self.calls = 0

    def find_by_launch_id(self, launch_id):
        self.calls += 1
        return self.sessions.pop(0) if self.sessions else None


def test_espera_devolve_a_sessao_com_pid():
    manager = FakeManager([None, session(pid=None), session(pid=42)])
    proc = MagicMock(poll=MagicMock(return_value=None))
    found = asyncio.run(wait_registered("l1", proc, 5, session_manager=manager, poll_seconds=0))
    assert found.pid == 42 and manager.calls == 3


def test_espera_falha_se_o_processo_termina_antes_de_registrar():
    proc = MagicMock(poll=MagicMock(return_value=1))
    with pytest.raises(LaunchError, match="código 1") as info:
        asyncio.run(
            wait_registered(
                "l1", proc, 5, session_manager=FakeManager([]), poll_seconds=0, on_failure_detail=lambda: "fim do log"
            )
        )
    assert "fim do log" in str(info.value)


def test_espera_falha_no_prazo():
    clock = FakeClock()

    async def run():
        proc = MagicMock(poll=MagicMock(return_value=None))
        manager = FakeManager([])

        async def tick(*_a, **_k):
            clock.advance(2)

        with patch("src.session.launcher.asyncio.sleep", tick):
            await wait_registered("l1", proc, 5, session_manager=manager, clock=clock.monotonic)

    with pytest.raises(LaunchError, match="SESSION_LAUNCH_TIMEOUT_SECONDS"):
        asyncio.run(run())


# -- validação da configuração ------------------------------------------------------------------------------------


def _import_config(**env) -> subprocess.CompletedProcess:
    root = Path(__file__).resolve().parents[3]
    return subprocess.run(
        ["python", "-c", "import src.config"], cwd=root, env={**os.environ, **env}, capture_output=True, text=True
    )


def test_presenca_com_prazo_menor_que_o_dobro_do_batimento_falha_na_partida():
    result = _import_config(TERMINAL_PRESENCE_HEARTBEAT_SECONDS="10", TERMINAL_PRESENCE_STALE_SECONDS="20")
    assert result.returncode != 0 and "TERMINAL_PRESENCE_STALE_SECONDS" in result.stderr


def test_laco_com_prazo_menor_que_o_tique_falha_na_partida():
    result = _import_config(SESSION_LOOP_TICK_SECONDS="10", SESSION_LOOP_STALE_SECONDS="10")
    assert result.returncode != 0 and "SESSION_LOOP_STALE_SECONDS" in result.stderr


def test_padroes_da_configuracao_de_sessao():
    result = subprocess.run(
        ["python", "-c", "import src.config as c; print(c.SESSION_LAUNCH_TIMEOUT_SECONDS, c.SESSION_LOOP_TICK_SECONDS,"
         " c.SESSION_LOOP_STALE_SECONDS, c.TERMINAL_PRESENCE_HEARTBEAT_SECONDS, c.TERMINAL_PRESENCE_STALE_SECONDS,"
         " c.SESSION_PRESENCE_CHECK_SECONDS, c.TERMINAL_STALE_CHECK_SECONDS, c.SESSION_LOST_EXIT_GRACE_SECONDS,"
         " c.SESSION_LOG_DIR, c.SESSION_ENV_DENYLIST)"],
        cwd=Path(__file__).resolve().parents[3],
        env={k: v for k, v in os.environ.items() if not k.startswith(("SESSION_", "TERMINAL_"))},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "60.0 10.0 900.0 10.0 60.0 15.0 60.0 30.0 logs/sessions ()"
