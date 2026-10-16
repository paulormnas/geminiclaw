"""REPL com armazenamento em memória para os testes em pseudo-terminal (``python -m tests.support.repl_pty``).

Roda o ``Repl`` de produção (entrada real do terminal, ``Console`` real) com presença em memória, sem banco nem processo
de sessão. ``GC_NOTIFY_AFTER=N`` agenda uma notificação assíncrona (como a da varredura de sessões paradas) N segundos
depois de abrir, para o teste de redesenho do prompt.
"""

from __future__ import annotations

import os
import threading

from src.cli.repl import Console, Repl, run_with_prompt_interrupt
from src.session.presence import TerminalPresence
from tests.support.fake_gate import FakeGate
from tests.support.session_fakes import FakeSessionManager, InMemoryPresenceStore
from tests.support.starter_world import BUDGET, args, make_starter


async def main() -> int:
    import pathlib
    import tempfile

    manager = FakeSessionManager()
    console = Console()
    starter, _ = make_starter(pathlib.Path(tempfile.mkdtemp()), manager=manager)
    repl = Repl(
        mode="auto", explicit_mode=None, budget=BUDGET, args=args(), starter=starter, manager=manager,
        presence=TerminalPresence("repl", store=InMemoryPresenceStore(), pid_alive=lambda pid: True),
        console=console, sweep_interval=3600, recover=lambda s: None, gate=FakeGate(), reminder_interval=3600,
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
