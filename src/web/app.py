"""Fábrica da aplicação FastAPI (injetável nos testes)."""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.knowledge.graph_store import GraphStore
from src.logger import get_logger
from src.web.auth import Clock, LoginThrottle, PasswordVerifier, SessionStore
from src.web.deps import AppState, LazyStore, LiveSession
from src.web.routes import projects, session
from src.web.security import SecurityMiddleware
from src.web.settings import WebSettings
from src.web.static import static_router

logger = get_logger(__name__)


def default_store_factory() -> GraphStore:
    from src.knowledge.factory import open_graph_store

    return open_graph_store()


def default_live_sessions(project_id: str) -> list[LiveSession]:
    from src.session.manager import SessionManager
    from src.session.states import STATUS_ACTIVE

    return [
        LiveSession(s.id, s.alias)
        for s in SessionManager().list_by_project(project_id)
        if s.status == STATUS_ACTIVE
    ]


def create_app(
    settings: WebSettings,
    *,
    store_factory: Callable[[], GraphStore] = default_store_factory,
    live_sessions: Callable[[str], list[LiveSession]] = default_live_sessions,
    clock: Clock = time.time,
) -> FastAPI:
    """Monta a aplicação; nada é aberto (banco, grafo) antes da primeira rota que precisa."""
    app = FastAPI(title="GeminiClaw — interface do pesquisador", docs_url=None, redoc_url=None)
    sessions = SessionStore(settings, clock)
    app.state.web = AppState(
        settings=settings,
        verifier=PasswordVerifier(settings.password_hash),
        sessions=sessions,
        throttle=LoginThrottle(
            settings.login_max_failures, settings.login_window_seconds, settings.login_lock_seconds, clock
        ),
        store=LazyStore(store_factory),
        live_sessions=live_sessions,
    )

    @app.exception_handler(Exception)
    async def internal(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Erro interno", extra={"extra": {"tipo": type(exc).__name__, "rota": request.url.path}})
        return JSONResponse({"erro": "interno", "mensagem": "Erro interno."}, status_code=500)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "nao_encontrado", 405: "metodo_nao_permitido"}
        return JSONResponse(
            {"erro": codes.get(exc.status_code, "erro"), "mensagem": "Requisição não atendida."},
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = [str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path")]
        return JSONResponse(
            {"erro": "campo_invalido", "mensagem": "Valor inválido.", "campo": loc[0] if loc else None},
            status_code=422,
        )

    app.include_router(session.router)
    app.include_router(projects.router)
    app.include_router(static_router(settings.static_dir))
    app.add_middleware(SecurityMiddleware, settings=settings, sessions=sessions)
    return app
