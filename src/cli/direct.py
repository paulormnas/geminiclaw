"""Comando direto (``geminiclaw "tarefa"``, ``resume``, ``continue``) (v18.7-background-sessions, design §1.1 e §1.4).

Por padrão o comando é o terminal: cria o processo da sessão, registra a presença (``tipo='direto'``), mostra a saída
dele, repassa o ``SIGINT`` e sai com o código de ``exit_code_for(motivo_parada)``. ``--background`` cria o processo,
imprime o apelido e o PID e sai com 0, sem presença (a sessão segue sem terminal).
"""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable
from typing import Any

from src.cli.session_start import (
    MEMORY_POLICY_FAIL,
    LaunchRefused,
    SessionStarter,
    Started,
    run_foreground,
)
from src.logger import get_logger
from src.orchestration.usage import UsageBudget
from src.session.exit_codes import EXIT_ERROR
from src.session.presence import TIPO_DIRETO, TerminalPresence
from src.utils.terminal import RED, RESET, STATUS_ICONS

logger = get_logger(__name__)

BACKGROUND_ASSISTED_REFUSAL = (
    "--background não combina com --mode assisted: o modo assisted precisa de um terminal presente; use o REPL."
)


def sweep_stopped(starter: SessionStarter) -> None:
    """Marca como ``interrompida`` as sessões paradas antes de iniciar ou retomar (nunca levanta)."""
    from src.cli.repl import make_recover
    from src.session.watch import SessionWatch

    SessionWatch(starter.manager, recover=make_recover(starter.manager)).sweep()


async def _run(
    starter: SessionStarter,
    launch: Callable[[str | None, bool], Awaitable[Started]],
    *,
    background: bool,
    presence_factory: Callable[[], TerminalPresence] = lambda: TerminalPresence(TIPO_DIRETO),
) -> int:
    if background:
        try:
            started = await launch(None, False)
            session = await starter.wait_registered(started)
        except LaunchRefused as refusal:
            print(f"\n  {STATUS_ICONS['error']} {RED}{refusal}{RESET}\n")
            return refusal.code
        print(f"Pesquisa {session.alias or session.id} iniciada em segundo plano (PID {session.pid}).")
        return 0
    presence = presence_factory()
    terminal_id = presence.start()
    presence.start_heartbeat()

    async def call() -> Started:
        return await launch(terminal_id, True)

    return await run_foreground(call, presence)


async def start_research(
    prompt: str,
    args: argparse.Namespace,
    *,
    mode: str,
    budget: UsageBudget,
    background: bool,
    starter: SessionStarter | None = None,
    **kwargs: Any,
) -> int:
    """``geminiclaw "tarefa"``: devolve o código de saída do comando."""
    if background and mode == "assisted":
        print(f"\n  {STATUS_ICONS['error']} {RED}{BACKGROUND_ASSISTED_REFUSAL}{RESET}\n")
        return EXIT_ERROR
    starter = starter or SessionStarter()
    sweep_stopped(starter)

    async def launch(terminal_id: str | None, foreground: bool) -> Started:
        return await starter.start_new(
            prompt, mode=mode, budget=budget, args=args, terminal_id=terminal_id, foreground=foreground,
            memory_policy=MEMORY_POLICY_FAIL,
        )

    return await _run(starter, launch, background=background, **kwargs)


async def resume_research(
    session_id: str,
    args: argparse.Namespace,
    *,
    mode: str | None,
    budget: UsageBudget,
    background: bool = False,
    starter: SessionStarter | None = None,
    **kwargs: Any,
) -> int:
    """``geminiclaw resume --session <id>``: retoma a partir do checkpoint, em nova sessão com orçamento novo."""
    if background and mode == "assisted":
        print(f"\n  {STATUS_ICONS['error']} {RED}{BACKGROUND_ASSISTED_REFUSAL}{RESET}\n")
        return EXIT_ERROR
    starter = starter or SessionStarter()
    sweep_stopped(starter)

    async def launch(terminal_id: str | None, foreground: bool) -> Started:
        return await starter.start_resume(
            session_id, mode=mode, budget=budget, args=args, terminal_id=terminal_id, foreground=foreground,
            memory_policy=MEMORY_POLICY_FAIL,
        )

    return await _run(starter, launch, background=background, **kwargs)


async def continue_project(
    project_id: str,
    args: argparse.Namespace,
    *,
    mode: str | None,
    budget: UsageBudget,
    background: bool = False,
    starter: SessionStarter | None = None,
    **kwargs: Any,
) -> int:
    """``geminiclaw continue --project <id>``: retoma a sessão mais recente do projeto."""
    from src.knowledge.errors import GraphStoreError
    from src.knowledge.projects import validate_project_id
    from src.session.resume import ResumeError, select_session_for_project

    starter = starter or SessionStarter()
    sweep_stopped(starter)
    try:
        pid = validate_project_id(project_id)
        session_id = select_session_for_project(starter.manager, pid)
    except (GraphStoreError, ResumeError) as exc:
        print(f"\n  {STATUS_ICONS['error']} {RED}{exc}{RESET}\n")
        return EXIT_ERROR
    args = argparse.Namespace(**{**vars(args), "project": pid})
    return await resume_research(
        session_id, args, mode=mode, budget=budget, background=background, starter=starter, **kwargs
    )
