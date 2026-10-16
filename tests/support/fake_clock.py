"""Relógio injetável dos testes de v18.7 (sem ``time-machine``: o relógio é passado, não substituído globalmente).

``now()`` é o instante em segundos desde a época (como ``time.time``), ``monotonic()`` avança junto, ``sleep()`` e
``asleep()`` apenas avançam o relógio (nunca esperam de verdade) e ``advance()`` o avança sem dormir.
"""

from __future__ import annotations

import datetime


class FakeClock:
    """Relógio manual: o tempo só passa quando o teste o avança."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self._now = float(start)
        self._monotonic = 0.0

    def now(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += seconds
        self._monotonic += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    async def asleep(self, seconds: float) -> None:
        self.advance(seconds)

    def iso(self, offset: float = 0.0) -> str:
        """Instante atual (mais ``offset`` segundos) em ISO 8601 UTC."""
        return datetime.datetime.fromtimestamp(self._now + offset, datetime.timezone.utc).isoformat()
