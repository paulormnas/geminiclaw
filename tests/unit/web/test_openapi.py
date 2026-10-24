"""O esquema OpenAPI versionado em ``frontend/openapi.json`` não pode divergir da API (design §5)."""

import pytest

from src.web.openapi import SCHEMA_PATH, build_schema, dump

pytestmark = pytest.mark.unit


def test_esquema_versionado_esta_atualizado() -> None:
    assert SCHEMA_PATH.read_text(encoding="utf-8") == dump(build_schema()), (
        "frontend/openapi.json desatualizado: rode `uv run python -m src.web.openapi` "
        "e `pnpm --dir frontend gen:api`."
    )
