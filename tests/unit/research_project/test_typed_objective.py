"""Rascunho e confirmação do Problema com objetivo tipado (v18.7-exploration-limits, tarefa 5.1).

Cenários de ``specs/research-project/spec.md`` (Problema redigido pelo Researcher e confirmado pelo pesquisador).
"""

from __future__ import annotations

import pytest

from src.cli.project_session import ProjectFlowError, ensure_confirmed_problem
from src.knowledge import projects
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.problem import (
    Concorrente,
    ProblemDraftError,
    apply_edit,
    parse_problem_draft,
)
from tests.unit.research_project.test_flow import make_drafter, scripted
from tests.unit.research_project.test_projects import make_draft

RIVALS = (
    Concorrente("H1: o ruído domina", "a variância cai com mais dados"),
    Concorrente("H2: o viés domina", "o erro não cai"),
)
BASE = {"titulo": "T", "resumo": "R"}
NO_OBJECTIVE = {"metrica": None, "alvo": None, "delta_min": None}


@pytest.fixture
def store() -> InMemoryGraphStore:
    return InMemoryGraphStore()


@pytest.fixture
def pid(store) -> str:
    return projects.create_project(store, "P", "Obj", [])


def criterion(store, problem_id) -> dict:
    return store.get_node(problem_id).properties["criterio_sucesso"]


@pytest.mark.unit
class TestParse:
    def test_tipo_e_concorrentes(self) -> None:
        draft = parse_problem_draft(
            {**BASE, "criterio_sucesso": {"tipo": "discriminacao", "hipoteses_concorrentes": [
                {"enunciado": "a", "predicao": "p1"}, {"enunciado": "b", "predicao": "p2"}]}}
        )
        assert draft.tipo == "discriminacao" and [c.predicao for c in draft.concorrentes] == ["p1", "p2"]

    def test_tipo_invalido(self) -> None:
        with pytest.raises(ProblemDraftError, match="tipo"):
            parse_problem_draft({**BASE, "criterio_sucesso": {"tipo": "outro"}})

    def test_politica_do_llm_e_descartada(self) -> None:
        draft = parse_problem_draft({**BASE, "criterio_sucesso": {"tipo": "cobertura", "ao_atingir_objetivo": "parar"}})
        assert draft.ao_atingir_objetivo is None

    def test_concorrente_sem_predicao(self) -> None:
        with pytest.raises(ProblemDraftError):
            parse_problem_draft({**BASE, "criterio_sucesso": {"hipoteses_concorrentes": [{"enunciado": "a"}]}})

    def test_edicao_de_concorrentes_e_politica(self) -> None:
        draft = apply_edit(make_draft(tipo="discriminacao"), "concorrentes", "a :: p1 ; b :: p2")
        assert len(draft.concorrentes) == 2
        assert apply_edit(draft, "ao_atingir_objetivo", "continuar").ao_atingir_objetivo == "continuar"
        with pytest.raises(ProblemDraftError):
            apply_edit(draft, "ao_atingir_objetivo", "talvez")
        with pytest.raises(ProblemDraftError):
            apply_edit(draft, "concorrentes", "sem separador")


@pytest.mark.unit
class TestConfirmacao:
    def test_limiar_grava_tipo_sentido_e_autoria(self, store, pid) -> None:
        problem_id = projects.confirm_problem(store, pid, make_draft(), sentido_metrica="maior_melhor")
        crit = criterion(store, problem_id)
        assert crit["tipo"] == "limiar" and crit["sentido"] == "maior_melhor" and crit["definido_por"] == "pesquisador"

    def test_discriminacao_sem_delta_min_cria_as_concorrentes(self, store, pid) -> None:
        """Scenario: Discriminação sem delta_min."""
        draft = make_draft(tipo="discriminacao", concorrentes=RIVALS, **NO_OBJECTIVE)
        problem_id = projects.confirm_problem(store, pid, draft)
        crit = criterion(store, problem_id)
        assert "delta_min" not in crit and "alvo" not in crit
        rivals = [store.get_node(item["hipotese_id"]) for item in crit["hipoteses_concorrentes"]]
        assert len(rivals) == 2
        assert all(r.properties["concorrente"] is True and r.properties["origem"] == "pesquisador" for r in rivals)
        assert {r.properties["predicao"] for r in rivals} == {c.predicao for c in RIVALS}
        assert all(
            any(e.rel_type == "SOBRE" and e.dst_id == problem_id for e in store.neighbors(r.id, ["SOBRE"]).edges)
            for r in rivals
        )

    def test_discriminacao_com_uma_concorrente_recusada(self, store, pid) -> None:
        """Scenario: Discriminação com uma só concorrente."""
        draft = make_draft(tipo="discriminacao", concorrentes=RIVALS[:1], **NO_OBJECTIVE)
        with pytest.raises(ProblemDraftError, match="concorrentes"):
            projects.confirm_problem(store, pid, draft)
        assert store.find_nodes("Problema", {}) == [] and store.find_nodes("Hipotese", {}) == []

    def test_cobertura(self, store, pid) -> None:
        problem_id = projects.confirm_problem(store, pid, make_draft(tipo="cobertura", **NO_OBJECTIVE))
        assert criterion(store, problem_id)["tipo"] == "cobertura"

    def test_fronteira_recusada(self, store, pid) -> None:
        """Scenario: Fronteira recusada."""
        with pytest.raises(ProblemDraftError, match="fronteira"):
            projects.confirm_problem(store, pid, make_draft(tipo="fronteira"))
        assert store.find_nodes("Problema", {}) == []

    def test_politica_definida_pelo_pesquisador(self, store, pid) -> None:
        """Scenario: Política definida pelo pesquisador."""
        draft = make_draft(ao_atingir_objetivo="continuar")
        problem_id = projects.confirm_problem(store, pid, draft, sentido_metrica="maior_melhor")
        assert criterion(store, problem_id)["ao_atingir_objetivo"] == "continuar"
        audits = [a for a in store.audit_log if a["node_id"] == problem_id]
        assert audits[-1]["actor"] == "pesquisador"

    def test_sem_objetivo_exige_tipo_fora_do_auto(self, store, pid) -> None:
        with pytest.raises(ProblemDraftError, match="tipo do objetivo"):
            projects.confirm_problem(store, pid, make_draft(**NO_OBJECTIVE))

    def test_sem_objetivo_no_auto(self, store, pid) -> None:
        """Scenario: Objetivo ausente no modo automático."""
        problem_id = projects.confirm_problem(store, pid, make_draft(**NO_OBJECTIVE), objective_optional=True)
        crit = criterion(store, problem_id)
        assert "tipo" not in crit and "definido_por" not in crit
        assert store.get_node(problem_id).properties["status"] == "confirmado"

    def test_agente_nao_define_a_politica(self, store, pid) -> None:
        """A política não entra no nó criado pelo Researcher (só na promoção do pesquisador)."""
        problem_id = projects.confirm_problem(
            store, pid, make_draft(ao_atingir_objetivo="parar"), sentido_metrica="maior_melhor"
        )
        for audit in (a for a in store.audit_log if a["node_id"] == problem_id and a["actor"] != "pesquisador"):
            assert "ao_atingir_objetivo" not in (audit["changes"].get("criterio_sucesso") or {})

    def test_contexto_mostra_o_tipo_e_as_concorrentes(self, store, pid) -> None:
        draft = make_draft(tipo="discriminacao", concorrentes=RIVALS, **NO_OBJECTIVE)
        projects.confirm_problem(store, pid, draft)
        text = projects.format_project_context(projects.get_project(store, pid))
        assert "tipo=discriminacao" in text and "a variância cai" in text


async def run_flow(store, pid, drafter, input_fn, *, optional=False):
    return await ensure_confirmed_problem(
        store, pid, "prompt", None, drafter=drafter, interactive=True,
        input_fn=input_fn, output_fn=lambda _m: None, objective_optional=optional,
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestCli:
    async def test_limiar_sem_delta_min_pede_o_valor(self, store, pid) -> None:
        """Scenario: delta_min ausente no limiar."""
        drafter = make_drafter(make_draft(delta_min=None))
        detail = await run_flow(store, pid, drafter, scripted("c", "0,03", "m", "c"))
        assert detail.problema.properties["criterio_sucesso"]["delta_min"] == 0.03

    async def test_objetivo_ausente_no_assistido_pede_o_tipo(self, store, pid) -> None:
        """Scenario: Objetivo ausente no modo assistido."""
        drafter = make_drafter(make_draft(**NO_OBJECTIVE))
        inp = scripted("c", "c")
        detail = await run_flow(store, pid, drafter, inp)
        assert detail.problema.properties["criterio_sucesso"]["tipo"] == "cobertura"
        assert any("Tipo do objetivo" in p for p in inp.asked)

    async def test_objetivo_ausente_no_auto_confirma_sem_perguntar(self, store, pid) -> None:
        drafter = make_drafter(make_draft(**NO_OBJECTIVE))
        detail = await run_flow(store, pid, drafter, scripted("c"), optional=True)
        assert "tipo" not in detail.problema.properties["criterio_sucesso"]

    async def test_discriminacao_pede_as_concorrentes(self, store, pid) -> None:
        drafter = make_drafter(make_draft(tipo="discriminacao", **NO_OBJECTIVE))
        detail = await run_flow(store, pid, drafter, scripted("c", "a :: p1 ; b :: p2"))
        assert len(detail.problema.properties["criterio_sucesso"]["hipoteses_concorrentes"]) == 2

    async def test_discriminacao_com_uma_so_volta_ao_menu(self, store, pid) -> None:
        drafter = make_drafter(make_draft(tipo="discriminacao", **NO_OBJECTIVE))
        with pytest.raises(ProjectFlowError, match="cancelada"):
            await run_flow(store, pid, drafter, scripted("c", "a :: p1", "q"))
        assert store.find_nodes("Problema", {}) == []

    async def test_fronteira_recusada_na_cli(self, store, pid) -> None:
        drafter = make_drafter(make_draft(tipo="fronteira"))
        with pytest.raises(ProjectFlowError, match="cancelada"):
            await run_flow(store, pid, drafter, scripted("c", "q"))
        assert store.find_nodes("Problema", {}) == []

    async def test_politica_escolhida_na_confirmacao(self, store, pid) -> None:
        drafter = make_drafter(make_draft())
        detail = await run_flow(store, pid, drafter, scripted("e", "ao_atingir_objetivo", "continuar", "c", "m", "c"))
        assert detail.problema.properties["criterio_sucesso"]["ao_atingir_objetivo"] == "continuar"
