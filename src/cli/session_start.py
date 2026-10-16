"""Início e retomada de pesquisas pelo terminal (v18.7-background-sessions, design §1.1 a §1.3).

O terminal faz, nesta ordem, tudo o que exige o pesquisador antes de a pesquisa começar: carregar e confirmar
``input_context/``, resolver os modelos, vincular o projeto e confirmar o Problema, confirmar o modo sem limite e, na
retomada, a sessão resolvida. Depois verifica a memória, grava o arquivo de lançamento e cria o processo da sessão
(``src/cli/session_process.py``). Nunca executa agentes: quem os executa é o processo da sessão.
"""

from __future__ import annotations

import argparse
import dataclasses
import signal
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src import config
from src.cli.banner import print_session_banner
from src.cli.context_commands import load_context_with_confirmation
from src.cli.unlimited import _project_marked_unlimited, resolve_unlimited_budget
from src.logger import get_logger
from src.orchestration.usage import UsageBudget
from src.session.exit_codes import EXIT_ERROR, EXIT_INTERRUPTED, EXIT_LOW_MEMORY, EXIT_UNLIMITED_NOT_CONFIRMED
from src.session.launcher import (
    LaunchError,
    LaunchSpec,
    MemoryCheck,
    check_memory,
    context_digest,
    log_tail,
    spawn_session,
    summarize_task,
    wait_registered,
    write_launch_file,
)
from src.session.manager import Session, SessionManager
from src.utils.terminal import DIM, RED, RESET, STATUS_ICONS, YELLOW

logger = get_logger(__name__)

MEMORY_POLICY_ASK = "perguntar"  # REPL: abaixo do mínimo mostra o aviso e pergunta
MEMORY_POLICY_FAIL = "falhar"  # comando direto: abaixo do mínimo falha com código 5 (ninguém decide)


class LaunchRefused(Exception):
    """O terminal desistiu antes de criar o processo (recusa, falha de pré-requisito ou "não" à pergunta)."""

    def __init__(self, message: str, code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Started:
    """Processo da sessão criado."""

    proc: subprocess.Popen[bytes]
    path: Path
    spec: LaunchSpec
    session: Session | None = None


def exit_code_of(returncode: int) -> int:
    """Código do processo -> código do comando (morte por sinal vira ``128 + sinal``)."""
    return returncode if returncode >= 0 else 128 + abs(returncode)


def wait_foreground(proc: subprocess.Popen[bytes]) -> int:
    """Espera o processo da sessão repassando ``SIGINT`` a ele (o 1º é gracioso; o 2º, imediato; design §1.1)."""

    def forward(signum: int, frame: Any) -> None:
        try:
            proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass

    previous = signal.signal(signal.SIGINT, forward)
    try:
        return exit_code_of(proc.wait())
    finally:
        signal.signal(signal.SIGINT, previous)


def _say(output: Callable[[str], Any], text: str) -> None:
    output(f"\n  {text}\n")


class SessionStarter:
    """Prepara e lança pesquisas. Entrada, saída, verificação de memória e criação do processo são injetáveis."""

    def __init__(
        self,
        *,
        session_manager: SessionManager | None = None,
        base_dir: Path | str | None = None,
        context_dir: str | None = None,
        monitor: Any | None = None,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], Any] = print,
        spawn: Callable[..., subprocess.Popen[bytes]] = spawn_session,
        spawn_module: str | None = None,
        spawn_env: dict[str, str] | None = None,
        spawn_cwd: Path | None = None,
        log_dir: Path | None = None,
        launch_timeout: float | None = None,
        binder_factory: Callable[[Any, argparse.Namespace], Any] | None = None,
        prerequisites: Callable[[], None] | None = None,
    ) -> None:
        self._prerequisites = prerequisites
        self._prerequisites_done = False
        self._binder_factory = binder_factory or self._default_binder
        self._binder: Any | None = None
        self.manager = session_manager or SessionManager()
        self.base_dir = Path(base_dir or config.OUTPUT_BASE_DIR)
        self.context_dir = context_dir or config.INPUT_CONTEXT_DIR
        self._monitor = monitor
        self._input = input_fn
        self._output = output_fn
        self._spawn = spawn
        self._spawn_kwargs: dict[str, Any] = {}
        if spawn_module:
            self._spawn_kwargs["module"] = spawn_module
        if spawn_env is not None:
            self._spawn_kwargs["env"] = spawn_env
        if spawn_cwd is not None:
            self._spawn_kwargs["cwd"] = spawn_cwd
        self._log_dir = log_dir
        self._launch_timeout = launch_timeout

    @staticmethod
    def _default_binder(routing: Any, args: argparse.Namespace) -> Any:
        """``ProjectBinder`` de produção; o modelo do papel researcher assina o rascunho do Problema."""
        from src.cli.project_session import ProjectBinder

        def open_store() -> Any:
            from src.knowledge.factory import open_graph_store

            # Início da sessão: reconcilia o índice semântico antes da primeira consulta ao grafo.
            return open_graph_store(reconcile=True)

        try:
            researcher_model: str | None = routing.resolution("researcher").id
        except Exception:  # noqa: BLE001 - sem modelo conhecido, a autoria do rascunho fica só com o papel
            researcher_model = None
        return ProjectBinder(open_store, project_arg=getattr(args, "project", None), researcher_model=researcher_model)

    def _ensure_prerequisites(self) -> None:
        """Verificação da infraestrutura (daemon, imagem do sandbox, PostgreSQL, Qdrant) antes da primeira pesquisa."""
        if self._prerequisites_done:
            return
        check = self._prerequisites
        if check is None:
            from src.cli.infrastructure import ensure_infrastructure as check
        try:
            check()
        except RuntimeError as exc:  # inclui PlatformImageError: a sessão não começa
            raise LaunchRefused(f"Falha na inicialização: {exc}", EXIT_ERROR) from exc
        self._prerequisites_done = True

    # -- memória (design §1.3) -------------------------------------------------------------------------------------

    def _memory_gate(self, policy: str) -> None:
        """Lê a memória e aplica a política. Leitura desconhecida só registra um evento e segue (decisão do pesquisador
        de 2026-10-16); abaixo do mínimo, o REPL pergunta e o comando direto falha com o código 5."""
        if self._monitor is None:
            from src.host.health import HealthMonitor

            self._monitor = HealthMonitor()
        try:
            running = self.manager.list_orchestrator(["active"])
        except Exception:  # noqa: BLE001 - sem a lista o aviso só não mostra as pesquisas em execução
            running = []
        check = check_memory(self._monitor, running)
        if check.unknown:
            logger.warning("Memória disponível desconhecida; a pesquisa segue", extra={"minimo": check.minimum_mb})
            self._record_unknown_memory(check)
            return
        if check.ok:
            return
        if policy == MEMORY_POLICY_FAIL:
            raise LaunchRefused(
                f"{check.message()}. Libere memória, encerre pesquisas em execução ou reduza MIN_AVAILABLE_MEMORY_MB.",
                EXIT_LOW_MEMORY,
            )
        self._output(f"\n  {YELLOW}{STATUS_ICONS['warning']} {check.message()}.{RESET}")
        if check.running:
            self._output(f"  {DIM}Pesquisas em execução:{RESET}")
            for s in check.running:
                self._output(f"    - {s.alias or s.id} ({s.payload.get('mode', '?')}, PID {s.pid or '?'})")
        try:
            answer = self._input("  Iniciar mesmo assim? [s/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("s", "sim", "y", "yes"):
            raise LaunchRefused("Início cancelado pelo pesquisador (memória insuficiente).", EXIT_ERROR)

    @staticmethod
    def _record_unknown_memory(check: MemoryCheck) -> None:
        try:
            from src.observability.telemetry import get_telemetry

            get_telemetry().record_agent_event(
                execution_id="terminal",
                session_id="terminal",
                agent_id="terminal",
                event_type="memoria_desconhecida",
                payload={"minimo_mb": check.minimum_mb},
            )
        except Exception as exc:  # noqa: BLE001 - telemetria nunca impede o início
            logger.warning("Evento memoria_desconhecida não registrado", extra={"error": type(exc).__name__})

    # -- lançamento ------------------------------------------------------------------------------------------------

    def _launch(self, spec: LaunchSpec, *, foreground: bool) -> Started:
        path = write_launch_file(spec, self.base_dir)
        try:
            proc = self._spawn(path, foreground=foreground, log_dir=self._log_dir, **self._spawn_kwargs)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return Started(proc=proc, path=path, spec=spec)

    async def wait_registered(self, started: Started) -> Session:
        """Espera o processo registrar a sessão (``SESSION_LAUNCH_TIMEOUT_SECONDS``); falha cita o fim do log."""
        timeout = self._launch_timeout if self._launch_timeout is not None else config.SESSION_LAUNCH_TIMEOUT_SECONDS
        try:
            session = await wait_registered(
                started.spec.launch_id,
                started.proc,
                timeout,
                session_manager=self.manager,
                on_failure_detail=lambda: log_tail(started.path, self._log_dir),
            )
        except LaunchError as exc:
            raise LaunchRefused(str(exc), EXIT_ERROR) from exc
        started.session = session
        return session

    def _context_digest(self) -> str:
        return context_digest(self.context_dir)

    @staticmethod
    def _unlimited_payload(budget: UsageBudget) -> dict[str, str] | None:
        if not budget.unlimited:
            return None
        from src.orchestration.unlimited_mode import get_activation

        activation = get_activation()
        if activation is None:
            raise LaunchRefused("modo sem limite sem confirmação registrada.", EXIT_UNLIMITED_NOT_CONFIRMED)
        return {"origem": activation.origem, "confirmado_em": activation.confirmado_em}

    def _confirm_unlimited(self, args: argparse.Namespace, budget: UsageBudget, launch_id: str) -> UsageBudget:
        """Confirma o modo sem limite no terminal: o pedido ``ativar_modo_sem_limite`` leva o ``launch_id`` como
        referência e o processo da sessão o confere e consome no banco (design §1.1)."""
        from src.orchestration.unlimited_mode import UnlimitedModeError

        try:
            return resolve_unlimited_budget(
                args, budget, project_marked=_project_marked_unlimited, reference=launch_id
            )
        except UnlimitedModeError as exc:
            raise LaunchRefused(str(exc), EXIT_UNLIMITED_NOT_CONFIRMED) from exc

    @staticmethod
    async def _routing(model_pin: str | None) -> Any:
        from src.llm.catalog import CatalogError
        from src.llm.routing import RoutingError
        from src.llm.session import build_session_routing

        try:
            return await build_session_routing(cli_pins={"researcher": model_pin} if model_pin else None)
        except (RoutingError, CatalogError) as exc:
            raise LaunchRefused(f"Falha na resolução de modelos: {exc}", EXIT_ERROR) from exc

    # -- pesquisa nova ---------------------------------------------------------------------------------------------

    async def start_new(
        self,
        prompt: str,
        *,
        mode: str,
        budget: UsageBudget,
        args: argparse.Namespace,
        terminal_id: str | None,
        foreground: bool,
        memory_policy: str,
    ) -> Started:
        """Prepara e lança uma pesquisa nova (o ``ProjectBinder`` é um por REPL: um projeto por REPL).

        Args:
            terminal_id: Presença do terminal que lança (``None`` em ``--background``).

        Raises:
            LaunchRefused: Recusa antes de criar o processo (``code`` é o código de saída do comando).
        """
        self._ensure_prerequisites()
        bundle = load_context_with_confirmation(self.context_dir)
        if bundle is None:
            raise LaunchRefused("Início cancelado (contexto de entrada).", EXIT_ERROR)
        routing = await self._routing(getattr(args, "model", None))
        from src.cli.project_session import ProjectFlowError
        from src.llm.session import bind_session_routing

        try:
            bind_session_routing(routing)  # o rascunho do Problema usa o modelo do papel researcher
            if self._binder is None:
                self._binder = self._binder_factory(routing, args)
            binding = await self._binder.bind(prompt, bundle)
        except ProjectFlowError as exc:
            raise LaunchRefused(str(exc), EXIT_ERROR) from exc
        launch_id = str(uuid.uuid4())
        budget = self._confirm_unlimited(args, budget, launch_id)
        self._memory_gate(memory_policy)
        print_session_banner(mode, budget=budget, llm_routing=routing, context_bundle=bundle)
        projeto = None
        project_mode = None
        if binding.mode == "sem_grafo":
            self._output(f"\n  {YELLOW}SEM GRAFO: projeto e Problema não aplicados nesta sessão.{RESET}")
            project_mode = "sem_grafo"
        else:
            projeto = {"project_id": binding.project_id, "project_context": binding.context_block}
        spec = LaunchSpec(
            launch_id=launch_id,
            tipo="nova",
            prompt=prompt,
            modo=mode,
            orcamento=dataclasses.asdict(budget),
            contexto={"dir": str(self.context_dir), "digest": self._context_digest()},
            primeiro_plano=foreground,
            ilimitado=self._unlimited_payload(budget),
            projeto=projeto,
            project_mode=project_mode,
            model_pin=getattr(args, "model", None),
            terminal_id=terminal_id,
            resumo=summarize_task(prompt),
        )
        return self._launch(spec, foreground=foreground)

    # -- retomada --------------------------------------------------------------------------------------------------

    async def start_resume(
        self,
        session_id: str,
        *,
        mode: str | None,
        budget: UsageBudget,
        args: argparse.Namespace,
        terminal_id: str | None,
        foreground: bool,
        memory_policy: str,
        confirm: Callable[[str], bool] | None = None,
    ) -> Started:
        """Valida a retomada (a confirmação de sessão resolvida é do terminal) e lança o processo que a executa.

        Raises:
            LaunchRefused: Retomada recusada ou desistência antes de criar o processo.
        """
        from src.session.resume import ResumeError, prepare_resume

        self._ensure_prerequisites()
        store = index = None
        try:
            from src.knowledge.factory import open_graph_store, open_knowledge_runtime

            runtime = open_knowledge_runtime()
            store = runtime.store if runtime is not None else open_graph_store()
            index = runtime.index if runtime is not None else None
        except Exception as exc:  # noqa: BLE001 - sem grafo, a preparação recusa se a sessão tinha projeto
            logger.warning("Grafo indisponível para a retomada", extra={"error": type(exc).__name__})
        asked = {"confirmed": False}
        ask = confirm or self._ask_yes_no

        def confirm_wrapper(question: str) -> bool:
            answer = bool(ask(question))
            asked["confirmed"] = answer
            return answer

        try:
            prep = await prepare_resume(
                session_manager=self.manager,
                base_dir=self.base_dir,
                session_id=session_id,
                project_arg=getattr(args, "project", None),
                mode=mode,
                store=store,
                index=index,
                confirm=confirm_wrapper,
            )
        except ResumeError as exc:
            raise LaunchRefused(str(exc), EXIT_ERROR) from exc
        routing = await self._routing(getattr(args, "model", None))
        launch_id = str(uuid.uuid4())
        budget = self._confirm_unlimited(args, budget, launch_id)  # a retomada não herda o modo sem limite
        self._memory_gate(memory_policy)
        print_session_banner(prep.mode, budget=budget, llm_routing=routing)
        if prep.accumulated.get("tokens") or prep.accumulated.get("minutos"):
            self._output(
                f"  {DIM}Consumo acumulado da cadeia: {prep.accumulated['tokens']:.0f} tokens, "
                f"{prep.accumulated['minutos']:.1f} min (esta sessão tem orçamento novo).{RESET}"
            )
        self._output(
            f"\n  {DIM}Retomando a sessão {prep.state.source_session_id} a partir do checkpoint "
            f"({len(prep.state.completed)} subtarefa(s) concluída(s) não serão reexecutadas); "
            f"orçamento novo (modo: {prep.mode}).{RESET}\n"
        )
        project_arg = getattr(args, "project", None)
        spec = LaunchSpec(
            launch_id=launch_id,
            tipo="retomada",
            prompt=prep.prompt,
            modo=prep.mode,
            orcamento=dataclasses.asdict(budget),
            contexto={"dir": str(self.context_dir), "digest": self._context_digest()},
            primeiro_plano=foreground,
            ilimitado=self._unlimited_payload(budget),
            projeto={"project_id": project_arg, "project_context": ""} if project_arg else None,
            model_pin=getattr(args, "model", None),
            retomada={"session_id": prep.state.source_session_id, "confirmado_resolvida": asked["confirmed"]},
            terminal_id=terminal_id,
            resumo=summarize_task(prep.prompt),
        )
        return self._launch(spec, foreground=foreground)

    def _ask_yes_no(self, question: str) -> bool:
        """Pergunta sim/não; sem terminal a resposta é "não" (nada é confirmado por omissão)."""
        from src.cli.project_session import is_interactive

        if not is_interactive():
            return False
        try:
            return self._input(f"  {question} [s/N] ").strip().lower() in ("s", "sim", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False


async def run_foreground(starter_call: Callable[[], Any], presence: Any | None) -> int:
    """Roda ``starter_call`` (que devolve ``Started``), espera o processo em primeiro plano e devolve o código.

    A presença (``tipo='direto'``) existe do início ao fim; recusas antes do processo viram o código da recusa.
    """
    try:
        started = await starter_call()
        return wait_foreground(started.proc)  # na thread principal: só ela instala o repasse de SIGINT
    except LaunchRefused as refusal:
        print(f"\n  {STATUS_ICONS['error']} {RED}{refusal}{RESET}\n")
        return refusal.code
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    finally:
        if presence is not None:
            presence.stop()
