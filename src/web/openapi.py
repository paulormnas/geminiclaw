"""Exporta o OpenAPI da API (``uv run python -m src.web.openapi``) para ``frontend/openapi.json``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.web.app import create_app
from src.web.settings import WebSettings

SCHEMA_PATH = Path("frontend/openapi.json")


def build_schema() -> dict[str, object]:
    settings = WebSettings(
        host="127.0.0.1", port=8765, password_hash="$argon2id$exemplo", allowed_hosts=("127.0.0.1",),
        allowed_origins=("http://127.0.0.1:8765",), cookie_secure=False, session_idle_minutes=60, session_max_hours=12,
        max_sessions=10, login_max_failures=5, login_window_seconds=300, login_lock_seconds=300,
        static_dir=Path("frontend/dist"),
    )
    from src.web import app as app_module

    original = app_module.PasswordVerifier
    app_module.PasswordVerifier = lambda _hash: None  # type: ignore[assignment,misc]
    try:
        return create_app(settings).openapi()
    finally:
        app_module.PasswordVerifier = original  # type: ignore[misc]


def dump(schema: dict[str, object]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(dump(build_schema()), encoding="utf-8")
    print(f"Escrito {SCHEMA_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
