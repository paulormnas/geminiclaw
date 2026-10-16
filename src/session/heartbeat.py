"""Batimento da sessão em thread dedicada (v18-research-continuity, achado I-5).

O batimento **não** depende do laço de eventos: um laço parado (disco lento, leitura bloqueante, banco
reiniciando) não faz a sessão viva parecer obsoleta. Se, mesmo assim, outro processo a marcou ``interrompida``
(o batimento é recusado), a thread reafirma ``active`` e limpa o ``motivo_parada`` herdado.
"""

from __future__ import annotations

import asyncio
import datetime
import threading
import time
from collections.abc import Callable

from src.logger import get_logger

logger = get_logger(__name__)


class LoopTick:
    """Último sinal do laço de eventos (v18.7-background-sessions §1.8).

    Uma tarefa ``asyncio`` atualiza um instante a cada ``interval`` segundos. A thread do batimento lê esse instante
    e o grava em ``loop_beat_at``: o batimento segue independente do laço (um laço lento não apaga o batimento), mas
    quem confere vê há quanto tempo o laço não dá sinal.
    """

    def __init__(self, interval: float, *, clock: Callable[[], float] = time.time) -> None:
        self._interval = max(float(interval), 0.01)
        self._clock = clock
        self.last = clock()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> "LoopTick":
        """Inicia a tarefa no laço corrente (deve ser chamado de dentro de uma corrotina)."""
        self.last = self._clock()
        self._task = asyncio.get_running_loop().create_task(self._run(), name="geminiclaw-loop-tick")
        return self

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            self.last = self._clock()

    def stop(self) -> None:
        """Cancela a tarefa; seguro a partir de outra thread."""
        task = self._task
        if task is not None and not task.done():
            task.get_loop().call_soon_threadsafe(task.cancel)

    def age(self) -> float:
        """Segundos desde o último sinal."""
        return max(self._clock() - self.last, 0.0)

    def iso(self) -> str:
        """Último sinal em ISO 8601 (UTC)."""
        return datetime.datetime.fromtimestamp(self.last, datetime.timezone.utc).isoformat()


class SessionHeartbeat:
    """Chama ``beat`` a cada ``interval`` segundos numa thread daemon até ``stop()``.

    Se o batimento é recusado e a reafirmação também, ``is_lost`` diz se a causa é a sessão ter sido continuada por
    outra: nesse caso ``on_lost`` é chamado uma vez e a thread termina (o processo antigo se encerra sem gravar nada).
    """

    def __init__(
        self,
        beat: Callable[[], bool],
        reassert: Callable[[], bool] | None = None,
        *,
        interval: float,
        name: str = "geminiclaw-heartbeat",
        tick: LoopTick | None = None,
        is_lost: Callable[[], bool] | None = None,
        on_lost: Callable[[], None] | None = None,
    ) -> None:
        self._beat = beat
        self._reassert = reassert
        self._tick = tick
        self._is_lost = is_lost
        self._on_lost = on_lost
        self.lost = False
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
        if self._tick is not None:
            self._tick.stop()
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
                elif self._is_lost is not None and self._is_lost():
                    self.lost = True
                    logger.error("Sessão continuada por outra: este processo deixa de executá-la")
                    if self._on_lost is not None:
                        self._on_lost()
                    return
            except Exception as exc:  # noqa: BLE001 - falha de batimento nunca derruba a pesquisa
                logger.warning("Batimento da sessão falhou", extra={"error": type(exc).__name__})
