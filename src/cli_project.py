"""Subcomando ``geminiclaw project new|list|show|use`` (v17-research-project).

Operações tipadas e determinísticas sobre o grafo, com autor ``pesquisador`` e sem LLM.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from src.knowledge import projects
from src.knowledge.errors import GraphStoreError
from src.knowledge.problem import ProblemDraftError


def handle_project_command(
    argv: list[str],
    store: Any | None = None,
    *,
    config_dir: Path | None = None,
    output_fn: Callable[[str], Any] = print,
) -> int:
    """Trata ``geminiclaw project new|list|show|use``.

    Args:
        argv: Argumentos após ``project``.
        store: ``GraphStore`` a usar (padrão: o grafo de produção); injetável em testes.
        config_dir: Diretório do projeto padrão (padrão: ``~/.config/geminiclaw``).
        output_fn: Saída de texto.

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
    except (GraphStoreError, ProblemDraftError, RuntimeError, OSError) as exc:
        output_fn(f"Erro: {exc}")
        return 1
    return 0
