"""Laço do REPL (v18.7-background-sessions, design §1.1, §1.6 e §1.7).

O REPL só lança, acompanha e decide: cada pesquisa roda em processo próprio (``nova-pesquisa <tarefa>``) e o prompt
volta sem esperar o fim dela. Ao abrir, registra a presença do terminal (um REPL por vez), marca as sessões paradas,
mostra o resumo desde a última vez e pergunta o que fazer com cada pesquisa não finalizada. Não carrega embeddings,
cliente do Qdrant nem clientes de LLM ao abrir: só os comandos que os usam (ADR 023 §7).
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from src import config
from src.cli.context_commands import clear_context
from src.cli.gate_commands import decide, send_message, show_pending
from src.cli.progress_view import EventsThread, send_command, show_history, show_overview
from src.cli.sandboxes import show_sandboxes, stop_sandboxes
from src.cli.session_start import LaunchRefused, SessionStarter, Started
from src.cli.sessions_view import (
    ANSWER_CLOSE,
    ANSWER_RESUME,
    ask_unfinished,
    label,
    resolve_target,
    summary_since,
)
from src.gate.persistent_gate import terminal_gate
from src.logger import get_logger
from src.session.chain import chain_session_ids
from src.session.events import EventReader, purge
from src.session.exit_codes import EXIT_ERROR
from src.session.manager import SessionManager
from src.session.presence import PgPresenceStore, TerminalAlreadyOpenError, TerminalPresence
from src.session.states import UNFINISHED_STATUSES
from src.session.watch import SessionWatch
from src.utils.terminal import BANNER, DIM, MAGENTA, RED, RESET, STATUS_ICONS, YELLOW

try:  # edição de linha no prompt e ``get_line_buffer()`` nas notificações; importar já aqui (numa thread bloquearia)
    import readline
except ImportError:  # pragma: no cover - plataformas sem readline
    readline = None  # type: ignore[assignment]

logger = get_logger(__name__)

EXIT_COMMANDS = {"exit", "quit", "sair"}
PROMPT = f"  {MAGENTA}🔮 >{RESET} "
NEW_RESEARCH_HINT = (
    "Para iniciar uma pesquisa use: nova-pesquisa <tarefa>  "
    "(comandos: pesquisas, acompanhar, pausar, parar, cancelar, replanejar, pendentes, decidir, mensagem, retomar, "
    "encerrar, sair)"
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
                    if readline is not None:
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


class ReminderThread:
    """Lembrete periódico dos pedidos pendentes ao pesquisador (``GATE_REMINDER_SECONDS``)."""

    def __init__(self, gate: Any, manager: Any, console: Console, interval: float) -> None:
        self._gate = gate
        self._manager = manager
        self._console = console
        self._interval = max(interval, 0.05)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="geminiclaw-reminder", daemon=True)

    def start(self) -> "ReminderThread":
        self._thread.start()
        return self

    def remind(self) -> int:
        """Escreve o lembrete se há pedidos pendentes; devolve quantos."""
        from src.cli.gate_commands import aliases_for, format_request

        try:
            pending = self._gate.pending()
        except Exception as exc:  # noqa: BLE001 - o lembrete nunca derruba o terminal
            logger.warning("Lembrete de pedidos falhou", extra={"error": type(exc).__name__})
            return 0
        if not pending:
            return 0
        aliases = aliases_for(self._manager, pending)
        lines = "\n    ".join(format_request(r, aliases.get(r.session_id or '')) for r in pending)
        self._console.notify(
            f"{YELLOW}{STATUS_ICONS['warning']} {len(pending)} pedido(s) aguardam você (use 'decidir <id>'):{RESET}"
            f"\n    {lines}"
        )
        return len(pending)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.remind()

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
        gate: Any | None = None,
        reminder_interval: float | None = None,
        reader: EventReader | None = None,
        events_interval: float | None = None,
        costs_fn: Callable[[Any], dict[str, float]] | None = None,
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
        self.gate = gate if gate is not None else terminal_gate()
        self._reminder_interval = (
            config.GATE_REMINDER_SECONDS if reminder_interval is None else reminder_interval
        )
        self._reminder: ReminderThread | None = None
        self.reader = reader if reader is not None else EventReader()
        self._events_interval = config.SESSION_EVENTS_POLL_SECONDS if events_interval is None else events_interval
        self._events: EventsThread | None = None
        self._costs_fn = costs_fn

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
        try:  # retenção dos eventos (0, o padrão, nunca apaga); falha nunca impede a abertura
            purge(int(config.SESSION_EVENTS_RETENTION_DAYS))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Retenção dos eventos falhou", extra={"error": type(exc).__name__})
        return None

    def close(self) -> None:
        if self._events is not None:
            self._events.stop()
        if self._sweep is not None:
            self._sweep.stop()
        if self._reminder is not None:
            self._reminder.stop()
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
            try:
                pending = self.gate.pending(chain_session_ids(self.manager, session.id))
            except Exception:  # noqa: BLE001 - sem a lista de pedidos a pergunta aparece sem eles
                pending = []
            answer = ask_unfinished(
                session, self.starter.base_dir, self._input, self.console.write, self._now(), pending
            )
            if answer == ANSWER_RESUME:
                await self.resume(session)
            elif answer == ANSWER_CLOSE:
                self.close_research(session)
        self._sweep = SweepThread(
            SessionWatch(self.manager, recover=self._recover, clock=self._now), self.console, self._sweep_interval
        ).start()
        self._reminder = ReminderThread(self.gate, self.manager, self.console, self._reminder_interval)
        self._reminder.remind()  # ao abrir
        self._reminder.start()
        self._start_events()

    def _start_events(self) -> None:
        """Liga a leitura periódica dos eventos de progresso; o REPL só mostra o que acontece depois de abrir."""
        try:
            start_id = self.reader.last_id()
        except Exception as exc:  # noqa: BLE001 - sem a tabela de eventos o REPL abre sem o acompanhamento
            logger.warning("Eventos de progresso indisponíveis", extra={"error": type(exc).__name__})
            return
        self._events = EventsThread(
            self.reader, self.manager, self.console, self._events_interval, start_id=start_id
        ).start()

    def close_research(self, session: Any) -> None:
        from src.session.closing import close_by_researcher

        report = close_by_researcher(self.manager, self.starter.base_dir, session)
        if report is None:
            self.console.write(f"  {DIM}{label(session)} já não está parada; nada foi alterado.{RESET}")
        else:
            self.console.write(f"  Pesquisa {label(session)} encerrada. Relatório: {report}")

    # -- comandos --------------------------------------------------------------------------------------------------

    def _running_researches(self) -> list[Any]:
        """Pesquisas com processo em execução (para a confirmação de ``nova-pesquisa``)."""
        try:
            return [s for s in self.manager.list_orchestrator(["active"]) if s.pid]
        except Exception as exc:  # noqa: BLE001 - sem a lista o comando segue sem a pergunta
            logger.warning("Pesquisas em execução indisponíveis", extra={"error": type(exc).__name__})
            return []

    def confirm_another_research(self, running: list[Any]) -> bool:
        """Com outra pesquisa em execução, pergunta antes da verificação de memória (decisão de 2026-10-15)."""
        names = ", ".join(label(s) for s in running)
        try:
            answer = self._input(f"  Já há pesquisa em execução ({names}). Iniciar outra? [s/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("s", "sim", "y", "yes")

    async def start_research(self, task: str) -> None:
        from src.cli.session_start import MEMORY_POLICY_ASK

        running = self._running_researches()
        if running and not self.confirm_another_research(running):
            self.console.write(f"  {DIM}Nenhuma pesquisa foi iniciada.{RESET}\n")
            return
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
        elif lower in ("sessions", "pesquisas"):
            show_overview(self.manager, self.reader, self.gate, self.console.write, self._now(), self._costs_fn)
        elif word == "acompanhar":
            self._cmd_follow(rest)
        elif word in ("pausar", "parar", "replanejar"):
            send_command(self.manager, rest.split()[0] if rest else "", word, None, self.console.write)
        elif word == "cancelar":
            target, _, subtask = rest.partition(" ")
            if not target or not subtask.strip():
                self.console.write(f"\n  {RED}Use: cancelar <apelido> <subtarefa>{RESET}\n")
            else:
                send_command(self.manager, target, "cancelar", subtask.strip().split()[0], self.console.write)
        elif word in ("retomar", "resume"):
            await self._cmd_resume(rest)
        elif word == "encerrar":
            self._cmd_close(rest)
        elif word == "pendentes":
            show_pending(self.gate, self.manager, self.console.write, rest.split()[0] if rest else None, self._now())
        elif word == "decidir":
            await self._cmd_decide(rest)
        elif word == "mensagem":
            target, _, message = rest.partition(" ")
            if not target or not message.strip():
                self.console.write(f"\n  {RED}Use: mensagem <apelido> <texto>{RESET}\n")
            else:
                send_message(self.manager, target, message.strip(), self.console.write)
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

    async def _cmd_decide(self, raw: str) -> None:
        """``decidir <id>``; ao responder o último pedido de uma pesquisa ``aguarda_pesquisador`` ela é retomada."""
        try:
            request_id = int(raw.split()[0].lstrip("#"))
        except (ValueError, IndexError):
            self.console.write(f"\n  {RED}Use: decidir <id> (veja 'pendentes'){RESET}\n")
            return
        result = decide(self.gate, request_id, self._input, self.console.write, manager=self.manager)
        if not result.resolved or result.request is None or not result.request.session_id:
            return
        session = self.manager.get(result.request.session_id)
        if session is not None and session.status != "aguarda_pesquisador":
            self._post_orientation(session, result.request)  # sessão em andamento: a orientação vai à caixa agora
        if session is None or session.status != "aguarda_pesquisador":
            return
        remaining = self.gate.pending(chain_session_ids(self.manager, session.id))
        if remaining:
            ids = ", ".join(f"#{r.id}" for r in remaining)
            self.console.write(f"  {DIM}{label(session)} ainda tem pedidos pendentes: {ids}.{RESET}\n")
            return
        if await self._apply_continuity(session, result.request):
            return
        self.console.write(f"  {DIM}Último pedido de {label(session)} respondido: retomando a pesquisa.{RESET}")
        await self.resume(session)

    def _post_orientation(self, session: Any, request: Any) -> None:
        """Orientação de uma resposta ``orientar`` de ``decidir_continuidade`` vai à caixa de entrada da sessão."""
        if request.decisao != "decidir_continuidade" or (request.resposta or {}).get("acao") != "orientar":
            return
        from src.session.inbox import InboxError, SessionInbox

        try:
            SessionInbox().post(session.id, str((request.resposta or {}).get("orientacao", "")))
        except InboxError as exc:
            self.console.write(f"  {RED}Orientação não gravada: {exc}{RESET}")

    async def _apply_continuity(self, session: Any, request: Any) -> bool:
        """Efeito das respostas de ``decidir_continuidade`` (ADR 021 §5.2): ``parar``, ``aceitar_conjunto`` e
        ``objetivo_atingido`` fecham a pesquisa pelo terminal, sem processo novo; ``orientar`` deixa o texto na caixa
        de entrada (a sessão retomada o entrega ao Researcher). Devolve ``True`` se fechou a pesquisa."""
        if request.decisao != "decidir_continuidade":
            return False
        action = (request.resposta or {}).get("acao")
        if action == "orientar":
            self._post_orientation(session, request)
            return False
        reason = {
            "parar": "planos_rejeitados" if request.motivo == "planos_rejeitados" else "encerrada_pesquisador",
            "aceitar_conjunto": "solucao_encontrada",
            "objetivo_atingido": "solucao_encontrada",
        }.get(str(action))
        if reason is None:
            return False
        from src.session.closing import close_by_researcher

        report = close_by_researcher(self.manager, self.starter.base_dir, session, motivo=reason)
        if report is not None and action == "objetivo_atingido":
            from src.cli.gate_commands import register_objective_reached

            register_objective_reached(session)
        if report is not None:
            self.console.write(f"  Pesquisa {label(session)} encerrada ({reason}). Relatório: {report}")
        return True

    def _cmd_follow(self, target: str) -> None:
        """``acompanhar <apelido>``: histórico e eventos novos em nível detalhado, até ``voltar`` ou Ctrl+C."""
        session = resolve_target(self.manager, target)
        if session is None:
            self.console.write(f"\n  {RED}Use: acompanhar <apelido|id> (pesquisa não encontrada: '{target}'){RESET}\n")
            return
        show_history(self.reader, session, self.console.write)
        if self._events is not None:
            self._events.follow(session.id)
        try:
            while True:
                self.console.waiting_for_input = True
                try:
                    answer = self._input(f"  {DIM}acompanhando {label(session)} >{RESET} ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    break
                finally:
                    self.console.waiting_for_input = False
                if answer in ("voltar", "sair", "exit"):
                    break
        finally:
            if self._events is not None:
                self._events.follow(None)
        self.console.write(f"  {DIM}Fim do acompanhamento de {label(session)}; a pesquisa continua.{RESET}\n")

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
    try:
        code = repl.open()
    except Exception as exc:  # noqa: BLE001 - sem o banco não há presença nem sessões: o REPL não abre
        print(f"\n  {STATUS_ICONS['error']} {RED}Não foi possível abrir o REPL ({type(exc).__name__}: {exc}). "
              f"Confira o PostgreSQL (docker compose up -d).{RESET}\n")
        return EXIT_ERROR
    if code is not None:
        return code
    try:
        await repl.review_unfinished()
        await repl.loop()
    finally:
        repl.close()
    return 0


def run_with_prompt_interrupt(coro_factory: Callable[[], Any]) -> Any:
    """Roda a corrotina com Ctrl+C no prompt levantando ``KeyboardInterrupt`` em ``input()``.

    O ``asyncio.run`` só instala o seu tratamento de ``SIGINT`` se o atual for o padrão; com este, o Ctrl+C no prompt
    encerra o REPL em vez de cancelar a tarefa principal (as pesquisas, em processos próprios, não recebem o sinal).
    """

    def raise_interrupt(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGINT, raise_interrupt)
    try:
        return asyncio.run(coro_factory())
    finally:
        signal.signal(signal.SIGINT, previous)


def run_repl(**kwargs: Any) -> int:
    """Executa o REPL (``interactive_mode``) e devolve o código de saída."""
    return run_with_prompt_interrupt(lambda: interactive_mode(**kwargs))
