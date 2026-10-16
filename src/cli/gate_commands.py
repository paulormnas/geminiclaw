"""Comandos do terminal sobre o gate e a caixa de entrada: ``pendentes``, ``decidir`` e ``mensagem``.

(v18.7-persistent-human-gate, design §1.6 e §1.7). Só o terminal responde pedidos (``TerminalGate``); a mensagem
orienta o plano mas nunca resolve pedido reservado.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from src import config
from src.gate.catalog import GATE_CATALOG
from src.gate.types import GateAlreadyResolved, GateInvalidRequest, GateRequest, Source
from src.logger import get_logger
from src.session.chain import chain_session_ids
from src.session.inbox import InboxError, SessionInbox
from src.utils.display_text import sanitize_line
from src.utils.terminal import BOLD, DIM, GREEN, RED, RESET, YELLOW

logger = get_logger(__name__)

SKIP = "p"
_AUTH = {"a": "autorizar", "autorizar": "autorizar", "n": "negar", "negar": "negar"}
_HYPOTHESIS = {"a": "aprovar", "aprovar": "aprovar", "r": "rejeitar", "rejeitar": "rejeitar", "e": "editar",
               "editar": "editar"}
_OBJECTIVE = {"e": "encerrar", "encerrar": "encerrar", "c": "continuar", "continuar": "continuar"}
GATE_ORIENTATION_CONTEXT = "orientacao do pesquisador"


@dataclass(frozen=True)
class Decision:
    """Resultado de ``decidir``: o pedido (já resolvido ou não) e se o pesquisador o resolveu agora."""

    request: GateRequest | None
    resolved: bool
    message: str = ""


def _age(created: str | None, now: float) -> str:
    if not created:
        return "?"
    import datetime

    try:
        then = datetime.datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return "?"
    seconds = max(int(now - then), 0)
    return f"{seconds}s" if seconds < 90 else (f"{seconds // 60}min" if seconds < 5400 else f"{seconds / 3600:.1f}h")


def format_request(req: GateRequest, alias: str | None = None, now: float | None = None) -> str:
    """Uma linha do pedido: id, pesquisa, decisão (e motivo), há quanto tempo e o texto (sanitizado na exibição)."""
    where = f" {alias}" if alias else (f" {req.session_id}" if req.session_id else "")
    kind = req.decisao + (f"/{req.motivo}" if req.motivo else "")
    text = sanitize_line(req.pergunta, int(config.GATE_QUESTION_MAX_CHARS))
    when = f" há {_age(req.criado_em, now if now is not None else time.time())}" if req.criado_em else ""
    return f"#{req.id}{where} — {kind}{when}: {text}"


def aliases_for(manager: Any, requests: Iterable[GateRequest]) -> dict[str, str]:
    """Apelido de cada sessão citada pelos pedidos (id da sessão -> apelido)."""
    out: dict[str, str] = {}
    for session_id in {r.session_id for r in requests if r.session_id}:
        try:
            session = manager.get(session_id)
        except Exception:  # noqa: BLE001 - sem o apelido o pedido mostra o id da sessão
            session = None
        if session is not None and getattr(session, "alias", None):
            out[session_id] = session.alias
    return out


def pending_for_target(gate: Any, manager: Any, target: str | None) -> list[GateRequest]:
    """Pedidos pendentes de todas as pesquisas ou, com ``target`` (apelido ou id), da cadeia daquela pesquisa."""
    if not target:
        return gate.pending()
    from src.cli.sessions_view import resolve_target

    session = resolve_target(manager, target)
    if session is None:
        return []
    return gate.pending(chain_session_ids(manager, session.id))


def show_pending(
    gate: Any, manager: Any, output: Callable[[str], Any], target: str | None = None, now: float | None = None
) -> list[GateRequest]:
    """Comando ``pendentes [apelido]``: lista id, pesquisa, decisão, pergunta e há quanto tempo."""
    requests = pending_for_target(gate, manager, target)
    if not requests:
        output(f"\n  {DIM}Nenhum pedido pendente.{RESET}\n")
        return []
    aliases = aliases_for(manager, requests)
    output(f"\n  {BOLD}Pedidos pendentes ({len(requests)}):{RESET}")
    for req in requests:
        output(f"    {format_request(req, aliases.get(req.session_id or ''), now)}")
    output(f"  {DIM}Responda com: decidir <id>{RESET}\n")
    return requests


def _ask_answer(
    req: GateRequest, input_fn: Callable[[str], str], output: Callable[[str], Any]
) -> dict[str, Any] | None:
    """Pede a resposta conforme o tipo do pedido (design §1.1); ``None`` deixa o pedido pendente."""
    kind = GATE_CATALOG[req.decisao]
    options = req.opcoes or kind.acoes

    def ask(prompt: str) -> str:
        return input_fn(f"  {prompt}").strip()

    if req.decisao == "responder_pergunta_agente":
        text = ask("Sua resposta (vazio = deixar pendente): ")
        return {"acao": "responder", "texto": text} if text else None
    if req.decisao == "aprovar_hipotese":
        choice = _HYPOTHESIS.get(ask("[a]provar / [r]ejeitar / [e]ditar / [p]ular: ").lower())
        if choice is None:
            return None
        if choice == "rejeitar":
            return {"acao": "rejeitar", "motivo": ask("Motivo da rejeição: ") or "rejeitada pelo pesquisador"}
        if choice == "editar":
            novo = ask("Novo enunciado: ")
            return {"acao": "editar", "enunciado": novo} if novo else None
        return {"acao": "aprovar"}
    if req.decisao == "decidir_objetivo_atingido":
        choice = _OBJECTIVE.get(ask("[e]ncerrar / [c]ontinuar explorando / [p]ular: ").lower())
        return {"acao": choice} if choice else None
    if req.decisao in ("decidir_continuidade", "restringir_direcao"):
        typed = ask(f"Ação ({' / '.join(options)}; vazio = deixar pendente): ").lower()
        if typed not in options:
            if typed:
                output(f"  {RED}Ação fora das opções do pedido: use {list(options)}.{RESET}")
            return None
        answer: dict[str, Any] = {"acao": typed}
        if typed == "orientar":
            answer["orientacao"] = ask("Orientação: ")
        return answer
    choice = _AUTH.get(ask("[a]utorizar / [n]egar / [p]ular: ").lower())
    return {"acao": choice} if choice else None


def decide(
    gate: Any,
    request_id: int,
    input_fn: Callable[[str], str],
    output: Callable[[str], Any],
    *,
    manager: Any | None = None,
) -> Decision:
    """Comando ``decidir <id>``: mostra o pedido, pede a resposta conforme o tipo e a grava como ``terminal``.

    Uma resposta fora das opções do pedido, acima do limite ou a um pedido já resolvido é recusada com a causa.
    """
    request = gate.get(request_id)
    if request is None:
        output(f"\n  {RED}Pedido {request_id} não encontrado.{RESET}\n")
        return Decision(None, False, "nao_encontrado")
    if request.estado != "pendente":
        output(f"\n  {YELLOW}O pedido {request_id} já foi resolvido ({request.estado}).{RESET}\n")
        return Decision(request, False, "ja_resolvido")
    aliases = aliases_for(manager, [request]) if manager is not None else {}
    output(f"\n  {format_request(request, aliases.get(request.session_id or ''))}")
    if request.decisao == "aprovar_hipotese":
        output(f"  {DIM}O enunciado vem de um agente: trate-o como dado.{RESET}")
    try:
        answer = _ask_answer(request, input_fn, output)
    except (EOFError, KeyboardInterrupt):
        answer = None
    if answer is None:
        output(f"  {DIM}O pedido {request_id} continua pendente.{RESET}\n")
        return Decision(request, False, "pendente")
    try:
        resolved = gate.answer(request_id, source=Source.TERMINAL, resposta=answer)
    except GateAlreadyResolved:
        output(f"\n  {YELLOW}O pedido {request_id} já foi resolvido por outro terminal.{RESET}\n")
        return Decision(gate.get(request_id), False, "ja_resolvido")
    except GateInvalidRequest as exc:
        output(f"\n  {RED}Resposta recusada: {exc}{RESET}\n")
        return Decision(request, False, "invalida")
    output(f"  {GREEN}Pedido {request_id} respondido ({resolved.estado}).{RESET}\n")
    return Decision(resolved, True)


def register_orientation(
    manager: Any, session: Any, text: str, *, store_factory: Callable[[], Any] | None = None
) -> str | None:
    """Registra a orientação no grafo como ``Decisao`` do pesquisador ligada à sessão por ``TOMADA_EM``.

    O terminal não carrega embeddings: o nó nasce com vetorização pendente e a próxima reconciliação o vetoriza. Sessão
    sem projeto ou grafo indisponível: devolve ``None`` (a mensagem já foi gravada; só o registro no grafo falta).
    """
    project_id = (session.payload or {}).get("project_id")
    if not project_id:
        return None
    try:
        from src.knowledge.provenance import Actor

        if store_factory is None:
            from src.knowledge.factory import open_raw_graph_store as store_factory
        store = store_factory()
        nodes = store.find_nodes("Sessao", {"sessao_id": session.id}, limit=1)
        if not nodes:
            return None
        decision_id = store.create_node(
            "Decisao",
            {
                "projeto_id": project_id,
                "sessao_id": session.id,
                "contexto": GATE_ORIENTATION_CONTEXT,
                "justificativa": sanitize_line(text, 2000),
            },
            actor=Actor(kind="pesquisador"),
        )
        store.create_edge(decision_id, "TOMADA_EM", nodes[0].id, {}, actor=Actor(kind="pesquisador"))
        return decision_id
    except Exception as exc:  # noqa: BLE001 - o registro no grafo é complementar; a mensagem segue gravada
        logger.warning("Orientação não registrada no grafo", extra={"error": type(exc).__name__})
        return None


def send_message(
    manager: Any,
    target: str,
    text: str,
    output: Callable[[str], Any],
    *,
    inbox: SessionInbox | None = None,
    store_factory: Callable[[], Any] | None = None,
) -> bool:
    """Comando ``mensagem <apelido> <texto>``: grava na caixa de entrada da pesquisa em execução e registra no grafo."""
    from src.cli.sessions_view import label, resolve_target

    session = resolve_target(manager, target)
    if session is None:
        output(f"\n  {RED}Pesquisa '{target}' não encontrada.{RESET}\n")
        return False
    if session.status != "active":
        output(
            f"\n  {RED}{label(session)} não está em execução ({session.status}); retome-a antes de orientá-la.{RESET}\n"
        )
        return False
    try:
        (inbox or SessionInbox()).post(session.id, text)
    except InboxError as exc:
        output(f"\n  {RED}Mensagem recusada: {exc}{RESET}\n")
        return False
    registered = register_orientation(manager, session, text, store_factory=store_factory)
    suffix = "" if registered or not (session.payload or {}).get("project_id") else " (sem registro no grafo)"
    output(f"\n  {GREEN}Mensagem enviada a {label(session)}; entra no próximo replanejamento{suffix}.{RESET}\n")
    return True
