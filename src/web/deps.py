"""Dependências da aplicação (injetadas por ``create_app``; trocáveis nos testes)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from src.knowledge.graph_store import GraphStore
from src.web.auth import LoginThrottle, PasswordVerifier, SessionStore, WebSession
from src.web.settings import WebSettings


@dataclass(frozen=True)
class LiveSession:
    """Sessão de pesquisa em execução (para recusar concluir/arquivar o projeto, design §8)."""

    session_id: str
    alias: str | None


class LazyStore:
    """Abre o ``GraphStore`` na primeira necessidade (a API de login e os estáticos não dependem do banco)."""

    def __init__(self, factory: Callable[[], GraphStore]) -> None:
        self._factory = factory
        self._store: GraphStore | None = None
        self._lock = threading.Lock()

    def get(self) -> GraphStore:
        with self._lock:
            if self._store is None:
                self._store = self._factory()
            return self._store


@dataclass
class AppState:
    settings: WebSettings
    verifier: PasswordVerifier
    sessions: SessionStore
    throttle: LoginThrottle
    store: LazyStore
    live_sessions: Callable[[str], list[LiveSession]]


def app_state(request: Request) -> AppState:
    return request.app.state.web  # type: ignore[no-any-return]


def current_session(request: Request) -> WebSession:
    return request.state.web_session  # type: ignore[no-any-return]
