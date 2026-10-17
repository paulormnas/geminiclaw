"""Subcomando ``geminiclaw project new|list|show|use|objective`` (v17-research-project).

Operações tipadas e determinísticas sobre o grafo, com autor ``pesquisador`` e sem LLM.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from src.knowledge import projects
from src.knowledge.errors import GraphStoreError
from src.knowledge.problem import ProblemDraftError


def _default_drafter() -> Callable[..., Any]:
    """Redator do rascunho: o papel ``researcher`` pelo roteador de modelos (ADR 017), resolvido uma vez."""
    import asyncio

    from src.agents.researcher.agent import draft_problem
    from src.llm.session import bind_session_routing, build_session_routing

    bind_session_routing(asyncio.run(build_session_routing()))
    return draft_problem


def _confirm_problem(
    store: Any,
    projeto_id: str,
    *,
    drafter: Callable[..., Any] | None,
    interactive: bool | None,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], Any],
) -> int:
    """``geminiclaw project confirm <id>``: mesmo fluxo da sessão (rascunho, edição, gate, confirmação)."""
    import asyncio

    from src.cli.project_session import ProjectFlowError, ensure_confirmed_problem, is_interactive

    detail = projects.get_project(store, projeto_id)
    if detail.problema is not None:
        title = detail.problema.properties.get("titulo")
        output_fn(f"O projeto {detail.projeto_id} já tem um Problema confirmado: {title}")
        return 0
    try:
        confirmed = asyncio.run(
            ensure_confirmed_problem(
                store, detail.projeto_id, detail.objetivo, None,
                drafter=drafter or _default_drafter(),
                interactive=is_interactive() if interactive is None else interactive,
                input_fn=input_fn, output_fn=output_fn,
            )
        )
    except ProjectFlowError as exc:
        output_fn(f"Erro: {exc}")
        return 1
    output_fn(f"Problema do projeto {confirmed.projeto_id} confirmado.")
    return 0


def handle_project_command(
    argv: list[str],
    store: Any | None = None,
    *,
    config_dir: Path | None = None,
    output_fn: Callable[[str], Any] = print,
    input_fn: Callable[[str], str] = input,
    drafter: Callable[..., Any] | None = None,
    interactive: bool | None = None,
) -> int:
    """Trata ``geminiclaw project new|list|show|use|objective``.

    Args:
        argv: Argumentos após ``project``.
        store: ``GraphStore`` a usar (padrão: o grafo de produção); injetável em testes.
        config_dir: Diretório do projeto padrão (padrão: ``~/.config/geminiclaw``).
        output_fn: Saída de texto.
        input_fn: Leitura interativa (``project confirm``).
        drafter: Redator do rascunho do Problema (testes injetam um dublê; padrão: papel ``researcher``).
        interactive: Força o estado interativo (testes); padrão: ``stdin`` e ``stdout`` são TTY.

    Returns:
        Código de saída (0 em sucesso).
    """
    parser = argparse.ArgumentParser(prog="geminiclaw project", description="Projetos de pesquisa.")
    sub = parser.add_subparsers(dest="action", required=True)
    new_p = sub.add_parser("new", help="Cria um projeto.")
    new_p.add_argument("--titulo", required=True)
    new_p.add_argument("--objetivo", required=True)
    new_p.add_argument("--dominio", action="append", default=[], metavar="TERMO")
    list_p = sub.add_parser("list", help="Lista projetos.")
    list_p.add_argument("--status", choices=["ativo", "pausado", "concluido"], default=None)
    sub.add_parser("show", help="Exibe um projeto.").add_argument("projeto_id")
    sub.add_parser("use", help="Define o projeto padrão das próximas sessões.").add_argument("projeto_id")
    unl_p = sub.add_parser(
        "unlimited",
        help="Marca (--on) ou desmarca (--off) o projeto para o modo sem limite (a execução pede confirmação).",
    )
    unl_p.add_argument("projeto_id")
    unl_group = unl_p.add_mutually_exclusive_group(required=True)
    unl_group.add_argument("--on", action="store_true")
    unl_group.add_argument("--off", action="store_true")
    obj_p = sub.add_parser(
        "objective", help="Política ao atingir o objetivo (--ao-atingir) ou declara a cobertura atingida (--atingido)."
    )
    obj_p.add_argument("projeto_id")
    obj_group = obj_p.add_mutually_exclusive_group(required=True)
    obj_group.add_argument("--ao-atingir", choices=["parar", "perguntar", "continuar"], dest="ao_atingir")
    obj_group.add_argument("--atingido", action="store_true")
    sub.add_parser(
        "confirm", help="Redige o rascunho do Problema e o confirma, sem iniciar uma sessão (exige terminal)."
    ).add_argument("projeto_id")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    try:
        if store is None:
            from src.knowledge.factory import open_graph_store

            store = open_graph_store()
        if args.action == "new":
            projeto_id = projects.create_project(store, args.titulo, args.objetivo, args.dominio)
            output_fn(f"Projeto criado: {projeto_id}")
        elif args.action == "list":
            items = projects.list_projects(store, args.status)
            if not items:
                output_fn("Nenhum projeto.")
            for item in items:
                output_fn(f"{item.projeto_id}  {item.status}  {item.titulo}")
        elif args.action == "show":
            detail = projects.get_project(store, args.projeto_id)
            output_fn(f"Projeto: {detail.projeto_id}\nTítulo: {detail.titulo}\nStatus: {detail.status}")
            output_fn(f"Objetivo: {detail.objetivo}")
            output_fn(f"Domínios: {'; '.join(detail.dominios) or '-'}")
            output_fn(f"Sessões: {detail.n_sessoes} | Hipóteses: {detail.n_hipoteses}")
            if detail.problema is None:
                output_fn("Problema: sem problema confirmado (será pedido na próxima sessão interativa).")
            else:
                crit = detail.problema.properties.get("criterio_sucesso") or {}
                output_fn(f"Problema confirmado: {detail.problema.properties.get('titulo')}")
                output_fn(f"Resumo: {detail.problema.properties.get('resumo')}")
                output_fn(f"Critério de sucesso: {crit}")
        elif args.action == "use":
            detail = projects.get_project(store, args.projeto_id)
            projects.set_default_project(detail.projeto_id, config_dir)
            output_fn(f"Projeto padrão: {detail.projeto_id} ({detail.titulo})")
        elif args.action == "confirm":
            return _confirm_problem(
                store, args.projeto_id, drafter=drafter, interactive=interactive, input_fn=input_fn,
                output_fn=output_fn,
            )
        elif args.action == "objective":
            if args.atingido:
                projects.declare_objective_reached(store, args.projeto_id)
                output_fn(f"Projeto {args.projeto_id}: objetivo de cobertura declarado atingido (marco gravado).")
            else:
                projects.set_objective_policy(store, args.projeto_id, args.ao_atingir)
                output_fn(f"Projeto {args.projeto_id}: ao atingir o objetivo, a sessão vai {args.ao_atingir}.")
        elif args.action == "unlimited":
            pid = projects.set_unlimited_mode(store, args.projeto_id, bool(args.on))
            output_fn(
                f"Projeto {pid}: modo sem limite {'MARCADO' if args.on else 'desmarcado'}."
                + (" Cada sessão ainda pedirá a confirmação digitada." if args.on else "")
            )
    except (GraphStoreError, ProblemDraftError, RuntimeError, OSError) as exc:
        output_fn(f"Erro: {exc}")
        return 1
    return 0
