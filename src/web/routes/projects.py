"""CRUD de projetos, sem exclusão física (ADR 027 §6.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from src.knowledge import projects as project_api
from src.knowledge.problem import ProblemDraftError
from src.knowledge.projects import ProjectDetail, ProjectError
from src.web.deps import AppState, app_state
from src.web.models import (
    ErrorOut,
    ProblemSummary,
    ProjectCreate,
    ProjectCreated,
    ProjectDetailOut,
    ProjectItem,
    ProjectPatch,
)

router = APIRouter(prefix="/api/projects", tags=["projetos"])

_BLOCKING = ("concluido", "pausado", "arquivado")


def _error(status: int, erro: str, mensagem: str, campo: str | None = None, **extra: object) -> JSONResponse:
    body: dict[str, object] = {"erro": erro, "mensagem": mensagem, **extra}
    if campo:
        body["campo"] = campo
    return JSONResponse(body, status_code=status)


def _field_of(message: str) -> str | None:
    if "'titulo'" in message:
        return "titulo"
    if "'objetivo'" in message:
        return "objetivo"
    return None


def _detail(detail: ProjectDetail) -> ProjectDetailOut:
    problem = detail.problema
    return ProjectDetailOut(
        projeto_id=detail.projeto_id,
        titulo=detail.titulo,
        objetivo=detail.objetivo,
        status=detail.status,
        criado_em=detail.criado_em,
        dominios=detail.dominios,
        problema=(
            ProblemSummary(
                problema_id=problem.id,
                resumo=str(problem.properties.get("resumo", "")),
                status=str(problem.properties.get("status", "")),
            )
            if problem
            else None
        ),
        n_sessoes=detail.n_sessoes,
        n_hipoteses=detail.n_hipoteses,
    )


@router.get("", response_model=list[ProjectItem])
def list_(
    status: str | None = Query(default=None),
    incluir_arquivados: bool = Query(default=False),
    state: AppState = Depends(app_state),
) -> list[ProjectItem] | JSONResponse:
    try:
        items = project_api.list_projects(state.store.get(), status)
    except ProjectError as exc:
        return _error(422, "status_invalido", str(exc), "status")
    if status is None and not incluir_arquivados:
        items = [p for p in items if p.status != "arquivado"]
    return [ProjectItem(**vars(p)) for p in items]


@router.post("", status_code=201, response_model=ProjectCreated, responses={422: {"model": ErrorOut}})
def create(body: ProjectCreate, state: AppState = Depends(app_state)) -> ProjectCreated | JSONResponse:
    try:
        pid = project_api.create_project(state.store.get(), body.titulo, body.objetivo, body.dominios)
    except ProblemDraftError as exc:
        return _error(422, "campo_invalido", str(exc), _field_of(str(exc)))
    return ProjectCreated(projeto_id=pid)


@router.get("/{projeto_id}", response_model=ProjectDetailOut, responses={404: {"model": ErrorOut}})
def read(projeto_id: str, state: AppState = Depends(app_state)) -> ProjectDetailOut | JSONResponse:
    try:
        return _detail(project_api.get_project(state.store.get(), projeto_id))
    except ProjectError:
        return _error(404, "projeto_nao_encontrado", "Projeto não encontrado.")


@router.patch(
    "/{projeto_id}",
    response_model=ProjectDetailOut,
    responses={404: {"model": ErrorOut}, 409: {"model": ErrorOut}, 422: {"model": ErrorOut}},
)
def patch(projeto_id: str, body: ProjectPatch, state: AppState = Depends(app_state)) -> ProjectDetailOut | JSONResponse:
    store = state.store.get()
    try:
        current = project_api.get_project(store, projeto_id)
    except ProjectError:
        return _error(404, "projeto_nao_encontrado", "Projeto não encontrado.")
    if body.status in _BLOCKING and body.status != current.status:
        live = state.live_sessions(current.projeto_id)
        if live:
            return _error(
                409,
                "pesquisa_em_execucao",
                "Há pesquisa em execução neste projeto; encerre-a antes.",
                sessoes=[{"session_id": s.session_id, "alias": s.alias} for s in live],
            )
    try:
        updated = project_api.update_project(
            store, projeto_id, titulo=body.titulo, objetivo=body.objetivo, status=body.status
        )
    except ProblemDraftError as exc:
        return _error(422, "campo_invalido", str(exc), _field_of(str(exc)))
    except ProjectError:
        return _error(404, "projeto_nao_encontrado", "Projeto não encontrado.")
    return _detail(updated)
