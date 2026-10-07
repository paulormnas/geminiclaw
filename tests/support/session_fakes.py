"""Gerenciador de sessões em memória para os testes de continuidade (sem PostgreSQL)."""

from __future__ import annotations

import datetime
import threading
import uuid
from typing import Any

from src.session import Session


def _now(delta: float = 0.0) -> str:
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=delta)).isoformat()


class FakeSessionManager:
    """Mesma interface pública de ``SessionManager``, em memória."""

    def __init__(self) -> None:
        self.rows: dict[str, Session] = {}
        self._lock = threading.Lock()

    def add(self, session_id: str, status: str, payload: dict[str, Any], *, agent_id: str = "orchestrator",
            updated_delta: float = 0.0) -> Session:
        sess = Session(session_id, agent_id, status, _now(-1000), _now(updated_delta), dict(payload))
        self.rows[session_id] = sess
        return sess

    def create(self, agent_id: str, session_id: str | None = None) -> Session:
        sid = session_id or str(uuid.uuid4())
        return self.add(sid, "active", {}, agent_id=agent_id)

    def get(self, session_id: str) -> Session | None:
        return self.rows.get(session_id)

    def update(self, session_id: str, status: str | None = None, payload: dict | None = None) -> Session:
        sess = self.rows[session_id]
        if status is not None:
            sess.status = status
        if payload is not None:
            sess.payload = dict(payload)
        sess.updated_at = _now()
        return sess

    def close(self, session_id: str) -> None:
        self.update(session_id, status="closed")

    def heartbeat(self, session_id: str) -> bool:
        sess = self.rows.get(session_id)
        if sess is None or sess.status != "active":
            return False
        sess.updated_at = _now()
        return True

    def mark_stale(self, stale_seconds: float) -> list[Session]:
        cutoff = _now(-stale_seconds)
        out = []
        for sess in self.rows.values():
            if sess.agent_id == "orchestrator" and sess.status == "active" and sess.updated_at < cutoff:
                sess.status = "interrompida"
                sess.payload = {**sess.payload, "motivo_parada": "interrompida"}
                out.append(sess)
        return out

    def find_continuation(self, session_id: str) -> Session | None:
        found = [s for s in self.rows.values() if s.payload.get("continues_session_id") == session_id]
        return sorted(found, key=lambda s: s.created_at)[-1] if found else None

    def list_by_project(self, project_id: str, limit: int = 20) -> list[Session]:
        found = [
            s for s in self.rows.values()
            if s.agent_id == "orchestrator" and s.payload.get("project_id") == project_id
        ]
        return sorted(found, key=lambda s: s.created_at, reverse=True)[:limit]

    def claim_continuation(self, source_id: str, new_id: str, expected: str | None = None) -> bool:
        with self._lock:  # modela a atomicidade do UPDATE condicional
            sess = self.rows.get(source_id)
            if sess is None:
                return False
            current = sess.payload.get("continued_by")
            if (expected is None and current is not None) or (expected is not None and current != expected):
                return False
            sess.payload = {**sess.payload, "continued_by": new_id}
            return True

    def release_continuation(self, source_id: str, new_id: str) -> bool:
        with self._lock:
            sess = self.rows.get(source_id)
            if sess is None or sess.payload.get("continued_by") != new_id:
                return False
            sess.payload = {k: v for k, v in sess.payload.items() if k != "continued_by"}
            return True

    def reassert_active(self, session_id: str) -> bool:
        with self._lock:
            sess = self.rows.get(session_id)
            if sess is None or sess.status != "interrompida":
                return False
            sess.status = "active"
            sess.payload = {k: v for k, v in sess.payload.items() if k != "motivo_parada"}
            sess.updated_at = _now()
            return True
