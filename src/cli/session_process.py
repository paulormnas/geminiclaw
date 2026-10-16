"""Processo da sessão de pesquisa (v18.7-background-sessions, design §1.1, §1.8 e §1.10).

``python -m src.cli.session_process --launch <arquivo>``: lê o lançamento gravado pelo terminal (dado não confiável),
executa o orquestrador, os agentes e o laço autônomo, registra PID, host, apelido e batimento na sessão e sai com o
código de ``exit_code_for(motivo_parada)``. Nunca lê o terminal: ``stdin`` fechado e ``input`` proibido.
"""

import src.config  # noqa: F401, I001 - primeiro import do projeto: retira os nomes negados do ambiente (§6.2)

import argparse
import asyncio
import builtins
import datetime
import os
import signal
import socket
import sys
import threading
from collections.abc import Callable, Iterable
from typing import Any

from src.logger import get_logger
from src.session.chain import chain_session_ids
from src.session.exit_codes import (
    EXIT_ERROR,
    EXIT_INTERRUPTED,
    EXIT_SESSION_LOST,
    EXIT_UNLIMITED_NOT_CONFIRMED,
    exit_code_for,
)
from src.session.launcher import LaunchError, LaunchSpec, context_digest, read_launch_file, summarize_task

logger = get_logger(__name__)


class StdinForbiddenError(RuntimeError):
    """Algum código do processo da sessão tentou ler a entrada padrão (ADR 023 §4.1)."""


def _forbidden_input(*_args: Any, **_kwargs: Any) -> str:
    raise StdinForbiddenError(
        "o processo da sessão não lê a entrada padrão: o que exige o pesquisador vira pendência registrada."
    )


def install_input_guard() -> None:
    """Substitui ``builtins.input`` por uma função que levanta ``StdinForbiddenError``."""
    builtins.input = _forbidden_input


def process_started_at() -> str:
    """Início deste processo em ISO 8601 (UTC), como o terminal o compara com ``psutil.Process(pid).create_time()``."""
    import psutil

    created = psutil.Process(os.getpid()).create_time()
    return datetime.datetime.fromtimestamp(created, datetime.timezone.utc).isoformat()


def project_title(project_id: str | None) -> str | None:
    """Título do projeto no grafo (para o apelido); ``None`` sem projeto ou com o grafo indisponível."""
    if not project_id:
        return None
    try:
        from src.knowledge.factory import open_graph_store
        from src.knowledge.projects import get_project

        return get_project(open_graph_store(), project_id).titulo
    except Exception as exc:  # noqa: BLE001 - sem o título o apelido cai em ``sessao-NN``
        logger.warning("Título do projeto indisponível para o apelido", extra={"error": type(exc).__name__})
        return None


def register_session_process(session_manager: Any, session: Any, spec: LaunchSpec, *, title: str | None) -> str:
    """Grava PID, host, início do processo, terminal, apelido e resumo; a retomada herda o apelido da cadeia.

    Returns:
        O apelido gravado.
    """
    from src.session.alias import next_alias, slugify

    alias: str | None = None
    if spec.retomada is not None:
        source = session_manager.get(spec.retomada["session_id"])
        alias = getattr(source, "alias", None) if source is not None else None
    if not alias:
        alias = next_alias(title, session_manager.aliases_in_use(slugify(title)))
    session_manager.register_process(
        session.id,
        pid=os.getpid(),
        host=socket.gethostname(),
        process_started_at=process_started_at(),
        terminal_id=spec.terminal_id,
        alias=alias,
        resumo=spec.resumo or summarize_task(spec.prompt),
    )
    return alias


async def watch_presence(
    terminal_id: str | None,
    *,
    interval: float | None = None,
    present: Callable[[str | None], bool] | None = None,
) -> None:
    """Sessão ``assisted``: lê a presença do terminal a cada ``SESSION_PRESENCE_CHECK_SECONDS``; na ausência pede a
    suspensão (a sessão para de despachar, deixa o que está em curso terminar e grava o checkpoint)."""
    from src import config
    from src.orchestration.usage import request_suspension
    from src.session.presence import terminal_present

    check = present or terminal_present
    wait = config.SESSION_PRESENCE_CHECK_SECONDS if interval is None else interval
    while True:
        try:
            absent = not await asyncio.to_thread(check, terminal_id)
        except Exception as exc:  # noqa: BLE001 - sem ler a presença não se suspende por engano
            logger.warning("Leitura da presença falhou", extra={"error": type(exc).__name__})
            absent = False
        if absent:
            logger.warning("Terminal ausente: a sessão assisted será suspensa", extra={"terminal_id": terminal_id})
            request_suspension()
            return
        await asyncio.sleep(wait)


class SessionRunner:
    """Executa o lançamento no orquestrador e devolve o código de saída."""

    def __init__(self, spec: LaunchSpec, *, orchestrator: Any | None = None) -> None:
        self.spec = spec
        self.orchestrator = orchestrator
        self.session_id: str | None = None
        self._task: "asyncio.Task[Any] | None" = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- sessão perdida (§1.8) --------------------------------------------------------------------------------------

    def _on_session_lost(self, session_id: str) -> None:
        """Thread do batimento: remove os containers da sessão, cancela a tarefa e arma a saída à força."""
        from src.config import SESSION_LOST_EXIT_GRACE_SECONDS
        from src.skills.code.sandbox import cleanup_sandbox_containers

        logger.error("Sessão continuada por outra: encerrando o processo", extra={"session_id": session_id})
        try:
            cleanup_sandbox_containers(chain_session_ids(self.orchestrator.session_manager, session_id))
        except Exception as exc:  # noqa: BLE001 - a saída não depende da limpeza
            logger.warning("Limpeza de sandboxes da sessão perdida falhou", extra={"error": type(exc).__name__})
        if self._loop is not None and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)
        timer = threading.Timer(SESSION_LOST_EXIT_GRACE_SECONDS, lambda: os._exit(EXIT_SESSION_LOST))
        timer.daemon = True
        timer.start()

    # -- execução ---------------------------------------------------------------------------------------------------

    async def run(self) -> int:
        spec = self.spec
        from src.llm.catalog import CatalogError
        from src.llm.routing import RoutingError
        from src.llm.session import build_session_routing
        from src.orchestration.orchestrator import Orchestrator, ResumeConflictError
        from src.orchestration.unlimited_mode import UnlimitedActivation, set_activation
        from src.orchestration.usage import UsageBudget
        from src.research_data.context_loader import ContextLoader
        from src.session.manager import SessionManager

        actual = context_digest(spec.contexto["dir"])
        if actual != spec.contexto["digest"]:
            print(
                "O conteúdo de input_context/ mudou depois da confirmação do pesquisador "
                f"(digest confirmado {spec.contexto['digest'][:12]}…, atual {actual[:12]}…); a sessão não foi criada."
            )
            return EXIT_ERROR
        try:
            budget = UsageBudget(**spec.orcamento)
        except (TypeError, ValueError) as exc:
            print(f"Orçamento inválido no lançamento: {exc}")
            return EXIT_ERROR
        if spec.ilimitado:
            refusal = self._check_unlimited_authorization()
            if refusal is not None:
                print(refusal)
                return EXIT_UNLIMITED_NOT_CONFIRMED
        set_activation(UnlimitedActivation(**spec.ilimitado) if spec.ilimitado else None)

        if self.orchestrator is None:
            self.orchestrator = Orchestrator(session_manager=SessionManager())
        orchestrator = self.orchestrator
        orchestrator.session_lost_handler = self._on_session_lost
        manager = orchestrator.session_manager
        try:
            routing = await build_session_routing(
                cli_pins={"researcher": spec.model_pin} if spec.model_pin else None
            )
        except (RoutingError, CatalogError) as exc:
            print(f"Falha na resolução de modelos: {exc}")
            return EXIT_ERROR

        project_id = (spec.projeto or {}).get("project_id")
        title = await asyncio.to_thread(project_title, project_id) if project_id else None

        def on_created(session: Any) -> None:
            self.session_id = session.id
            register_session_process(manager, session, spec, title=title)

        kwargs: dict[str, Any] = {
            "budget": budget,
            "llm_routing": routing,
            "launch_id": spec.launch_id,
            "on_session_created": on_created,
        }
        try:
            if spec.retomada is None:
                kwargs.update(
                    mode=spec.modo,
                    context_bundle=ContextLoader(spec.contexto["dir"]).load(),
                    project_id=project_id,
                    project_context=(spec.projeto or {}).get("project_context"),
                    project_mode=spec.project_mode,
                )
                prompt = spec.prompt
            else:
                prompt, resume_kwargs = await self._prepare_resume(orchestrator)
                kwargs.update(resume_kwargs)
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.ensure_future(orchestrator.handle_request(prompt, **kwargs))
            watcher = None
            if kwargs.get("mode") == "assisted":  # semi e auto não leem a presença (design §1.6)
                watcher = asyncio.ensure_future(watch_presence(spec.terminal_id))
            try:
                result = await self._task
            finally:
                if watcher is not None:
                    watcher.cancel()
        except asyncio.CancelledError:
            return EXIT_SESSION_LOST if self.session_id in orchestrator._lost_sessions else EXIT_INTERRUPTED
        except ResumeConflictError as exc:
            print(f"Retomada recusada: {exc}")
            return EXIT_ERROR
        except Exception as exc:  # noqa: BLE001 - o código de saída reflete a falha
            logger.error("Erro na sessão", extra={"error": str(exc)}, exc_info=True)
            print(f"Erro: {exc}")
            return self._exit_code_from_session(manager, EXIT_ERROR)
        from src.cli.reports import format_result

        print(format_result(result))
        return self._exit_code_from_session(manager, EXIT_ERROR, getattr(result, "session_id", None))

    def _check_unlimited_authorization(self) -> str | None:
        """Confere e consome no banco o pedido ``ativar_modo_sem_limite`` do lançamento (``referencia``: ``launch_id``).

        Antes de a sessão existir, a cadeia é vazia: vale só o pedido do terminal fora de sessão (``session_id`` nulo).
        """
        from src.gate.persistent_gate import session_gate
        from src.gate.types import GateAuthorizationRefused

        try:
            session_gate().consume_authorized("ativar_modo_sem_limite", self.spec.launch_id, [])
        except GateAuthorizationRefused as exc:
            return (
                "O modo sem limite não foi autorizado pelo pesquisador para este lançamento "
                f"({exc.motivo}); a sessão não foi criada."
            )
        except Exception as exc:  # noqa: BLE001 - sem o banco não há como conferir: falha fechada
            return f"Autorização do modo sem limite não conferida ({type(exc).__name__}); a sessão não foi criada."
        return None

    def _exit_code_from_session(self, manager: Any, default: int, session_id: str | None = None) -> int:
        sid = session_id or self.session_id
        session = manager.get(sid) if sid else None
        if session is None:
            return default
        motivo = (session.payload or {}).get("motivo_parada")
        return exit_code_for(motivo) if motivo else default

    async def _prepare_resume(self, orchestrator: Any) -> tuple[str, dict[str, Any]]:
        """Valida a retomada (a confirmação de sessão resolvida foi dada no terminal) e monta os argumentos."""
        from src.research_data.context_loader import ContextBundle
        from src.session.resume import prepare_resume

        spec = self.spec
        assert spec.retomada is not None
        store = index = None
        try:
            from src.knowledge.factory import open_graph_store, open_knowledge_runtime

            runtime = open_knowledge_runtime()
            store = runtime.store if runtime is not None else open_graph_store()
            index = runtime.index if runtime is not None else None
        except Exception as exc:  # noqa: BLE001 - sem grafo, a preparação recusa se a sessão tinha projeto
            logger.warning("Grafo indisponível para a retomada", extra={"error": type(exc).__name__})
        confirmed = bool(spec.retomada.get("confirmado_resolvida"))
        prep = await prepare_resume(
            session_manager=orchestrator.session_manager,
            base_dir=orchestrator.output_manager.base_dir,
            session_id=spec.retomada["session_id"],
            project_arg=(spec.projeto or {}).get("project_id"),
            mode=spec.modo,
            store=store,
            index=index,
            confirm=lambda _message: confirmed,
        )
        return prep.prompt, {
            "mode": prep.mode,
            "context_bundle": ContextBundle(),
            "project_id": prep.state.project_id,
            "project_context": prep.project_context,
            "project_mode": None if prep.state.project_id else "sem_grafo",
            "resume": prep.state,
        }


def _install_sigint_handler(runner_ref: Callable[[], SessionRunner | None]) -> None:
    """1º ``SIGINT``/``SIGTERM``: fechamento gracioso com checkpoint; 2º: limpeza dos sandboxes desta sessão e saída."""

    def handler(signum: int, frame: Any) -> None:
        from src.config import LIMIT_GRACE_SECONDS
        from src.orchestration.usage import interrupt_requested, request_interrupt, session_active

        if session_active() and not interrupt_requested():
            request_interrupt()
            print(
                "\nInterrupção pedida: a sessão fecha com checkpoint assim que as subtarefas em andamento terminarem "
                f"(até {LIMIT_GRACE_SECONDS}s). Um segundo SIGINT encerra imediatamente.",
                flush=True,
            )
            return
        runner = runner_ref()
        removed = 0
        if runner is not None and runner.orchestrator is not None and runner.session_id:
            from src.skills.code.sandbox import cleanup_sandbox_containers

            removed = cleanup_sandbox_containers(
                chain_session_ids(runner.orchestrator.session_manager, runner.session_id)
            )
        print(f"\nInterrupção recebida: {removed} sandbox(es) desta sessão removido(s).", flush=True)
        try:
            from src.observability.telemetry import get_telemetry

            asyncio.run(get_telemetry().flush())
        except Exception as exc:  # noqa: BLE001
            logger.error("Erro no flush de telemetria (SIGINT)", extra={"error": type(exc).__name__})
        os._exit(EXIT_INTERRUPTED)

    signal.signal(signal.SIGINT, handler)
    # `SIGTERM` (o runner do benchmark encerra o grupo no tempo limite) tem o mesmo tratamento: pede o fechamento com
    # checkpoint e, se repetido, limpa só os sandboxes desta sessão e sai.
    signal.signal(signal.SIGTERM, handler)


def main(
    argv: Iterable[str] | None = None, *, runner_factory: Callable[[LaunchSpec], SessionRunner] = SessionRunner
) -> int:
    """Ponto de entrada: lê o lançamento, roda a sessão e devolve o código de saída."""
    parser = argparse.ArgumentParser(prog="python -m src.cli.session_process")
    parser.add_argument("--launch", required=True, help="arquivo de lançamento gravado pelo terminal")
    args = parser.parse_args(list(argv) if argv is not None else None)

    install_input_guard()
    from src.egress.routing import install_provider_resolver

    install_provider_resolver()
    try:
        spec = read_launch_file(args.launch)
    except LaunchError as exc:
        print(f"Lançamento recusado: {exc}", file=sys.stderr)
        return EXIT_ERROR
    runner = runner_factory(spec)
    _install_sigint_handler(lambda: runner)
    try:
        code = asyncio.run(runner.run())
    except KeyboardInterrupt:
        code = EXIT_INTERRUPTED
    try:
        from src.observability.telemetry import get_telemetry

        asyncio.run(get_telemetry().flush())
    except Exception as exc:  # noqa: BLE001
        logger.error("Erro no flush de telemetria final", extra={"error": type(exc).__name__})
    return code


if __name__ == "__main__":
    sys.exit(main())
