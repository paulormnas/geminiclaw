"""Batimento da sessão em thread dedicada (v18-research-continuity, achado I-5).

O batimento **não** depende do laço de eventos: um laço parado (disco lento, leitura bloqueante, banco
reiniciando) não faz a sessão viva parecer obsoleta. Se, mesmo assim, outro processo a marcou ``interrompida``
(o batimento é recusado), a thread reafirma ``active`` e limpa o ``motivo_parada`` herdado.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from src.logger import get_logger

logger = get_logger(__name__)


class SessionHeartbeat:
    """Chama ``beat`` a cada ``interval`` segundos numa thread daemon até ``stop()``."""

    def __init__(
        self,
        beat: Callable[[], bool],
        reassert: Callable[[], bool] | None = None,
        *,
        interval: float,
        name: str = "geminiclaw-heartbeat",
    ) -> None:
        self._beat = beat
        self._reassert = reassert
        self._interval = max(float(interval), 0.01)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.reasserted = 0

    def start(self) -> "SessionHeartbeat":
        """Inicia a thread."""
        self._thread.start()
        return self

    def stop(self) -> None:
        """Para a thread (não bloqueia além de uma volta do batimento)."""
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if self._beat():
                    continue
                logger.warning("Batimento recusado: a sessão foi marcada obsoleta; tentando reafirmar")
                if self._reassert is not None and self._reassert():
                    self.reasserted += 1
                    logger.warning("Sessão reafirmada como ativa (falso positivo de obsolescência)")
            except Exception as exc:  # noqa: BLE001 - falha de batimento nunca derruba a pesquisa
                logger.warning("Batimento da sessão falhou", extra={"error": type(exc).__name__})
