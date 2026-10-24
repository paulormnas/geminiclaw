"""SPA estática: serve ``WEB_STATIC_DIR`` e devolve ``index.html`` nas rotas do frontend (design §1)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response

BUILD_HINT = "Frontend não compilado: rode `pnpm --dir frontend build`."


def static_router(static_dir: Path) -> APIRouter:
    router = APIRouter(include_in_schema=False)
    root = static_dir.resolve()

    @router.get("/{path:path}")
    def spa(path: str) -> Response:
        index = root / "index.html"
        if not index.is_file():
            return JSONResponse({"erro": "frontend_ausente", "mensagem": BUILD_HINT}, status_code=503)
        if path.startswith("api/"):
            return JSONResponse({"erro": "nao_encontrado", "mensagem": "Rota inexistente."}, status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)

    return router
