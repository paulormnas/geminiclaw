"""Configuração do servidor web (``WEB_*``), exigida só quando ``src.web`` inicia (design §4)."""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import src.config  # noqa: F401  (importar carrega o .env)
from src.utils.configuration_error import ConfigurationError

LOOPBACK_NAMES = frozenset({"127.0.0.1", "::1", "localhost"})
PASSWORD_HINT = "uv run python -m src.web.password"


@dataclass(frozen=True)
class WebSettings:
    """Valores validados do servidor web."""

    host: str
    port: int
    password_hash: str
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]
    cookie_secure: bool
    session_idle_minutes: int
    session_max_hours: int
    max_sessions: int
    login_max_failures: int
    login_window_seconds: int
    login_lock_seconds: int
    static_dir: Path
    in_container: bool = False

    @property
    def cookie_name(self) -> str:
        return "__Host-gc_session" if self.cookie_secure else "gc_session"


def _int(env: Mapping[str, str], key: str, default: int, minimum: int, maximum: int | None = None) -> int:
    raw = env.get(key, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ConfigurationError(f"'{key}' deve ser um inteiro; valor inválido.") from None
    if value < minimum or (maximum is not None and value > maximum):
        faixa = f">= {minimum}" if maximum is None else f"entre {minimum} e {maximum}"
        raise ConfigurationError(f"'{key}' deve ser {faixa}.")
    return value


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("true", "1", "t", "y", "yes")


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _is_loopback_name(name: str) -> bool:
    return name.lower() in LOOPBACK_NAMES


def _check_bind_host(host: str, *, in_container: bool) -> None:
    if in_container:
        return
    if not _is_loopback_name(host):
        raise ConfigurationError(
            f"'WEB_HOST={host}' não é loopback. O servidor só escuta em 127.0.0.1, ::1 ou localhost; para acesso "
            "remoto use `tailscale serve` (ADR 027 §4.1)."
        )
    if host.lower() == "localhost":
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as exc:
            raise ConfigurationError(f"'WEB_HOST=localhost' não resolve: {exc}") from None
        for info in infos:
            if not ipaddress.ip_address(info[4][0]).is_loopback:
                raise ConfigurationError("'WEB_HOST=localhost' resolve para endereço que não é loopback.")


def load_web_settings(env: Mapping[str, str] | None = None) -> WebSettings:
    """Lê e valida ``WEB_*``.

    Raises:
        ConfigurationError: Valor inválido, hash ausente, host fora do loopback ou cookie inseguro com nome da tailnet.
    """
    if env is None:
        env = os.environ
    in_container = _bool(env, "WEB_IN_CONTAINER", False) and Path("/.dockerenv").exists()
    host = env.get("WEB_HOST", "127.0.0.1").strip()
    _check_bind_host(host, in_container=in_container)
    port = _int(env, "WEB_PORT", 8765, 1024, 65535)
    password_hash = env.get("WEB_PASSWORD_HASH", "").strip()
    if not password_hash:
        raise ConfigurationError(f"'WEB_PASSWORD_HASH' ausente. Gere o hash com `{PASSWORD_HINT}` e ponha no .env.")
    if not password_hash.startswith("$argon2id$"):
        raise ConfigurationError(f"'WEB_PASSWORD_HASH' deve começar com $argon2id$ (gere com `{PASSWORD_HINT}`).")
    allowed_hosts = _csv(env.get("WEB_ALLOWED_HOSTS", "127.0.0.1,localhost"))
    if not allowed_hosts:
        raise ConfigurationError("'WEB_ALLOWED_HOSTS' não pode ser vazia.")
    cookie_secure = _bool(env, "WEB_COOKIE_SECURE", False)
    if not cookie_secure and any(not _is_loopback_name(h) for h in allowed_hosts):
        raise ConfigurationError(
            "'WEB_ALLOWED_HOSTS' tem nome fora do loopback (tailnet): defina WEB_COOKIE_SECURE=true "
            "(o acesso pela tailnet é sempre HTTPS pelo `tailscale serve`)."
        )
    raw_origins = env.get("WEB_ALLOWED_ORIGINS", "").strip()
    if raw_origins:
        allowed_origins = _csv(raw_origins)
    elif cookie_secure:
        allowed_origins = tuple(f"https://{h}" for h in allowed_hosts if not _is_loopback_name(h)) + tuple(
            f"http://{h}:{port}" for h in allowed_hosts if _is_loopback_name(h)
        )
    else:
        allowed_origins = tuple(f"http://{h}:{port}" for h in allowed_hosts)
    return WebSettings(
        host=host,
        port=port,
        password_hash=password_hash,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        cookie_secure=cookie_secure,
        session_idle_minutes=_int(env, "WEB_SESSION_IDLE_MINUTES", 60, 1),
        session_max_hours=_int(env, "WEB_SESSION_MAX_HOURS", 12, 1),
        max_sessions=_int(env, "WEB_MAX_SESSIONS", 10, 1),
        login_max_failures=_int(env, "WEB_LOGIN_MAX_FAILURES", 5, 1),
        login_window_seconds=_int(env, "WEB_LOGIN_WINDOW_SECONDS", 300, 1),
        login_lock_seconds=_int(env, "WEB_LOGIN_LOCK_SECONDS", 300, 1),
        static_dir=Path(env.get("WEB_STATIC_DIR", "frontend/dist")),
        in_container=in_container,
    )
