"""Comandos ``geminiclaw project objective`` (v18.7-exploration-limits, tarefa 5.5; ``specs/research-project``)."""

from __future__ import annotations

import pytest

from src.cli.project import handle_project_command
from src.knowledge import projects
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.provenance import Actor
from tests.unit.research_project.test_projects import make_draft

pytestmark = pytest.mark.unit


@pytest.fixture
def store() -> InMemoryGraphStore:
    return InMemoryGraphStore()


def confirmed(store, **over) -> tuple[str, str]:
    pid = projects.create_project(store, "P", "Obj", [])
    draft = make_draft(**over)
    problem_id = projects.confirm_problem(store, pid, draft, sentido_metrica="maior_melhor", objective_optional=True)
    return pid, problem_id


def run(store, *argv):
    out: list[str] = []
    code = handle_project_command(list(argv), store, output_fn=out.append)
    return code, "\n".join(out)


def test_mudar_a_politica(store):
    """Scenario: Mudar a política — grava e a auditoria registra o pesquisador."""
    pid, problem_id = confirmed(store)
    assert "ao_atingir_objetivo" not in store.get_node(problem_id).properties["criterio_sucesso"]
    code, out = run(store, "objective", pid, "--ao-atingir", "perguntar")
    assert code == 0 and "perguntar" in out
    assert store.get_node(problem_id).properties["criterio_sucesso"]["ao_atingir_objetivo"] == "perguntar"
    assert [a for a in store.audit_log if a["node_id"] == problem_id][-1]["actor"] == "pesquisador"


def test_politica_invalida_e_recusada_pelo_parser(store):
    pid, _ = confirmed(store)
    assert run(store, "objective", pid, "--ao-atingir", "talvez")[0] != 0


def test_atingido_em_tipo_errado_e_recusado(store):
    """Scenario: Atingido em tipo errado."""
    pid, problem_id = confirmed(store)
    code, out = run(store, "objective", pid, "--atingido")
    assert code == 1 and "cobertura" in out
    assert not store.get_node(problem_id).properties.get("objetivo_atingido")


def test_atingido_na_cobertura_grava_o_marco(store):
    pid, problem_id = confirmed(store, tipo="cobertura", metrica=None, alvo=None, delta_min=None)
    code, _ = run(store, "objective", pid, "--atingido")
    assert code == 0
    (mark,) = store.get_node(problem_id).properties["objetivo_atingido"]
    assert mark["tipo"] == "cobertura" and mark["declarado_por"] == "pesquisador"
    assert [a for a in store.audit_log if a["node_id"] == problem_id][-1]["actor"] == "pesquisador"
    run(store, "objective", pid, "--atingido")  # acrescenta; nunca sobrescreve
    assert len(store.get_node(problem_id).properties["objetivo_atingido"]) == 2


def test_projeto_sem_problema_e_projeto_inexistente(store):
    pid = projects.create_project(store, "P", "Obj", [])
    assert run(store, "objective", pid, "--ao-atingir", "parar")[0] == 1
    assert run(store, "objective", "../x", "--atingido")[0] == 1


def test_so_o_pesquisador_altera_o_objetivo(store):
    pid, _ = confirmed(store)
    agent = Actor(kind="agente", role="researcher")
    with pytest.raises(projects.ProjectError):
        projects.set_objective_policy(store, pid, "parar", decided_by=agent)
    with pytest.raises(projects.ProjectError):
        projects.declare_objective_reached(store, pid, decided_by=agent)
