"""Login, logout e estado da sessão (ADR 027 §4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from src.logger import get_logger
from src.web.auth import SessionsExhausted, WebSession
from src.web.deps import AppState, app_state, current_session
from src.web.models import ErrorOut, LoginIn, LoginOut, SessionOut

logger = get_logger(__name__)
router = APIRouter(prefix="/api/session", tags=["sessão"])


@router.post("/login", response_model=LoginOut, responses={401: {"model": ErrorOut}, 429: {"model": ErrorOut}})
def login(body: LoginIn, state: AppState = Depends(app_state)) -> Response:
    wait = state.throttle.retry_in()
    if wait > 0:
        return JSONResponse(
            {"erro": "bloqueado", "mensagem": "Muitas tentativas.", "tentar_em_segundos": wait}, status_code=429
        )
    if not state.verifier.verify(body.senha):
        state.throttle.record_failure()
        logger.warning("Login recusado")
        return JSONResponse({"erro": "credenciais_invalidas", "mensagem": "Senha incorreta."}, status_code=401)
    try:
        session = state.sessions.create()
    except SessionsExhausted:
        return JSONResponse(
            {"erro": "sessoes_esgotadas", "mensagem": "Máximo de sessões ativas; saia de uma antes."}, status_code=429
        )
    state.throttle.record_success()
    settings = state.settings
    response = JSONResponse({"csrf_token": session.csrf, "expira_em": state.sessions.expires_at(session)})
    response.set_cookie(
        settings.cookie_name,
        session.token,
        max_age=settings.session_max_hours * 3600,
        path="/",
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
    )
    logger.info("Login aceito")
    return response


@router.post("/logout", status_code=204)
def logout(
    request: Request, session: WebSession = Depends(current_session), state: AppState = Depends(app_state)
) -> Response:
    state.sessions.delete(session.token)
    response = Response(status_code=204)
    response.delete_cookie(state.settings.cookie_name, path="/")
    return response


@router.get("", response_model=SessionOut, responses={401: {"model": ErrorOut}})
def whoami(session: WebSession = Depends(current_session), state: AppState = Depends(app_state)) -> SessionOut:
    return SessionOut(autenticado=True, expira_em=state.sessions.expires_at(session))
