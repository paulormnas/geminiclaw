"""Modelos Pydantic da API (entrada e saída)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProjectStatus = Literal["ativo", "pausado", "concluido", "arquivado"]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    senha: str = Field(min_length=1, max_length=1024)


class LoginOut(BaseModel):
    csrf_token: str
    expira_em: float


class SessionOut(BaseModel):
    autenticado: bool
    expira_em: float
    csrf_token: str


class ProjectItem(BaseModel):
    projeto_id: str
    titulo: str
    status: str
    criado_em: str


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: str
    objetivo: str
    dominios: list[str] = Field(default_factory=list, max_length=20)


class ProjectCreated(BaseModel):
    projeto_id: str


class ProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: str | None = None
    objetivo: str | None = None
    status: ProjectStatus | None = None


class ProblemSummary(BaseModel):
    problema_id: str
    resumo: str
    status: str


class ProjectDetailOut(BaseModel):
    projeto_id: str
    titulo: str
    objetivo: str
    status: str
    criado_em: str
    dominios: list[str]
    problema: ProblemSummary | None
    n_sessoes: int
    n_hipoteses: int


class ErrorOut(BaseModel):
    erro: str
    mensagem: str = ""
    campo: str | None = None
