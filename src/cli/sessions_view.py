"""Lista e perguntas sobre as pesquisas no REPL (v18.7-background-sessions, design §1.7).

``sessions`` lista as pesquisas em execução e as não finalizadas; ao abrir, o REPL mostra o resumo desde a última vez
e pergunta, para cada pesquisa não finalizada, se o pesquisador quer retomar, manter ou encerrar.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

from src.report.operation_metrics import describe_stop_reason
from src.session.continuity import CheckpointError, read_checkpoint, resolve_session_dir
from src.session.manager import Session
from src.session.states import FINISHED_STATUSES, UNFINISHED_STATUSES
from src.utils.terminal import BOLD, DIM, GREEN, RESET, YELLOW

ANSWER_RESUME = "r"
ANSWER_KEEP = "m"
ANSWER_CLOSE = "e"
_ANSWERS = {
    "r": ANSWER_RESUME, "retomar": ANSWER_RESUME,
    "m": ANSWER_KEEP, "manter": ANSWER_KEEP,
    "e": ANSWER_CLOSE, "encerrar": ANSWER_CLOSE,
}


def _age(iso: str | None, now: float) -> str:
    if not iso:
        return "?"
    try:
        then = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return "?"
    seconds = max(int(now - then), 0)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}min"
    return f"{seconds / 3600:.1f}h" if seconds < 172800 else f"{seconds // 86400}d"


def label(session: Session) -> str:
    """Apelido da pesquisa (ou o id, em sessões anteriores aos apelidos)."""
    return session.alias or session.id


def stop_text(session: Session) -> str:
    motivo = (session.payload or {}).get("motivo_parada")
    return describe_stop_reason(motivo) or motivo or "n/d"


def progress_text(session: Session, base_dir: Any) -> str:
    """Último estado do checkpoint em uma linha (concluídas/pendentes), ou vazio sem checkpoint utilizável."""
    try:
        checkpoint, _ = read_checkpoint(resolve_session_dir(base_dir, session.id), expected_session_id=session.id)
    except (CheckpointError, OSError):
        return ""
    done = len(checkpoint.concluidas())
    return f"checkpoint {checkpoint.estado}: {done} de {len(checkpoint.subtarefas)} subtarefa(s) concluída(s)"


def describe(session: Session, base_dir: Any, now: float) -> list[str]:
    """Linhas da pergunta de retomada: apelido, modo, motivo e último estado."""
    mode = (session.payload or {}).get("mode", "?")
    head = f"{BOLD}{label(session)}{RESET} — modo {mode}, {session.status} há {_age(session.updated_at, now)}"
    lines = [head, f"    {DIM}{session.resumo or (session.payload or {}).get('prompt', '')[:160]}{RESET}"]
    lines.append(f"    motivo: {stop_text(session)}")
    progress = progress_text(session, base_dir)
    if progress:
        lines.append(f"    {progress}")
    return lines


def show_researches(manager: Any, output: Callable[[str], Any], now: float) -> list[Session]:
    """Comando ``sessions``: pesquisas em execução e não finalizadas (apelido, modo, estado, PID, tempo, resumo)."""
    sessions = manager.list_orchestrator(["active", *UNFINISHED_STATUSES])
    if not sessions:
        output(f"\n  {DIM}Nenhuma pesquisa em execução ou por terminar.{RESET}\n")
        return []
    output(f"\n  {BOLD}Pesquisas:{RESET}")
    for s in sessions:
        pid = f", PID {s.pid}" if s.pid and s.status == "active" else ""
        output(
            f"    {BOLD}{label(s)}{RESET}  {(s.payload or {}).get('mode', '?')}  {s.status}{pid}  "
            f"há {_age(s.updated_at, now)}  {DIM}{s.resumo or ''}{RESET}"
        )
    output("")
    return sessions


def summary_since(manager: Any, last_end: float | None, output: Callable[[str], Any]) -> list[Session]:
    """Resumo das pesquisas alteradas desde o fim da última presença de REPL; devolve as não finalizadas, por ordem de
    atualização. Sem presença anterior não há resumo, mas as não finalizadas ainda são devolvidas."""
    unfinished = manager.list_orchestrator(UNFINISHED_STATUSES)
    if last_end is not None:
        since = datetime.datetime.fromtimestamp(last_end, datetime.timezone.utc).isoformat()
        finished = manager.list_orchestrator(FINISHED_STATUSES, updated_after=since)
        running = manager.list_orchestrator(["active"], updated_after=since)
        if finished or running or unfinished:
            output(f"\n  {BOLD}Desde a última vez:{RESET}")
        for s in finished:
            output(f"    {GREEN}concluída{RESET} {label(s)}: {stop_text(s)}")
        for s in running:
            output(f"    em execução {label(s)} (PID {s.pid or '?'})")
    return unfinished


def ask_unfinished(
    session: Session, base_dir: Any, input_fn: Callable[[str], str], output: Callable[[str], Any], now: float
) -> str:
    """Pergunta "[r]etomar / [m]anter / [e]ncerrar" para uma pesquisa não finalizada; padrão e erros: manter."""
    output("")
    for line in describe(session, base_dir, now):
        output(f"  {line}")
    while True:
        try:
            raw = input_fn(f"  {YELLOW}[r]etomar / [m]anter / [e]ncerrar?{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ANSWER_KEEP
        if not raw:
            return ANSWER_KEEP
        if raw in _ANSWERS:
            return _ANSWERS[raw]
        output(f"  {DIM}Responda r, m ou e.{RESET}")


def resolve_target(manager: Any, text: str) -> Session | None:
    """Pesquisa pelo apelido (a folha da cadeia) ou pelo id da sessão."""
    text = (text or "").strip()
    if not text:
        return None
    found = manager.find_by_alias(text)
    if found is not None:
        return found
    session = manager.get(text)
    return session if session is not None and session.agent_id == "orchestrator" else None
