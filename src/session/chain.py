"""Cadeia de sessões de uma pesquisa (``continues_session_id``), da sessão à raiz (v18.7-background-sessions §6.1)."""

from __future__ import annotations

from typing import Any


def chain_session_ids(session_manager: Any, session_id: str, limit: int = 200) -> list[str]:
    """A sessão e os antecessores da cadeia, da mais nova à mais antiga (ciclos e cadeias longas são cortados)."""
    ids: list[str] = []
    current: str | None = session_id
    while current and current not in ids and len(ids) < limit:
        ids.append(current)
        session = session_manager.get(current)
        nxt = (session.payload or {}).get("continues_session_id") if session is not None else None
        current = nxt if isinstance(nxt, str) else None
    return ids
