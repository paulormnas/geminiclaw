"""Acompanhamento das pesquisas no REPL (v18.7-session-events-terminal, design §1.4 e §1.5).

``EventsThread`` lê os eventos novos de ``session_events`` a cada ``SESSION_EVENTS_POLL_SECONDS`` e imprime uma linha
por evento (``[apelido] resumo``) sem apagar o que o pesquisador digita (``Console.notify``). O banco é gravável pelo
processo da sessão, então o terminal **saneia de novo** tudo o que imprime (``sanitize_line``, que remove ESC, C1 e
marcas bidi) e aplica o teto do resumo, sem confiar no saneamento da gravação. Os comandos de ação (``pausar``,
``parar``, ``cancelar``, ``replanejar``) vão à sessão pela caixa de entrada, só quando a pesquisa tem processo vivo.
"""

from __future__ import annotations

import datetime
import threading
from collections.abc import Callable, Iterable
from typing import Any

from src import config
from src.cli.sessions_view import _age
from src.logger import get_logger
from src.session.commands import COMANDOS, codifica
from src.session.events import TIPOS_RESUMO, TIPOS_SILENCIOSO, Event, EventReader
from src.session.inbox import TIPO_COMANDO, InboxError, SessionInbox
from src.utils.display_text import sanitize_line
from src.utils.terminal import BOLD, DIM, GREEN, RED, RESET, YELLOW

logger = get_logger(__name__)

_LINE_MAX = 300


def clean_line(text: Any, limit: int | None = None) -> str:
    """Texto em uma linha, sem sequências de controle, no teto de exibição (nunca confia na gravação)."""
    return sanitize_line(text, min(limit or _LINE_MAX, int(config.SESSION_EVENT_SUMMARY_MAX_CHARS), _LINE_MAX))


def visible(level: str, tipo: str) -> bool:
    """Se o evento aparece no nível de detalhe (``silencioso``, ``resumo`` ou ``detalhado``)."""
    if level == "detalhado":
        return True
    return tipo in (TIPOS_SILENCIOSO if level == "silencioso" else TIPOS_RESUMO)


def format_event(alias: str, event: Event) -> str:
    """``[apelido] resumo``, com apelido e resumo saneados."""
    return f"[{clean_line(alias, 40)}] {clean_line(event.resumo)}"


def _alias_of(manager: Any, cache: dict[str, str], session_id: str) -> str:
    if session_id not in cache:
        try:
            session = manager.get(session_id)
        except Exception:  # noqa: BLE001 - sem o apelido a linha mostra o começo do id
            session = None
        cache[session_id] = (getattr(session, "alias", None) if session is not None else None) or session_id[:8]
    return cache[session_id]


class EventsThread:
    """Consulta periódica dos eventos novos e impressão no REPL.

    Args:
        reader: ``EventReader``.
        manager: ``SessionManager`` (apelidos).
        console: ``Console`` do REPL (``notify`` redesenha o prompt com o texto parcial).
        interval: Segundos entre consultas (``SESSION_EVENTS_POLL_SECONDS``).
        level: Função que devolve o nível de detalhe vigente.
        start_id: Só eventos com ``id`` maior que este são impressos (o REPL abre no fim da tabela).
    """

    def __init__(
        self,
        reader: EventReader,
        manager: Any,
        console: Any,
        interval: float,
        *,
        level: Callable[[], str] = lambda: config.TERMINAL_EVENT_DETAIL,
        start_id: int = 0,
    ) -> None:
        self._reader = reader
        self._manager = manager
        self._console = console
        self._interval = max(interval, 0.05)
        self._level = level
        self.last_id = start_id
        self._aliases: dict[str, str] = {}
        self._following: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="geminiclaw-events", daemon=True)

    def start(self) -> "EventsThread":
        self._thread.start()
        return self

    def follow(self, session_id: str | None) -> None:
        """Mostra todos os eventos da sessão (nível detalhado) até ``follow(None)``."""
        self._following = session_id

    def poll(self) -> int:
        """Imprime os eventos novos conforme o nível; devolve quantos foram impressos. Nunca levanta."""
        try:
            events = self._reader.since(self.last_id)
        except Exception as exc:  # noqa: BLE001 - o acompanhamento nunca derruba o terminal
            logger.warning("Leitura de eventos falhou", extra={"error": type(exc).__name__})
            return 0
        printed = 0
        level = self._level()
        for event in events:
            self.last_id = max(self.last_id, event.id)
            effective = "detalhado" if event.session_id == self._following else level
            if not visible(effective, event.tipo):
                continue
            self._console.notify(format_event(_alias_of(self._manager, self._aliases, event.session_id), event))
            printed += 1
        return printed

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.poll()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)


# --- comandos ----------------------------------------------------------------------------------------------------


def session_costs(session_ids: Iterable[str]) -> dict[str, float]:
    """Custo estimado (US$) por sessão, somando ``token_usage.estimated_cost_usd``; vazio se não houver leitura."""
    ids = list(session_ids)
    if not ids:
        return {}
    try:
        from src.db import get_pool

        with get_pool().connection(timeout=3) as conn:  # sem banco, o comando não espera o tempo padrão do pool
            rows = conn.execute(
                "SELECT execution_id, SUM(estimated_cost_usd) AS custo FROM token_usage "
                "WHERE execution_id = ANY(%s) GROUP BY execution_id",
                (ids,),
            ).fetchall()
        return {r["execution_id"]: float(r["custo"] or 0.0) for r in rows}
    except Exception as exc:  # noqa: BLE001 - sem o custo a linha mostra n/d
        logger.warning("Custo das pesquisas indisponível", extra={"error": type(exc).__name__})
        return {}


def show_overview(
    manager: Any, reader: EventReader, gate: Any, output: Callable[[str], Any], now: float,
    costs_fn: Callable[[Iterable[str]], dict[str, float]] | None = None,
) -> list[Any]:
    """Comando ``pesquisas``: uma linha por pesquisa em execução, por terminar ou terminada nas últimas 24 h, com
    estado, tempo, custo, último evento e pedidos pendentes."""
    from src.cli.sessions_view import label
    from src.session.states import FINISHED_STATUSES, UNFINISHED_STATUSES

    since = datetime.datetime.fromtimestamp(now - 24 * 3600, datetime.timezone.utc).isoformat()
    sessions = list(manager.list_orchestrator(["active", *UNFINISHED_STATUSES]))
    seen = {s.id for s in sessions}
    sessions += [s for s in manager.list_orchestrator(FINISHED_STATUSES, updated_after=since) if s.id not in seen]
    if not sessions:
        output(f"\n  {DIM}Nenhuma pesquisa em execução, por terminar ou terminada nas últimas 24 h.{RESET}\n")
        return []
    costs = (costs_fn or session_costs)(s.id for s in sessions)
    try:
        pending = gate.pending()
    except Exception:  # noqa: BLE001 - sem o gate a coluna fica vazia
        pending = []
    output(f"\n  {BOLD}Pesquisas:{RESET}")
    for s in sessions:
        try:
            last = reader.tail(s.id, 1)
        except Exception:  # noqa: BLE001
            last = []
        waiting = sum(1 for r in pending if r.session_id == s.id)
        cost = costs.get(s.id)
        parts = [
            f"{BOLD}{clean_line(label(s), 40)}{RESET}",
            clean_line((s.payload or {}).get("mode", "?"), 12),
            clean_line(s.status, 32),
            f"há {_age(s.created_at, now)}",
            f"US$ {cost:.2f}".replace(".", ",") if cost is not None else "US$ n/d",
        ]
        if waiting:
            parts.append(f"{YELLOW}{waiting} pedido(s) pendente(s){RESET}")
        line = "  ".join(parts)
        if last:
            line += f"  {DIM}último: {clean_line(last[0].resumo)}{RESET}"
        output(f"    {line}")
    output("")
    return sessions


def show_history(reader: EventReader, session: Any, output: Callable[[str], Any]) -> int:
    """Últimos ``TERMINAL_FOLLOW_HISTORY`` eventos da pesquisa, em nível detalhado."""
    from src.cli.sessions_view import label

    events = reader.tail(session.id, int(config.TERMINAL_FOLLOW_HISTORY))
    output(f"\n  {BOLD}Acompanhando {clean_line(label(session), 40)}{RESET} {DIM}(digite 'voltar' para sair){RESET}")
    for event in events:
        output(f"    {format_event(label(session), event)}")
    if not events:
        output(f"    {DIM}Nenhum evento ainda.{RESET}")
    return len(events)


def _process_alive(session: Any) -> bool:
    """A pesquisa tem processo vivo: ``active`` com PID (no mesmo host, o PID existe de fato)."""
    if session.status != "active" or not session.pid:
        return False
    import os
    import socket

    if session.host and session.host != socket.gethostname():
        return True  # outro host: o terminal não consegue conferir; a varredura de paradas cuida disso
    try:
        os.kill(int(session.pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def send_command(
    manager: Any,
    target: str,
    command: str,
    subtask: str | None,
    output: Callable[[str], Any],
    *,
    inbox: SessionInbox | None = None,
) -> bool:
    """``pausar``, ``parar``, ``cancelar`` e ``replanejar``: grava o comando na caixa de entrada da pesquisa.

    Recusa a pesquisa sem processo vivo, mostrando o estado e sugerindo ``retomar``.
    """
    from src.cli.sessions_view import label, resolve_target

    if command not in COMANDOS:
        output(f"\n  {RED}Comando desconhecido: {clean_line(command, 40)}{RESET}\n")
        return False
    session = resolve_target(manager, target)
    if session is None:
        usage = f"{command} <apelido>" + (" <subtarefa>" if command == "cancelar" else "")
        output(f"\n  {RED}Use: {usage} (pesquisa não encontrada: '{clean_line(target, 40)}'){RESET}\n")
        return False
    name = clean_line(label(session), 40)
    if not _process_alive(session):
        output(
            f"\n  {RED}{name} não tem processo em execução (estado {clean_line(session.status, 32)}); "
            f"use 'retomar {name}'.{RESET}\n"
        )
        return False
    try:
        (inbox or SessionInbox()).post(session.id, codifica(command, subtask), tipo=TIPO_COMANDO)
    except (InboxError, ValueError) as exc:
        output(f"\n  {RED}Comando recusado: {clean_line(exc, 120)}{RESET}\n")
        return False
    output(f"\n  {GREEN}Comando '{command}' enviado a {name}; o resultado aparece nos eventos.{RESET}\n")
    return True
