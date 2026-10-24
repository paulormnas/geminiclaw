"""Fixtures da web: aplicação com relógio simulado, grafo em memória e sessões vivas controláveis."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from src.knowledge.graph_store import InMemoryGraphStore
from src.web.app import create_app
from src.web.deps import LiveSession
from src.web.settings import WebSettings

PASSWORD = "uma-senha-de-teste-longa"
ORIGIN = "http://127.0.0.1:8765"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_settings(tmp_path: Path, **overrides: object) -> WebSettings:
    base = WebSettings(
        host="127.0.0.1",
        port=8765,
        password_hash=PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD),
        allowed_hosts=("127.0.0.1", "localhost"),
        allowed_origins=(ORIGIN, "http://localhost:8765"),
        cookie_secure=False,
        session_idle_minutes=60,
        session_max_hours=12,
        max_sessions=10,
        login_max_failures=5,
        login_window_seconds=300,
        login_lock_seconds=300,
        static_dir=tmp_path / "dist",
    )
    return replace(base, **overrides)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store() -> InMemoryGraphStore:
    return InMemoryGraphStore()


@pytest.fixture
def live() -> dict[str, list[LiveSession]]:
    return {}


@pytest.fixture
def make_client(tmp_path, clock, store, live):
    def build(**overrides: object) -> TestClient:
        app = create_app(
            make_settings(tmp_path, **overrides),
            store_factory=lambda: store,
            live_sessions=lambda pid: live.get(pid, []),
            clock=clock,
        )
        return TestClient(app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False)

    return build


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def auth(client) -> dict[str, str]:
    """Faz login e devolve os cabeçalhos de uma requisição que muda estado."""
    response = client.post("/api/session/login", json={"senha": PASSWORD}, headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}
