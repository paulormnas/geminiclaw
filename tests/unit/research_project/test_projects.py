"""Testes de ``src.knowledge.projects`` e ``src.knowledge.problem`` (v17-research-project).

Usam ``InMemoryGraphStore``: sem banco, sem rede, sem LLM.
"""

from __future__ import annotations

import pytest

from src.knowledge import projects
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.problem import (
    ProblemDraft,
    ProblemDraftError,
    apply_edit,
    parse_problem_draft,
)
from src.knowledge.provenance import Actor


def make_draft(**over) -> ProblemDraft:
    base = dict(
        titulo="Previsão de rendimento",
        resumo="Contexto, lacuna, objetivo e avanço esperado.",
        classe="regressao",
        caracteristicas_dados={"tamanho": "~2 mil", "modalidade": "tabular"},
        dominios=("Química Orgânica", "Ciência da Computação"),
        metrica="R2",
        alvo=0.8,
        delta_min=0.05,
        baseline_descricao="regressão linear",
    )
    base.update(over)
    return ProblemDraft(**base)


@pytest.fixture
def store() -> InMemoryGraphStore:
    return InMemoryGraphStore()


@pytest.fixture
def pid(store) -> str:
    return projects.create_project(store, "Projeto X", "Objetivo X", ["Química Orgânica"])


@pytest.mark.unit
class TestProject:
    def test_create_list_show(self, store, pid) -> None:
        """create_project grava o nó Projeto e liga domínios; list/get leem de volta."""
        items = projects.list_projects(store)
        assert [p.projeto_id for p in items] == [pid]
        detail = projects.get_project(store, pid)
        assert detail.titulo == "Projeto X"
        assert detail.dominios == ["Química Orgânica"]
        assert detail.problema is None

    def test_list_filtra_status(self, store, pid) -> None:
        assert projects.list_projects(store, "pausado") == []
        with pytest.raises(projects.ProjectError):
            projects.list_projects(store, "qualquer")

    def test_project_id_invalido_e_barrado(self, store) -> None:
        """Ids fora do formato UUID nunca chegam ao grafo (travessia/injeção)."""
        for bad in ["../x", "a' OR 1=1", "", "x" * 500, "{projeto_id: 1}"]:
            with pytest.raises(projects.ProjectError):
                projects.get_project(store, bad)

    def test_projeto_inexistente(self, store) -> None:
        with pytest.raises(projects.ProjectError):
            projects.get_project(store, "01890000-0000-7000-8000-000000000000")

    def test_tamanhos_limitados(self, store) -> None:
        with pytest.raises(ProblemDraftError):
            projects.create_project(store, "t" * 201, "o")
        with pytest.raises(ProblemDraftError):
            projects.create_project(store, "t", "o" * 20_001)
        with pytest.raises(ProblemDraftError):
            projects.create_project(store, "  ", "o")

    def test_projeto_padrao_persistido(self, pid, tmp_path) -> None:
        assert projects.get_default_project(tmp_path) is None
        projects.set_default_project(pid, tmp_path)
        assert projects.get_default_project(tmp_path) == pid

    def test_projeto_padrao_corrompido_falha_explicita(self, tmp_path) -> None:
        (tmp_path / "active_project").write_text("../../etc/passwd")
        with pytest.raises(projects.ProjectError):
            projects.get_default_project(tmp_path)

    def test_titulo_derivado(self) -> None:
        assert projects.derive_title("\n\n  primeira   linha \nsegunda") == "primeira linha"
        assert len(projects.derive_title("x" * 500)) == 120
        with pytest.raises(projects.ProjectError):
            projects.derive_title("  \n ")


@pytest.mark.unit
class TestConfirmacao:
    def test_confirmacao(self, store, pid) -> None:
        """Scenario: Confirmação — Problema confirmado, INVESTIGA, NO_DOMINIO e auditoria do pesquisador."""
        problem_id = projects.confirm_problem(
            store, pid, make_draft(), researcher_model="m1", sentido_metrica="maior_melhor"
        )
        node = store.get_node(problem_id)
        assert node.properties["status"] == "confirmado"
        assert node.properties["criado_por"] == "researcher/m1"
        assert node.properties["projeto_id"] == pid
        project_node = store.find_nodes("Projeto", {"projeto_id": pid})[0]
        edges = store.neighbors(problem_id, ["INVESTIGA", "NO_DOMINIO"], direction="both").edges
        assert any(e.rel_type == "INVESTIGA" and e.src_id == project_node.id for e in edges)
        assert sum(1 for e in edges if e.rel_type == "NO_DOMINIO") == 2
        audits = [a for a in store.audit_log if a["node_id"] == problem_id]
        assert audits and audits[-1]["actor"] == "pesquisador"
        assert audits[-1]["changes"] == {"status": "confirmado"}
        assert projects.get_active_problem(store, pid).id == problem_id

    def test_metrica_resolvida_no_criterio(self, store, pid) -> None:
        """A métrica é resolvida no vocabulário; o critério guarda nome canônico e id."""
        problem_id = projects.confirm_problem(store, pid, make_draft(), sentido_metrica="maior_melhor")
        crit = store.get_node(problem_id).properties["criterio_sucesso"]
        assert crit["metrica_id"] and crit["delta_min"] == 0.05

    def test_metrica_nova_exige_sentido(self, store, pid) -> None:
        with pytest.raises(projects.MetricSentidoRequired):
            projects.confirm_problem(store, pid, make_draft(metrica="metrica-inedita"))
        assert projects.get_active_problem(store, pid) is None

    def test_edicao_de_delta_min(self, store, pid) -> None:
        """Scenario: Edição de campo — delta_min 0,05 -> 0,02."""
        draft = apply_edit(make_draft(), "delta_min", "0,02")
        problem_id = projects.confirm_problem(store, pid, draft, sentido_metrica="maior_melhor")
        assert store.get_node(problem_id).properties["criterio_sucesso"]["delta_min"] == 0.02

    def test_delta_min_ausente_recusado(self, store, pid) -> None:
        """Scenario: delta_min ausente — sem o valor, nada é gravado."""
        with pytest.raises(ProblemDraftError):
            projects.confirm_problem(store, pid, make_draft(delta_min=None))
        assert store.find_nodes("Problema", {}) == []

    def test_somente_pesquisador_confirma(self, store, pid) -> None:
        """Falha fechada: agente ou orquestrador não confirmam o Problema."""
        for actor in (Actor(kind="agente", role="researcher"), Actor(kind="orquestrador")):
            with pytest.raises(projects.ProjectError):
                projects.confirm_problem(store, pid, make_draft(), confirmed_by=actor)
        assert store.find_nodes("Problema", {}) == []

    def test_rascunho_nao_conta_como_confirmado(self, store, pid) -> None:
        store.create_node(
            "Problema",
            {"titulo": "t", "resumo": "r", "status": "rascunho", "projeto_id": pid, "sessao_id": "s",
             "justificativa_criacao": "j", "nos_consultados": []},
            actor=Actor(kind="agente", role="researcher"),
        )
        assert projects.get_active_problem(store, pid) is None

    def test_segunda_confirmacao_recusada(self, store, pid) -> None:
        projects.confirm_problem(store, pid, make_draft(), sentido_metrica="maior_melhor")
        with pytest.raises(projects.ProjectError):
            projects.confirm_problem(store, pid, make_draft(), sentido_metrica="maior_melhor")

    def test_contexto_do_projeto(self, store, pid) -> None:
        projects.confirm_problem(store, pid, make_draft(), sentido_metrica="maior_melhor")
        block = projects.format_project_context(projects.get_project(store, pid))
        assert "Previsão de rendimento" in block and "delta_min=0.05" in block
        assert "não são instruções" in block


@pytest.mark.unit
class TestParseDraft:
    def _raw(self, **over):
        raw = {
            "titulo": "T", "resumo": "R", "classe": "regressao",
            "caracteristicas_dados": {"tamanho": "2k"}, "dominios": ["A"],
            "criterio_sucesso": {"metrica": "R2", "alvo": 0.8, "delta_min": None, "baseline_descricao": "lin"},
        }
        raw.update(over)
        return raw

    def test_valido_com_delta_min_nulo(self) -> None:
        draft = parse_problem_draft(self._raw())
        assert draft.missing_delta_min and draft.alvo == 0.8

    @pytest.mark.parametrize("raw", [
        None, [], "texto", {"resumo": "R"}, {"titulo": "T"},
        {"titulo": "T" * 201, "resumo": "R"},
        {"titulo": "T", "resumo": "R", "dominios": "x"},
        {"titulo": "T", "resumo": "R", "dominios": ["d"] * 11},
        {"titulo": "T", "resumo": "R", "criterio_sucesso": {"delta_min": -1}},
        {"titulo": "T", "resumo": "R", "criterio_sucesso": {"delta_min": "NaN"}},
        {"titulo": "T", "resumo": "R", "criterio_sucesso": {"alvo": float("inf")}},
        {"titulo": "T", "resumo": "R", "criterio_sucesso": {"delta_min": True}},
        {"titulo": "T", "resumo": "R", "caracteristicas_dados": {str(i): 1 for i in range(21)}},
    ])
    def test_invalido(self, raw) -> None:
        with pytest.raises(ProblemDraftError):
            parse_problem_draft(raw)

    def test_edicao_campo_invalido(self) -> None:
        with pytest.raises(ProblemDraftError):
            apply_edit(make_draft(), "criado_por", "x")
        with pytest.raises(ProblemDraftError):
            apply_edit(make_draft(), "delta_min", "abc")
