"""Projeto arquivado recusa nova pesquisa e retomada no REPL (spec: Projeto arquivado recusa pesquisa)."""

import pytest

from src.cli.project_session import ProjectFlowError, resolve_project
from src.knowledge import projects
from src.knowledge.graph_store import InMemoryGraphStore

pytestmark = pytest.mark.unit


def test_nova_pesquisa_em_projeto_arquivado_e_recusada() -> None:
    store = InMemoryGraphStore()
    pid = projects.create_project(store, "Iris", "Classificar")
    projects.update_project(store, pid, status="arquivado")
    with pytest.raises(ProjectFlowError, match="desarquive para explorar"):
        resolve_project(store, "prompt", project_arg=pid)


def test_desarquivado_volta_a_aceitar() -> None:
    store = InMemoryGraphStore()
    pid = projects.create_project(store, "Iris", "Classificar")
    projects.update_project(store, pid, status="arquivado")
    projects.update_project(store, pid, status="pausado")
    assert resolve_project(store, "prompt", project_arg=pid) == (pid, False)


def test_list_projects_filtra_arquivado() -> None:
    store = InMemoryGraphStore()
    pid = projects.create_project(store, "Iris", "Classificar")
    projects.update_project(store, pid, status="arquivado")
    assert [p.projeto_id for p in projects.list_projects(store, "arquivado")] == [pid]
    assert projects.list_projects(store, "ativo") == []
