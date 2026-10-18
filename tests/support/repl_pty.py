"""REPL com armazenamento em memória para os testes em pseudo-terminal (``python -m tests.support.repl_pty``).

Roda o ``Repl`` de produção (entrada real do terminal, ``Console`` real) com presença em memória, sem banco nem processo
de sessão. ``GC_NOTIFY_AFTER=N`` agenda uma notificação assíncrona (como a da varredura de sessões paradas) N segundos
depois de abrir, para o teste de redesenho do prompt.
"""

from __future__ import annotations

import os
import threading
import time

from src.cli.repl import Console, Repl, run_with_prompt_interrupt
from src.cli.terminal_consult import ConsultOutcome
from src.session.events import Event
from src.session.presence import TerminalPresence
from tests.support.fake_gate import FakeGate
from tests.support.session_fakes import FakeSessionManager, InMemoryPresenceStore
from tests.support.starter_world import BUDGET, args, make_starter


class ScriptedReader:
    """Leitor de eventos roteirizado: entrega um evento ``plano_aprovado`` da sessão ``iris-01`` ``after`` segundos
    depois de criado (``GC_EVENT_AFTER``); o resto é vazio."""

    def __init__(self, after: float) -> None:
        self._at = time.time() + after
        self._sent = False

    def last_id(self) -> int:
        return 0

    def since(self, last_id: int, *, session_ids=None, limit: int = 200) -> list[Event]:
        if self._sent or time.time() < self._at:
            return []
        self._sent = True
        resumo = os.environ.get("GC_EVENT_SUMMARY", "plano 2 aprovado: 5 subtarefas, 3 hipóteses")
        return [Event(1, "sess-iris", 1, os.environ.get("GC_EVENT_TYPE", "plano_aprovado"), "2026-10-18T10:00:00Z",
                      resumo, {})]

    def tail(self, session_id: str, n: int) -> list[Event]:
        return []


async def main() -> int:
    import pathlib
    import tempfile

    manager = FakeSessionManager()
    session = manager.add("sess-iris", "active", {"mode": "auto"})
    session.alias, session.pid = "iris-01", os.getpid()
    console = Console()
    starter, _ = make_starter(pathlib.Path(tempfile.mkdtemp()), manager=manager)
    repl = Repl(
        mode="auto", explicit_mode=None, budget=BUDGET, args=args(), starter=starter, manager=manager,
        presence=TerminalPresence("repl", store=InMemoryPresenceStore(), pid_alive=lambda pid: True),
        console=console, sweep_interval=3600, recover=lambda s: None, gate=FakeGate(), reminder_interval=3600,
        reader=ScriptedReader(float(os.environ["GC_EVENT_AFTER"])) if "GC_EVENT_AFTER" in os.environ else ScriptedReader(1e9),
        events_interval=0.2, costs_fn=lambda ids: {},
        consult_fn=lambda pergunta, session_id: ConsultOutcome(
            resposta=os.environ.get("GC_CONSULT_ANSWER", "RESPOSTA-SIMULADA") + f" [{pergunta}]"
        ),
    )
    if repl.open() is not None:
        return 1
    after = float(os.environ.get("GC_NOTIFY_AFTER", "0"))
    if after:
        threading.Timer(after, lambda: console.notify("AVISO-ASSINCRONO: a pesquisa x-01 parou")).start()
    await repl.review_unfinished()
    try:
        await repl.loop()
    finally:
        repl.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_with_prompt_interrupt(main))
