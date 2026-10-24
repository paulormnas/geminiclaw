"""Middleware de segurança: Host, Origin, sessão, CSRF e cabeçalhos (ADR 027 §4, design §3)."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.web.auth import SessionStore
from src.web.settings import WebSettings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOGIN_PATH = "/api/session/login"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def error_response(status: int, erro: str, mensagem: str = "", **extra: object) -> Response:
    body = {"erro": erro, "mensagem": mensagem, **extra}
    return Response(json.dumps(body, ensure_ascii=False), status_code=status, media_type="application/json")


class SecurityMiddleware:
    """ASGI puro: valida antes de qualquer rota e acrescenta os cabeçalhos a toda resposta."""

    def __init__(self, app: ASGIApp, settings: WebSettings, sessions: SessionStore) -> None:
        self.app = app
        self.settings = settings
        self.sessions = sessions
        self._hosts = {h.lower() for h in settings.allowed_hosts}
        self._origins = {o.rstrip("/").lower() for o in settings.allowed_origins}

    def _host_ok(self, request: Request) -> bool:
        host = request.headers.get("host", "").strip().lower()
        if host.startswith("["):
            name = host[1 : host.find("]")] if "]" in host else host
        else:
            name = host.rsplit(":", 1)[0] if ":" in host else host
        return name in self._hosts

    def _origin_ok(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        if not origin:
            return False
        parts = urlsplit(origin)
        normalized = f"{parts.scheme}://{parts.netloc}".lower()
        return normalized in self._origins

    def _decide(self, request: Request) -> Response | None:
        if not self._host_ok(request):
            return error_response(400, "host_invalido", "Host não permitido.")
        path = request.url.path
        unsafe = request.method not in SAFE_METHODS
        if unsafe and not self._origin_ok(request):
            return error_response(403, "origem_invalida", "Origem não permitida.")
        if not path.startswith("/api/") or (path == LOGIN_PATH and request.method == "POST"):
            return None
        session = self.sessions.get(request.cookies.get(self.settings.cookie_name))
        if session is None:
            return error_response(401, "nao_autenticado", "Entre com a senha.")
        request.state.web_session = session
        if unsafe and not self.sessions.csrf_ok(session, request.headers.get("x-csrf-token")):
            return error_response(403, "csrf_invalido", "Token CSRF ausente ou inválido.")
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        denied = self._decide(request)
        is_api = request.url.path.startswith("/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {k.lower() for k, _ in headers}
                extra = [
                    (b"content-security-policy", CSP.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                if is_api:
                    extra.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers + [h for h in extra if h[0] not in names]}
            await send(message)

        if denied is not None:
            await denied(scope, receive, send_with_headers)
            return
        await self.app(scope, receive, send_with_headers)
