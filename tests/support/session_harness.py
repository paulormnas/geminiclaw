"""Harness do processo da sessão nos testes de integração (v18.7-background-sessions, tarefa 3.4).

Lança o processo real (``tests.support.session_process_recorded``) com arquivo de lançamento de teste, espera o PID
registrado na sessão, envia sinais e, no teardown, encerra o grupo de processos inteiro (``os.killpg``) e confere que
nada sobrou. Os tempos são os valores reduzidos da spec ``session-continuity`` (nenhum teste espera 30 s ou 60 s).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from src.orchestration.usage import UsageBudget
from src.session.launcher import LaunchSpec, context_digest, spawn_session, write_launch_file
from src.session.manager import Session, SessionManager

ROOT = Path(__file__).resolve().parents[2]
RECORDED_MODULE = "tests.support.session_process_recorded"
REDUCED_ENV = {
    "SESSION_LAUNCH_TIMEOUT_SECONDS": "10",
    "SESSION_HEARTBEAT_SECONDS": "1",
    "SESSION_STALE_SECONDS": "3",
    "SESSION_LOOP_TICK_SECONDS": "1",
    "SESSION_LOOP_STALE_SECONDS": "4",
    "TERMINAL_PRESENCE_HEARTBEAT_SECONDS": "1",
    "TERMINAL_PRESENCE_STALE_SECONDS": "3",
    "SESSION_PRESENCE_CHECK_SECONDS": "1",
    "TERMINAL_STALE_CHECK_SECONDS": "1",
    "SESSION_LOST_EXIT_GRACE_SECONDS": "2",
    "LIMIT_GRACE_SECONDS": "2",
    "LOCALITY_MIN_GROUP_SIZE": "3",
}
DEFAULT_BUDGET = UsageBudget(100_000, 60.0, 3, 3, 0.05, 1_000_000)


@dataclass
class Launched:
    proc: subprocess.Popen[bytes]
    spec: LaunchSpec | None
    path: Path

    @property
    def log(self) -> Path:
        return Path(self.path.parents[2]) / "logs" / f"{self.path.stem}.log"


class SessionHarness:
    """Lança processos de sessão em ``tmp_path`` (cwd, ``outputs/``, ``logs/``) contra o banco de teste."""

    def __init__(self, tmp_path: Path, database_url: str, extra_env: dict[str, str] | None = None) -> None:
        self.root = tmp_path
        self.context_dir = tmp_path / "input_context"
        self.context_dir.mkdir()
        self.env = {
            **os.environ,
            **REDUCED_ENV,
            "DATABASE_URL": database_url,
            "PYTHONPATH": str(ROOT),
            "OUTPUT_BASE_DIR": str(tmp_path / "outputs"),
            **(extra_env or {}),
        }
        self.manager = SessionManager()
        self.launched: list[Launched] = []

    def starter(self, **kwargs: Any) -> Any:
        """``SessionStarter`` real que cria o processo de teste (``GC_SCENARIO`` é lido de ``self.env`` a cada lançamento).

        Tudo o que é do terminal e não do processo (infraestrutura, roteamento e vínculo de projeto) fica a cargo do
        teste; a memória é a do computador.
        """
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from src.cli.session_start import SessionStarter

        binder = MagicMock()
        binder.bind = AsyncMock(return_value=SimpleNamespace(mode="sem_grafo", project_id=None, context_block=""))
        defaults: dict[str, Any] = dict(
            session_manager=self.manager,
            base_dir=self.root / "outputs",
            context_dir=str(self.context_dir),
            monitor=SimpleNamespace(get_memory_usage=lambda: {"available_mb": 10**6}),
            spawn=self._tracked_spawn,
            spawn_module=RECORDED_MODULE,
            spawn_env=self.env,
            spawn_cwd=self.root,
            log_dir=self.root / "logs",
            launch_timeout=10,
            binder_factory=lambda _routing, _args: binder,
            prerequisites=lambda: None,
            output_fn=lambda _t: None,
        )
        defaults.update(kwargs)
        return SessionStarter(**defaults)

    def _tracked_spawn(self, path: Path, **kwargs: Any) -> subprocess.Popen[bytes]:
        proc = spawn_session(path, **kwargs)
        self.launched.append(Launched(proc, None, path))
        return proc

    def use_scenario(self, scenario: Path) -> None:
        self.env["GC_SCENARIO"] = str(scenario)

    def scenario(self, *, motivo: str = "solucao_encontrada", passos: list[dict[str, Any]] | None = None) -> Path:
        path = self.root / f"cenario-{uuid.uuid4().hex[:6]}.json"
        path.write_text(json.dumps({"motivo": motivo, "passos": passos or []}), encoding="utf-8")
        return path

    def spec(self, prompt: str = "tarefa de teste", *, modo: str = "auto", digest: str | None = None,
             **over: Any) -> LaunchSpec:
        base: dict[str, Any] = dict(
            tipo="nova",
            prompt=prompt,
            modo=modo,
            orcamento={**DEFAULT_BUDGET.__dict__},
            contexto={"dir": str(self.context_dir), "digest": digest or context_digest(self.context_dir)},
            primeiro_plano=False,
            project_mode="sem_grafo",
        )
        base.update(over)
        return LaunchSpec(**base)

    def launch(self, spec: LaunchSpec | None = None, *, scenario: Path | None = None, foreground: bool = False) -> Launched:
        spec = spec or self.spec()
        path = write_launch_file(spec, self.root / "outputs")
        env = dict(self.env)
        env["GC_SCENARIO"] = str(scenario or self.scenario())
        proc = spawn_session(
            path, foreground=foreground, log_dir=self.root / "logs", module=RECORDED_MODULE, env=env, cwd=self.root
        )
        launched = Launched(proc, spec, path)
        self.launched.append(launched)
        return launched

    def wait_registered(self, launched: Launched, timeout: float = 10) -> Session:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            session = self.manager.find_by_launch_id(launched.spec.launch_id)
            if session is not None and session.pid is not None:
                return session
            if launched.proc.poll() is not None:
                break
            time.sleep(0.1)
        raise AssertionError(f"sessão não registrada; saída={launched.proc.poll()}; log={self.tail(launched)}")

    def wait_exit(self, launched: Launched, timeout: float = 10) -> int:
        try:
            return launched.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"o processo não terminou em {timeout} s; log={self.tail(launched)}") from None

    def tail(self, launched: Launched) -> str:
        try:
            return launched.log.read_text(encoding="utf-8", errors="replace")[-1500:]
        except OSError:
            return ""

    def send(self, launched: Launched, sig: int) -> None:
        os.kill(launched.proc.pid, sig)

    def wait_status(self, session_id: str, statuses: tuple[str, ...], timeout: float = 10) -> Session:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            session = self.manager.get(session_id)
            if session is not None and session.status in statuses:
                return session
            time.sleep(0.1)
        raise AssertionError(f"sessão {session_id} não chegou a {statuses}: {self.manager.get(session_id)}")

    def teardown(self) -> None:
        """Encerra o grupo de processos de cada lançamento e confere que nada sobrou."""
        survivors: list[int] = []
        for launched in self.launched:
            pid = launched.proc.pid
            if launched.proc.poll() is None:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                launched.proc.wait(timeout=5)
            if psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
                survivors.append(pid)
        assert survivors == [], f"processos de sessão sobreviveram ao teardown: {survivors}"


def python_executable() -> str:
    return sys.executable
