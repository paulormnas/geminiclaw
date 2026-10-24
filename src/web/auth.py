"""Senha, sessões em memória e bloqueio de login (ADR 027 §4, design §3). Relógio injetável para os testes."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from src.utils.configuration_error import ConfigurationError
from src.web.settings import PASSWORD_HINT, WebSettings

Clock = Callable[[], float]


class PasswordVerifier:
    """Verifica a senha contra o hash argon2id (tempo constante); hash malformado impede a inicialização."""

    def __init__(self, password_hash: str) -> None:
        self._hasher = PasswordHasher()
        try:
            self._hasher.verify(password_hash, "\0")
        except VerifyMismatchError:
            pass  # hash válido, senha errada: esperado
        except (VerificationError, InvalidHashError):
            raise ConfigurationError(f"'WEB_PASSWORD_HASH' malformado; gere outro com `{PASSWORD_HINT}`.") from None
        self._hash = password_hash

    def verify(self, password: str) -> bool:
        try:
            return self._hasher.verify(self._hash, password)
        except (VerificationError, InvalidHashError):
            return False


@dataclass
class WebSession:
    token: str
    csrf: str
    criado_em: float
    ultimo_uso: float


class SessionsExhausted(Exception):
    """``WEB_MAX_SESSIONS`` atingido: o login novo é recusado, nunca derruba uma sessão existente."""


class SessionStore:
    """Sessões só em memória: reiniciar o servidor as encerra."""

    def __init__(self, settings: WebSettings, clock: Clock = time.time) -> None:
        self._idle = settings.session_idle_minutes * 60
        self._max_age = settings.session_max_hours * 3600
        self._max = settings.max_sessions
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, WebSession] = {}

    def _purge(self, now: float) -> None:
        dead = [
            t
            for t, s in self._sessions.items()
            if now - s.ultimo_uso > self._idle or now - s.criado_em > self._max_age
        ]
        for token in dead:
            del self._sessions[token]

    def create(self) -> WebSession:
        now = self._clock()
        with self._lock:
            self._purge(now)
            if len(self._sessions) >= self._max:
                raise SessionsExhausted
            session = WebSession(secrets.token_urlsafe(32), secrets.token_urlsafe(32), now, now)
            self._sessions[session.token] = session
            return session

    def get(self, token: str | None) -> WebSession | None:
        """Sessão válida (e renova o uso), ou ``None``."""
        if not token:
            return None
        now = self._clock()
        with self._lock:
            self._purge(now)
            session = self._sessions.get(token)
            if session is not None:
                session.ultimo_uso = now
            return session

    def delete(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def expires_at(self, session: WebSession) -> float:
        return min(session.ultimo_uso + self._idle, session.criado_em + self._max_age)

    @staticmethod
    def csrf_ok(session: WebSession, presented: str | None) -> bool:
        return bool(presented) and hmac.compare_digest(session.csrf, presented or "")


class LoginThrottle:
    """Bloqueio global (um usuário só): N falhas na janela bloqueiam por ``lock`` segundos, inclusive a senha certa."""

    def __init__(self, max_failures: int, window: int, lock: int, clock: Clock = time.time) -> None:
        self._max, self._window, self._lock_s, self._clock = max_failures, window, lock, clock
        self._failures: deque[float] = deque()
        self._locked_until = 0.0
        self._mutex = threading.Lock()

    def retry_in(self) -> int:
        """Segundos até poder tentar de novo (0 = liberado)."""
        now = self._clock()
        with self._mutex:
            return max(0, int(self._locked_until - now + 0.999)) if self._locked_until > now else 0

    def record_failure(self) -> None:
        now = self._clock()
        with self._mutex:
            self._failures.append(now)
            while self._failures and now - self._failures[0] > self._window:
                self._failures.popleft()
            if len(self._failures) >= self._max:
                self._locked_until = now + self._lock_s
                self._failures.clear()

    def record_success(self) -> None:
        with self._mutex:
            self._failures.clear()
