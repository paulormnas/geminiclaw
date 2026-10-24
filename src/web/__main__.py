"""``uv run python -m src.web``: sobe a interface em ``WEB_HOST:WEB_PORT`` (só loopback, ADR 027 §4.1)."""

from __future__ import annotations

import sys

import uvicorn

from src.utils.configuration_error import ConfigurationError
from src.web.app import create_app
from src.web.settings import load_web_settings


def main() -> int:
    try:
        settings = load_web_settings()
        app = create_app(settings)
    except ConfigurationError as exc:
        print(f"Configuração inválida: {exc}", file=sys.stderr)
        return 1
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning", server_header=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
