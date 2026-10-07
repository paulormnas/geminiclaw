"""Subcomando ``geminiclaw graph show|node|edit`` (``v17-graph-cli``; ADR 015 §11).

- ``graph show`` e ``graph node``: **visualização** simples, somente leitura, **sem agente e sem LLM**. Usam o grafo
  através de uma fachada somente-leitura (``ReadOnlyGraph``); nenhum provedor de LLM é importado nesse caminho.
- ``graph edit "<pedido>"``: **alteração** sempre pelo Curator, que traduz o pedido em operações PROPOSTAS. A CLI valida
  a seco, mostra a proposta e só aplica depois da confirmação **humana interativa** (terminal real; não existe
  ``--yes`` nem leitura de confirmação de arquivo/pipe), com ``Actor(pesquisador)``. O pesquisador não tem acesso direto
  ao banco: não há comando que execute consulta Cypher/SQL fornecida por ele.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, Callable

from src import config
from src.human_gate import HumanGate, Source, default_gate
from src.knowledge import projects
from src.knowledge.change_proposals import (
    CONFIRM_WORD,
    ApplyError,
    Plan,
    ProposalError,
    apply_plan,
    issue_confirmation,
    render_plan,
)
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_views import (
    FORMATS,
    GraphViewError,
    ReadOnlyGraph,
    load_node_detail,
    load_project_view,
    render_node_detail,
    render_view,
    sanitize_text,
)
from src.knowledge.problem import ProblemDraftError

_ANSWER_APPLY, _ANSWER_CANCEL, _ANSWER_ADJUST = CONFIRM_WORD, "cancelar", "ajustar"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="geminiclaw graph", description="Grafo de conhecimento do projeto.")
    sub = parser.add_subparsers(dest="action", required=True)
    show = sub.add_parser("show", help="Exibe o grafo do projeto (somente leitura, sem LLM).")
    show.add_argument("--project", default=None, metavar="ID", help="Projeto (padrão: o de `project use`).")
    show.add_argument("--label", action="append", default=[], metavar="ROTULO", help="Filtra por rótulo (repetível).")
    show.add_argument("--dominio", default=None, metavar="TERMO", help="Só nós ligados a este domínio.")
    show.add_argument("--status", default=None, help="Filtra por status.")
    show.add_argument("--depth", type=int, default=0, help="Saltos a incluir a partir dos nós filtrados (0 a 3).")
    show.add_argument("--format", choices=FORMATS, default="text", dest="fmt")
    show.add_argument("--offset", type=int, default=0, help="Deslocamento (paginação além do limite).")
    node = sub.add_parser("node", help="Detalha um nó (somente leitura, sem LLM).")
    node.add_argument("node_id")
    node.add_argument("--project", default=None, metavar="ID")
    node.add_argument("--format", choices=("text", "json"), default="text", dest="fmt")
    edit = sub.add_parser("edit", help="Pede ao Curator uma alteração; você confirma antes de aplicar.")
    edit.add_argument("pedido", help="O que alterar, em linguagem natural.")
    edit.add_argument("--project", default=None, metavar="ID")
    return parser


def _resolve_project(project: str | None, config_dir: Path | None) -> str:
    if project is not None:
        return projects.validate_project_id(project)
    default = projects.get_default_project(config_dir)
    if default is None:
        raise GraphViewError("Nenhum projeto ativo: informe --project <id> ou rode `geminiclaw project use <id>`.")
    return default


def _is_interactive() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def _default_provider_factory() -> Callable[[], Any]:
    """Provedor do papel ``curator`` pelo roteador de modelos (ADR 017); só é chamado no ``graph edit``."""

    def factory() -> Any:
        from src.llm.session import bind_session_routing, build_session_routing
        from src.model_router import ModelRouter

        routing = asyncio.run(build_session_routing())
        bind_session_routing(routing)
        return ModelRouter.get_provider("curator")

    return factory


def handle_graph_command(
    argv: list[str],
    store: Any | None = None,
    *,
    config_dir: Path | None = None,
    output_fn: Callable[[str], Any] = print,
    input_fn: Callable[[str], str] = input,
    interactive: bool | None = None,
    provider_factory: Callable[[], Any] | None = None,
    index: Any | None = None,
    gate: HumanGate | None = None,
) -> int:
    """Trata ``geminiclaw graph show|node|edit``.

    Args:
        argv: Argumentos após ``graph``.
        store: ``GraphStore`` a usar (padrão: o grafo de produção); injetável em testes.
        config_dir: Diretório do projeto padrão (padrão: ``~/.config/geminiclaw``).
        output_fn: Saída de texto.
        input_fn: Leitura interativa (terminal).
        interactive: Força o estado interativo (testes); padrão: ``stdin`` e ``stdout`` são TTY.
        provider_factory: Provedor do Curator (testes injetam um dublê; padrão: roteador ADR 017).
        index: Índice semântico (avisos de duplicata e ``similar``); só com ``store`` injetado.
        gate: ``HumanGate`` das decisões reservadas (padrão: o do processo).

    Returns:
        Código de saída (0 em sucesso).
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    def out(text: str) -> None:
        output_fn(text)

    try:
        if args.action == "edit":
            return _edit(args, store, config_dir, out, input_fn, interactive, provider_factory, index, gate)
        project_id = _resolve_project(args.project, config_dir)
        if store is None:
            from src.knowledge.factory import open_raw_graph_store

            store = open_raw_graph_store()  # sem índice: a visualização só lê
        reader = ReadOnlyGraph(store)
        projects.get_project(reader, project_id)  # type: ignore[arg-type]  # só leituras; falha se não existe
        if args.action == "show":
            view = load_project_view(
                reader, project_id, labels=args.label, dominio=args.dominio, status=args.status,
                depth=args.depth, offset=args.offset,
            )
            out(render_view(view, args.fmt))
        else:
            out(render_node_detail(load_node_detail(reader, args.node_id, project_id), args.fmt))
    except (GraphViewError, GraphStoreError, ProblemDraftError, projects.ProjectError, RuntimeError, OSError) as exc:
        out(f"Erro: {sanitize_text(exc, 400)}")
        return 1
    return 0


# ---------------------------------------------------------------------------
# graph edit
# ---------------------------------------------------------------------------


def _ask(input_fn: Callable[[str], str], prompt: str) -> str | None:
    """Lê uma resposta; fim de entrada ou Ctrl-C contam como cancelamento (``None``)."""
    try:
        return input_fn(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _authorize_decisions(plan: Plan, gate: HumanGate, input_fn: Callable[[str], str]) -> bool:
    """Decisões reservadas (``Oportunidade``): autorização adicional, no terminal, pelo ``HumanGate``.

    O prompt identifica o alvo e o novo status; só a resposta ``s`` digitada no terminal autoriza.
    """
    for item in plan.decisions:
        request = gate.request(item.decision or "", item.node_id)
        target = sanitize_text(item.description, 400)
        reply = _ask(input_fn, f"Autoriza a decisão '{item.decision}' (operação {item.index})?\n  {target}\n[s/N] ")
        gate.answer(request.id, source=Source.TERMINAL, approved=reply is not None and reply.lower() in ("s", "sim"))
        if not gate.authorized(request.id):
            return False
    return True


def _edit(
    args: argparse.Namespace,
    store: Any | None,
    config_dir: Path | None,
    out: Callable[[str], Any],
    input_fn: Callable[[str], str],
    interactive: bool | None,
    provider_factory: Callable[[], Any] | None,
    index: Any | None,
    gate: HumanGate | None,
) -> int:
    from agents.curator.edit import CuratorEditor, EditProposal, plan_for

    # 1. Pré-condições, antes de qualquer chamada de LLM.
    if not (_is_interactive() if interactive is None else interactive):
        out(
            "Erro: `graph edit` exige um terminal interativo: a confirmação da alteração é sempre do pesquisador "
            "e não aceita entrada por pipe, arquivo ou opção. Nada foi alterado."
        )
        return 1
    request = args.pedido.strip() if isinstance(args.pedido, str) else ""
    if not request:
        out("Erro: informe o pedido de alteração.")
        return 1
    if len(request) > config.GRAPH_EDIT_MAX_REQUEST_CHARS:
        out(f"Erro: pedido longo demais (máximo {config.GRAPH_EDIT_MAX_REQUEST_CHARS} caracteres).")
        return 1
    project_id = _resolve_project(args.project, config_dir)
    if store is None:
        from src.knowledge.factory import open_knowledge_runtime, open_raw_graph_store

        runtime = open_knowledge_runtime()
        store, index = (runtime.store, runtime.index) if runtime is not None else (open_raw_graph_store(), None)
    projects.get_project(store, project_id)
    gate = gate or default_gate()
    # O provedor é resolvido AQUI (fora do laço assíncrono do Curator): o roteador usa ``asyncio.run`` internamente.
    try:
        provider = (provider_factory or _default_provider_factory())()
    except Exception as exc:  # noqa: BLE001 - sem modelo elegível, nada a propor
        out(f"Erro: modelo do Curator indisponível ({sanitize_text(type(exc).__name__ + ': ' + str(exc), 300)}). "
            "Nada foi alterado.")
        return 1
    editor = CuratorEditor(store, project_id=project_id, provider_factory=lambda: provider, index=index)

    # 2. Rodadas: propor -> validar a seco -> mostrar -> aplicar/cancelar/ajustar.
    feedback: str | None = None
    adjustments: list[str] = []
    previous: EditProposal | None = None
    for round_no in range(1, max(config.GRAPH_EDIT_MAX_ROUNDS, 1) + 1):
        outcome = asyncio.run(editor.propose(request, feedback=feedback, previous=previous))
        plan = plan_for(store, outcome, project_id, index)
        last_round = round_no >= config.GRAPH_EDIT_MAX_ROUNDS
        if plan is None or outcome.proposal is None:
            out(f"Erro: {sanitize_text(outcome.reason or 'sem proposta do Curator', 300)} Nada foi alterado.")
            return 1
        previous = outcome.proposal
        out(render_plan(plan, outcome.proposal.explanation))
        can_apply = plan.ok and bool(plan.items)
        options = [_ANSWER_CANCEL] + ([] if last_round else [_ANSWER_ADJUST])
        if can_apply:
            options.insert(0, _ANSWER_APPLY)
        answer = _ask(input_fn, f"\nResponda {', '.join(repr(o) for o in options)}: ")
        choice = answer if answer is not None else _ANSWER_CANCEL  # resposta EXATA: sem strip nem caixa
        if choice == "" or choice not in options:
            out("Resposta não reconhecida: proposta cancelada. Nada foi alterado.")
            return 1
        if choice == _ANSWER_CANCEL:
            out("Proposta cancelada. Nada foi alterado.")
            return 0
        if choice == _ANSWER_ADJUST:
            raw = _ask(input_fn, "Descreva o ajuste: ")
            text = sanitize_text(raw, config.GRAPH_EDIT_MAX_REQUEST_CHARS) if raw else ""
            if not text:
                out("Ajuste vazio: proposta cancelada. Nada foi alterado.")
                return 0
            feedback = text[: config.GRAPH_EDIT_MAX_REQUEST_CHARS]
            adjustments.append(feedback)
            continue
        return _apply(store, plan, request, gate, input_fn, out, tuple(adjustments))
    out("Limite de rodadas atingido. Nada foi alterado.")
    return 1


def _apply(
    store: Any,
    plan: Plan,
    request: str,
    gate: HumanGate,
    input_fn: Callable[[str], str],
    out: Callable[[str], Any],
    adjustments: tuple[str, ...],
) -> int:
    if not _authorize_decisions(plan, gate, input_fn):
        out("Decisão reservada não autorizada: nada foi alterado.")
        return 1
    try:
        # A confirmação só existe aqui: terminal interativo já verificado e a palavra exata digitada acima.
        confirmation = issue_confirmation(plan, _ANSWER_APPLY, tty=True)
        result = apply_plan(store, plan, request=request, confirmation=confirmation, adjustments=adjustments)
    except ApplyError as exc:
        extra = f" Nós criados mantidos (nada é apagado): {', '.join(exc.kept_created)}." if exc.kept_created else ""
        out(f"Erro: {sanitize_text(exc, 400)}{extra}")
        return 1
    except (ProposalError, GraphStoreError, PermissionError) as exc:
        out(f"Erro: {sanitize_text(exc, 400)} Nada foi alterado.")
        return 1
    ids = ", ".join(f"${k}={sanitize_text(v, 64)}" for k, v in sorted(result.created_ids.items()))
    created = f" IDs criados: {ids}." if ids else ""
    out(f"Alteração aplicada ({result.applied} operação(ões)), com autoria 'pesquisador' e auditoria.{created}")
    return 0
