"""Subcomando ``geminiclaw opportunities list|approve|reject`` (v18-hypothesis-loop, design §7).

Comandos determinísticos, sem LLM, com autor ``pesquisador`` e auditoria no grafo. Aprovar ou rejeitar uma oportunidade
é decisão reservada ao pesquisador: o ``HumanGate`` registra o pedido com a origem ``cli`` e o ``GraphStore`` recusa a
mesma escrita por agente ou pelo orquestrador (``validate_human_only``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from src.human_gate import HumanGate
from src.knowledge import opportunities, projects
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_views import sanitize_text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geminiclaw opportunities", description="Decisão do pesquisador sobre oportunidades documentadas."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    list_p = sub.add_parser("list", help="Lista oportunidades do projeto.")
    list_p.add_argument("--project", default=None, metavar="ID", help="Projeto (padrão: o de `project use`).")
    list_p.add_argument("--status", default=None, choices=[
        "documentada", "aprovada", "rejeitada", "em_investigacao", "concluida"])
    approve_p = sub.add_parser(
        "approve", help="Aprova uma oportunidade documentada (ela passa a poder ser investigada)."
    )
    approve_p.add_argument("id")
    approve_p.add_argument("--project", default=None, metavar="ID")
    approve_p.add_argument("--motivo", default=None, help="Motivo da aprovação (opcional).")
    approve_p.add_argument(
        "--yes", action="store_true",
        help="Aprova sem pedir confirmação (uso não interativo; só pelo pesquisador, nunca por agente).",
    )
    reject_p = sub.add_parser("reject", help="Rejeita uma oportunidade documentada (sem apagar).")
    reject_p.add_argument("id")
    reject_p.add_argument("--project", default=None, metavar="ID")
    reject_p.add_argument("--motivo", required=True, help="Motivo da rejeição.")
    return parser


def handle_opportunities_command(
    argv: list[str],
    store: Any | None = None,
    *,
    config_dir: Path | None = None,
    output_fn: Callable[[str], Any] = print,
    gate: HumanGate | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> int:
    """Trata ``geminiclaw opportunities list|approve|reject``.

    Args:
        argv: Argumentos após ``opportunities``.
        store: ``GraphStore`` a usar (padrão: o grafo de produção); injetável em testes.
        config_dir: Diretório do projeto padrão.
        output_fn: Saída de texto.
        gate: ``HumanGate`` (padrão: o do processo).
        input_fn: Leitura da confirmação de ``approve`` (padrão: ``input`` no terminal interativo; sem terminal
            interativo e sem ``--yes`` a aprovação é recusada).

    Returns:
        Código de saída (0 em sucesso).
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        if store is None:
            from src.knowledge.factory import open_graph_store

            store = open_graph_store()
        project_id = projects.validate_project_id(args.project) if args.project else projects.get_default_project(
            config_dir
        )
        if args.action == "list":
            if project_id is None:
                output_fn("Erro: informe --project <id> ou rode `geminiclaw project use <id>`.")
                return 1
            items = opportunities.list_opportunities(store, project_id, args.status)
            if not items:
                output_fn("Nenhuma oportunidade.")
            for item in items:
                output_fn(f"{item.id}  {item.status}  {item.enunciado}")
            return 0
        approve = args.action == "approve"
        if approve and not args.yes and not _confirm_approval(
            store, args.id, project_id, output_fn, input_fn
        ):
            return 1
        node = opportunities.authorize_and_decide(
            store, args.id, approve=approve, motivo=args.motivo, project_id=project_id, gate=gate
        )
        verbo = "aprovada" if approve else "rejeitada"
        output_fn(f"Oportunidade {verbo}: {node.id} (autor: pesquisador).")
    except (GraphStoreError, RuntimeError, OSError) as exc:
        output_fn(f"Erro: {sanitize_text(exc, 400)}")
        return 1
    return 0


def _confirm_approval(
    store: Any, opportunity_id: str, project_id: str | None, output_fn: Callable[[str], Any],
    input_fn: Callable[[str], str] | None,
) -> bool:
    """Mostra o enunciado (saneado) e pede confirmação antes de aprovar; fail-closed sem terminal interativo.

    Oportunidade inexistente, de outro projeto ou já decidida não pede confirmação: a decisão devolve o erro acionável.
    """
    node = store.get_node(opportunity_id)
    if (
        node is None
        or node.label != "Oportunidade"
        or node.properties.get("status") != opportunities.STATUS_DOCUMENTADA
        or (project_id is not None and node.properties.get("projeto_id") != project_id)
    ):
        return True
    if input_fn is None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            output_fn("Erro: aprovar exige confirmação interativa; sem terminal use --yes (decisão do pesquisador).")
            return False
        input_fn = input
    output_fn(f"Oportunidade {node.id}: {sanitize_text(node.properties.get('enunciado', ''), 400)}")
    answer = input_fn("Aprovar esta oportunidade para investigação? [s/N] ")
    if answer.strip().lower() not in ("s", "sim", "y", "yes"):
        output_fn("Aprovação cancelada; nada foi alterado.")
        return False
    return True
