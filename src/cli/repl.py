"""Laço do REPL (v18.7-background-sessions, design §1.1, §1.6 e §1.7).

O REPL só lança, acompanha e decide: cada pesquisa roda em processo próprio (``nova-pesquisa <tarefa>``) e o prompt
volta sem esperar o fim dela. Ao abrir, registra a presença do terminal (um REPL por vez), marca as sessões paradas,
mostra o resumo desde a última vez e pergunta o que fazer com cada pesquisa não finalizada. Não carrega embeddings,
cliente do Qdrant nem clientes de LLM ao abrir: só os comandos que os usam (ADR 023 §7).
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from src import config
from src.cli.context_commands import clear_context
from src.cli.sandboxes import show_sandboxes, stop_sandboxes
from src.cli.session_start import LaunchRefused, SessionStarter, Started
from src.cli.sessions_view import (
    ANSWER_CLOSE,
    ANSWER_RESUME,
    ask_unfinished,
    label,
    resolve_target,
    show_researches,
    summary_since,
)
from src.logger import get_logger
from src.session.exit_codes import EXIT_ERROR
from src.session.manager import SessionManager
from src.session.presence import PgPresenceStore, TerminalAlreadyOpenError, TerminalPresence
from src.session.states import UNFINISHED_STATUSES
from src.session.watch import SessionWatch
from src.utils.terminal import BANNER, DIM, MAGENTA, RED, RESET, STATUS_ICONS, YELLOW

logger = get_logger(__name__)

EXIT_COMMANDS = {"exit", "quit", "sair"}
PROMPT = f"  {MAGENTA}🔮 >{RESET} "
NEW_RESEARCH_HINT = (
    "Para iniciar uma pesquisa use: nova-pesquisa <tarefa>  (comandos: sessions, retomar, encerrar, sair)"
)


class Console:
    """Saída do REPL com notificações de outras threads que redesenham o prompt e o que já foi digitado."""

    def __init__(self, stream: Any | None = None) -> None:
        self._stream = stream or sys.stdout
        self._lock = threading.Lock()
        self.waiting_for_input = False

    def write(self, text: str) -> None:
        with self._lock:
            print(text, file=self._stream, flush=True)

    def notify(self, text: str) -> None:
        """Mensagem assíncrona: apaga a linha do prompt, escreve e redesenha o prompt com o texto parcial."""
        with self._lock:
            if self.waiting_for_input:
                self._stream.write("\r\033[K")
            print(f"\n  {text}", file=self._stream, flush=True)
            if self.waiting_for_input:
                partial = ""
                try:
                    import readline

                    partial = readline.get_line_buffer()
                except Exception:  # noqa: BLE001 - sem readline o prompt volta sem o texto parcial
                    pass
                self._stream.write(PROMPT + partial)
                self._stream.flush()


class SweepThread:
    """Varredura periódica de sessões paradas enquanto o REPL está aberto (``TERMINAL_STALE_CHECK_SECONDS``)."""

    def __init__(self, watch: SessionWatch, console: Console, interval: float) -> None:
        self._watch = watch
        self._console = console
        self._interval = max(interval, 0.05)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="geminiclaw-sweep", daemon=True)

    def start(self) -> "SweepThread":
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            for session in self._watch.sweep():
                self._console.notify(
                    f"{YELLOW}{STATUS_ICONS['warning']} A pesquisa {label(session)} parou sem fechar "
                    f"(o processo não responde). Use 'retomar {label(session)}' ou 'encerrar {label(session)}'.{RESET}"
                )

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def make_recover(manager: SessionManager) -> Callable[[Any], None]:
    """Recuperação de uma sessão parada: o orquestrador só é criado quando há o que recuperar."""
    holder: dict[str, Any] = {}

    def recover(session: Any) -> None:
        if "orchestrator" not in holder:
            from src.orchestration.orchestrator import Orchestrator

            holder["orchestrator"] = Orchestrator(session_manager=manager)
        holder["orchestrator"].recover_stopped_session(session)

    return recover


class Repl:
    """Estado e comandos do REPL. Entrada, saída e relógio são injetáveis (testes com entrada simulada)."""

    def __init__(
        self,
        *,
        mode: str | None,
        explicit_mode: str | None,
        budget: Any,
        args: argparse.Namespace,
        starter: SessionStarter | None = None,
        manager: SessionManager | None = None,
        presence: TerminalPresence | None = None,
        input_fn: Callable[[str], str] | None = None,
        console: Console | None = None,
        now: Callable[[], float] = time.time,
        sweep_interval: float | None = None,
        recover: Callable[[Any], None] | None = None,
    ) -> None:
        self.mode = mode or config.SESSION_DEFAULT_MODE
        self.explicit_mode = explicit_mode
        self.budget = budget
        self.args = args
        self.manager = manager or SessionManager()
        self.console = console or Console()
        self._input = input_fn or input
        self.starter = starter or SessionStarter(
            session_manager=self.manager, input_fn=self._input, output_fn=self.console.write
        )
        self.presence = presence or TerminalPresence("repl", store=PgPresenceStore())
        self._now = now
        self._sweep_interval = config.TERMINAL_STALE_CHECK_SECONDS if sweep_interval is None else sweep_interval
        self._recover = recover if recover is not None else make_recover(self.manager)
        self._sweep: SweepThread | None = None

    # -- abertura e fechamento -------------------------------------------------------------------------------------

    def open(self) -> int | None:
        """Registra a presença e prepara o terminal. Devolve um código de saída se o REPL não pôde abrir."""
        try:
            last_end = self.presence.last_repl_end()
            self.presence.start()
        except TerminalAlreadyOpenError as exc:
            self.console.write(f"\n  {STATUS_ICONS['error']} {RED}{exc}{RESET}\n")
            return EXIT_ERROR
        self.presence.start_heartbeat()
        self._last_end = last_end
        return None

    def close(self) -> None:
        if self._sweep is not None:
            self._sweep.stop()
        self.presence.stop()

    # -- pesquisas não finalizadas ---------------------------------------------------------------------------------

    async def review_unfinished(self) -> None:
        """Marca as sessões paradas, mostra o resumo desde a última vez e pergunta o destino de cada pesquisa."""
        watch = SessionWatch(self.manager, recover=self._recover, clock=self._now)
        marked = watch.sweep()
        for s in marked:
            self.console.write(
                f"  {YELLOW}{STATUS_ICONS['warning']} {label(s)} parou sem fechar (processo ausente).{RESET}"
            )
        unfinished = summary_since(self.manager, self._last_end, self.console.write)
        for session in unfinished:
            answer = ask_unfinished(
                session, self.starter.base_dir, self._input, self.console.write, self._now()
            )
            if answer == ANSWER_RESUME:
                await self.resume(session)
            elif answer == ANSWER_CLOSE:
                self.close_research(session)
        self._sweep = SweepThread(
            SessionWatch(self.manager, recover=self._recover, clock=self._now), self.console, self._sweep_interval
        ).start()

    def close_research(self, session: Any) -> None:
        from src.session.closing import close_by_researcher

        report = close_by_researcher(self.manager, self.starter.base_dir, session)
        if report is None:
            self.console.write(f"  {DIM}{label(session)} já não está parada; nada foi alterado.{RESET}")
        else:
            self.console.write(f"  Pesquisa {label(session)} encerrada. Relatório: {report}")

    # -- comandos --------------------------------------------------------------------------------------------------

    async def start_research(self, task: str) -> None:
        from src.cli.session_start import MEMORY_POLICY_ASK

        try:
            started = await self.starter.start_new(
                task,
                mode=self.mode,
                budget=self.budget,
                args=self.args,
                terminal_id=self.presence.terminal_id,
                foreground=False,
                memory_policy=MEMORY_POLICY_ASK,
            )
            await self._announce(started)
        except LaunchRefused as refusal:
            self.console.write(f"\n  {STATUS_ICONS['error']} {RED}{refusal}{RESET}\n")

    async def resume(self, session: Any) -> None:
        from src.cli.session_start import MEMORY_POLICY_ASK

        try:
            started = await self.starter.start_resume(
                session.id,
                mode=self.explicit_mode,
                budget=self.budget,
                args=self.args,
                terminal_id=self.presence.terminal_id,
                foreground=False,
                memory_policy=MEMORY_POLICY_ASK,
            )
            await self._announce(started)
        except LaunchRefused as refusal:
            self.console.write(f"\n  {STATUS_ICONS['error']} {RED}{refusal}{RESET}\n")

    async def _announce(self, started: Started) -> None:
        session = await self.starter.wait_registered(started)
        self.console.write(
            f"\n  Pesquisa {label(session)} iniciada em segundo plano (PID {session.pid}). "
            f"Acompanhe com 'sessions'.\n"
        )

    def confirm_stop_all_sandboxes(self) -> bool:
        try:
            answer = self._input(
                "  Encerrar os containers de sandbox de TODAS as pesquisas? [s/N] "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("s", "sim", "y", "yes")

    async def handle(self, line: str) -> bool:
        """Trata uma linha. Devolve ``False`` para sair do REPL."""
        text = line.strip()
        if not text:
            return True
        lower = text.lower()
        word, _, rest = text.partition(" ")
        word = word.lower()
        rest = rest.strip()
        if lower in EXIT_COMMANDS:
            return False
        if word == "nova-pesquisa":
            if not rest:
                self.console.write(f"\n  {RED}Use: nova-pesquisa <tarefa>{RESET}\n")
            else:
                await self.start_research(rest)
        elif lower == "sessions":
            show_researches(self.manager, self.console.write, self._now())
        elif word in ("retomar", "resume"):
            await self._cmd_resume(rest)
        elif word == "encerrar":
            self._cmd_close(rest)
        elif lower == "sandboxes":
            show_sandboxes()
        elif word == "parar-sandboxes":
            if rest:
                stop_sandboxes(session_id=rest.split()[0])
            elif self.confirm_stop_all_sandboxes():
                from src.skills.code.sandbox import cleanup_all_sandbox_containers

                stop_sandboxes(session_id=None)
                cleanup_all_sandbox_containers()
        elif lower == "clear-context":
            clear_context()
        else:
            self.console.write(f"\n  {YELLOW}{NEW_RESEARCH_HINT}{RESET}\n")
        return True

    async def _cmd_resume(self, target: str) -> None:
        session = resolve_target(self.manager, target)
        if session is None:
            self.console.write(f"\n  {RED}Use: retomar <apelido|id> (pesquisa não encontrada: '{target}'){RESET}\n")
            return
        await self.resume(session)

    def _cmd_close(self, target: str) -> None:
        session = resolve_target(self.manager, target)
        if session is None or session.status not in UNFINISHED_STATUSES:
            self.console.write(f"\n  {RED}Use: encerrar <apelido|id> de uma pesquisa parada ('{target}'){RESET}\n")
            return
        self.close_research(session)

    # -- laço ------------------------------------------------------------------------------------------------------

    async def loop(self) -> None:
        while True:
            self.console.waiting_for_input = True
            try:
                line = self._input(PROMPT)
            except (EOFError, KeyboardInterrupt):
                self.console.waiting_for_input = False
                self.console.write(f"\n\n  {DIM}Encerrando...{RESET}")
                return
            self.console.waiting_for_input = False
            if not await self.handle(line):
                self.console.write(f"\n  {DIM}Até logo! 👋{RESET}\n")
                return


async def interactive_mode(
    *,
    mode: str | None = None,
    explicit_mode: str | None = None,
    budget: Any = None,
    args: argparse.Namespace | None = None,
    **kwargs: Any,
) -> int:
    """Executa o REPL e devolve o código de saída (1 se já há um REPL aberto)."""
    repl = Repl(
        mode=mode, explicit_mode=explicit_mode, budget=budget, args=args or argparse.Namespace(), **kwargs
    )
    print(BANNER)
    print(f"  {DIM}Modo interativo. 'nova-pesquisa <tarefa>' inicia uma pesquisa em segundo plano.{RESET}")
    print(f"  {DIM}'sessions' lista as pesquisas; 'sair' encerra o terminal (as pesquisas continuam).{RESET}\n")
    code = repl.open()
    if code is not None:
        return code
    try:
        await repl.review_unfinished()
        await repl.loop()
    finally:
        repl.close()
    return 0
