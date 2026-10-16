"""Terminal falso em processo próprio (``python -m tests.support.presence_process``): abre a presença de um REPL, imprime
o ``terminal_id`` e fica batendo até receber um sinal (os testes o matam com ``SIGKILL`` para simular a queda)."""

from __future__ import annotations

import sys
import time

from src.session.presence import TIPO_REPL, TerminalPresence

if __name__ == "__main__":
    presence = TerminalPresence(sys.argv[1] if len(sys.argv) > 1 else TIPO_REPL)
    print(presence.start(), flush=True)
    presence.start_heartbeat()
    time.sleep(600)
