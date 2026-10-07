"""Correções do parecer de segurança do PR #103 (v17-research-project). Sem rede, banco ou LLM."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import cli
from src.knowledge import projects
from src.knowledge.errors import HumanConfirmationRequiredError
from src.knowledge.graph_store import AgeGraphStore, InMemoryGraphStore
from src.knowledge.problem import parse_problem_draft
from src.knowledge.provenance import Actor
from src.orchestrator import AgentResult, AgentTask, Orchestrator
from src.project_session import ProjectBinder, ProjectFlowError, resolve_project
from tests.unit.research_project.test_flow import make_drafter, scripted
from tests.unit.research_project.test_projects import make_draft

AGENTE = Actor(kind="agente", role="researcher", model="m")
ORQ = Actor(kind="orquestrador")
PESQ = Actor(kind="pesquisador")
REPO = Path(__file__).resolve().parents[3]


def problema_props(pid: str, status: str, actor: Actor) -> dict:
    props = {"titulo": "t", "resumo": "r", "status": status, "projeto_id": pid, "sessao_id": "s"}
    if actor.kind == "agente":
        props.update(justificativa_criacao="j", nos_consultados=[])
    return props


@pytest.fixture
def store() -> InMemoryGraphStore:
    return InMemoryGraphStore()


@pytest.fixture
def pid(store) -> str:
    return projects.create_project(store, "P", "O", [])


# --------------------------------------------------------------------- S1


@pytest.mark.unit
class TestHumanOnlyNoGraphStore:
    @pytest.mark.parametrize("actor", [AGENTE, ORQ])
    def test_nao_cria_confirmado(self, store, pid, actor) -> None:
        with pytest.raises(HumanConfirmationRequiredError):
            store.create_node("Problema", problema_props(pid, "confirmado", actor), actor=actor)
        assert store.find_nodes("Problema", {}) == []

    @pytest.mark.parametrize("actor", [AGENTE, ORQ])
    def test_nao_promove_nem_rebaixa(self, store, pid, actor) -> None:
        rascunho = store.create_node("Problema", problema_props(pid, "rascunho", AGENTE), actor=AGENTE)
        with pytest.raises(HumanConfirmationRequiredError):
            store.update_node(rascunho, {"status": "confirmado"}, actor=actor)
        assert store.get_node(rascunho).properties["status"] == "rascunho"
        store.update_node(rascunho, {"status": "confirmado"}, actor=PESQ)
        with pytest.raises(HumanConfirmationRequiredError):
            store.update_node(rascunho, {"status": "rascunho"}, actor=actor)
        assert store.get_node(rascunho).properties["status"] == "confirmado"

    def test_pesquisador_pode_tudo(self, store, pid) -> None:
        pid_node = store.create_node("Problema", problema_props(pid, "confirmado", PESQ), actor=PESQ)
        store.update_node(pid_node, {"status": "rascunho"}, actor=PESQ)

    def test_outros_campos_e_rotulos_nao_sao_afetados(self, store, pid) -> None:
        node = store.create_node("Problema", problema_props(pid, "rascunho", AGENTE), actor=AGENTE)
        store.update_node(node, {"titulo": "novo"}, actor=ORQ)
        store.create_node("Projeto", {"titulo": "x", "objetivo": "y", "status": "ativo",
                                      "projeto_id": "p2", "sessao_id": "s"}, actor=ORQ)

    def test_confirm_problem_continua_passando(self, store, pid) -> None:
        projects.confirm_problem(store, pid, make_draft(), sentido_metrica="maior_melhor")
        assert projects.get_active_problem(store, pid) is not None

    def test_age_store_aplica_a_mesma_regra(self) -> None:
        age = AgeGraphStore("g", reader_conninfo="postgresql://x", read_timeout_ms=1000)
        with patch.object(age, "_run_cypher", return_value=[]) as run:
            with pytest.raises(HumanConfirmationRequiredError):
                age.create_node("Problema", problema_props("p", "confirmado", AGENTE), actor=AGENTE)
            run.assert_not_called()
        from src.knowledge.graph_store import Node

        node = Node(id="n1", label="Problema", properties={"status": "rascunho"})
        with patch.object(age, "get_node", return_value=node), patch.object(age, "_run_cypher") as run:
            with pytest.raises(HumanConfirmationRequiredError):
                age.update_node("n1", {"status": "confirmado"}, actor=ORQ)
            run.assert_not_called()

    def test_guarda_estatica_ninguem_em_agents_ou_skills_constroi_pesquisador(self) -> None:
        """Agentes e skills nunca constroem o ator pesquisador nem importam PESQUISADOR."""
        pattern = re.compile(r"""Actor\([^)]*["']pesquisador["']|\bPESQUISADOR\b""")
        offenders = []
        for base in ("agents", "src/skills"):
            for path in (REPO / base).rglob("*.py"):
                if pattern.search(path.read_text(encoding="utf-8")):
                    offenders.append(str(path.relative_to(REPO)))
        assert not offenders, f"Código de agente/skill não pode construir Actor pesquisador: {offenders}"

    def test_guarda_estatica_ninguem_em_agents_ou_skills_aplica_alteracao_do_pesquisador(self) -> None:
        """v17-graph-cli: ``apply_plan`` e a confirmação humana só existem na CLI; agentes só importam a proposta."""
        pattern = re.compile(r"\b(apply_plan|issue_confirmation|HumanConfirmation)\b")
        offenders = [
            str(path.relative_to(REPO))
            for base in ("agents", "src/skills")
            for path in (REPO / base).rglob("*.py")
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        assert not offenders, f"Agente/skill não pode aplicar alteração do pesquisador: {offenders}"
        importers = [
            str(path.relative_to(REPO))
            for base in ("agents", "src")
            for path in (REPO / base).rglob("*.py")
            if "change_proposals" in path.read_text(encoding="utf-8")
            and str(path.relative_to(REPO))
            not in {"src/knowledge/change_proposals.py", "src/cli_graph.py", "agents/curator/edit.py"}
        ]
        assert not importers, f"Importadores não previstos de change_proposals: {importers}"


# --------------------------------------------------------------- grafo fora do ar


class _Boom(Exception):
    """Simula erro de driver (psycopg/qdrant), que não é GraphStoreError nem RuntimeError."""


def _down():
    raise _Boom("connection refused")


@pytest.mark.unit
@pytest.mark.asyncio
class TestGrafoForaDoAr:
    async def test_erro_de_driver_vira_project_flow_error(self) -> None:
        binder = ProjectBinder(_down, interactive=True, graph_optional=False)
        with pytest.raises(ProjectFlowError, match="indisponível"):
            await binder.bind("p")

    async def test_erro_de_driver_na_sonda(self) -> None:
        bad = MagicMock()
        bad.list_nodes.side_effect = _Boom("timeout")
        with pytest.raises(ProjectFlowError, match="indisponível"):
            await ProjectBinder(lambda: bad, interactive=True, graph_optional=False).bind("p")

    async def test_erro_de_driver_no_meio_do_fluxo(self, store) -> None:
        flaky = MagicMock(wraps=store)
        flaky.find_nodes.side_effect = _Boom("caiu")
        with pytest.raises(ProjectFlowError, match="Falha ao acessar"):
            await ProjectBinder(lambda: flaky, project_arg="01890000-0000-7000-8000-000000000000",
                                interactive=True, graph_optional=True).bind("p")

    async def test_opcional_ligado_so_se_grafo_nao_abrir(self) -> None:
        out: list[str] = []
        binding = await ProjectBinder(_down, interactive=False, graph_optional=True,
                                      output_fn=out.append).bind("p")
        assert binding.mode == "sem_grafo" and binding.project_id is None
        assert "SEM GRAFO" in out[0]

    async def test_opcional_nao_enfraquece_a_confirmacao(self, store, pid) -> None:
        """Com o grafo acessível a confirmação continua obrigatória, mesmo com a variável ligada."""
        drafter = make_drafter(make_draft())
        binder = ProjectBinder(lambda: store, project_arg=pid, drafter=drafter, interactive=False,
                               graph_optional=True)
        with pytest.raises(ProjectFlowError, match="sem TTY"):
            await binder.bind("p")
        drafter.assert_not_awaited()

    async def test_padrao_da_variavel_e_desligado(self) -> None:
        from src import config

        assert config.RESEARCH_PROJECT_GRAPH_OPTIONAL is False
        assert "RESEARCH_PROJECT_GRAPH_OPTIONAL=false" in (REPO / ".env.example").read_text()

    async def test_execute_prompt_grava_project_mode_sem_grafo(self) -> None:
        orch = MagicMock()
        orch.handle_request = AsyncMock(return_value=MagicMock(session_id=None))
        binder = MagicMock()
        binder.bind = AsyncMock(return_value=MagicMock(mode="sem_grafo", project_id=None, context_block=""))
        with patch.object(cli, "format_result", lambda _r: "ok"):
            assert await cli.execute_prompt(orch, "p", project_binder=binder) is True
        kwargs = orch.handle_request.await_args.kwargs
        assert kwargs["project_mode"] == "sem_grafo" and "project_id" not in kwargs


# ------------------------------------------------------------- TTY, atomicidade


@pytest.mark.unit
@pytest.mark.asyncio
class TestSemOrfaosEAtomicidade:
    async def test_sem_tty_nao_cria_projeto_orfao(self, store) -> None:
        with pytest.raises(ProjectFlowError, match="sem TTY"):
            await ProjectBinder(lambda: store, interactive=False, graph_optional=False).bind("prompt")
        assert store.find_nodes("Projeto", {}) == []

    async def test_resolve_project_allow_create_false(self, store, tmp_path) -> None:
        with pytest.raises(ProjectFlowError):
            resolve_project(store, "x", config_dir=tmp_path, allow_create=False)
        assert store.find_nodes("Projeto", {}) == []

    async def test_promocao_e_o_ultimo_passo(self, store, pid) -> None:
        """Falha ao ligar domínios deixa só rascunho: nunca um confirmado sem ligações."""
        with patch.object(projects, "_link_domains", side_effect=_Boom("falha")):
            with pytest.raises(_Boom):
                projects.confirm_problem(store, pid, make_draft(), sentido_metrica="maior_melhor")
        assert projects.get_active_problem(store, pid) is None
        assert [n.properties["status"] for n in store.find_nodes("Problema", {})] == ["rascunho"]

    async def test_mais_de_um_confirmado_e_fail_fast(self, store, pid) -> None:
        for _ in range(2):
            store.create_node("Problema", problema_props(pid, "confirmado", PESQ), actor=PESQ)
        with pytest.raises(projects.ProjectError, match="2 Problemas confirmados"):
            projects.get_active_problem(store, pid)

    async def test_corrida_de_confirmacoes_e_revertida(self, store, pid) -> None:
        """Se a promoção cria um segundo confirmado, ela é desfeita e a chamada falha."""
        real = projects._link_domains

        def link_then_race(*a, **k):
            real(*a, **k)
            store.create_node("Problema", problema_props(pid, "confirmado", PESQ), actor=PESQ)

        with patch.object(projects, "_link_domains", side_effect=link_then_race):
            with pytest.raises(projects.ProjectError):
                projects.confirm_problem(store, pid, make_draft(), sentido_metrica="maior_melhor")
        statuses = sorted(n.properties["status"] for n in store.find_nodes("Problema", {}))
        assert statuses == ["confirmado", "rascunho"]


# ---------------------------------------------------------------- autoria / sugestões


@pytest.mark.unit
@pytest.mark.asyncio
class TestAutoria:
    async def test_modelo_do_researcher_vai_para_criado_por(self, store, pid) -> None:
        binder = ProjectBinder(
            lambda: store, project_arg=pid, drafter=make_drafter(make_draft()), interactive=True,
            input_fn=scripted("c", "m", "c"), output_fn=lambda _m: None, researcher_model="ollama/qwen3:8b",
            graph_optional=False,
        )
        binding = await binder.bind("p")
        node = projects.get_active_problem(store, binding.project_id)
        assert node.properties["criado_por"] == "researcher/ollama/qwen3:8b"

    async def test_termos_do_llm_entram_como_researcher(self, store, pid) -> None:
        projects.confirm_problem(store, pid, make_draft(), researcher_model="m", sentido_metrica="maior_melhor")
        for label in ("Dominio", "Metrica"):
            nodes = [n for n in store.list_nodes(label) if n.properties.get("status") == "candidato"]
            assert nodes and all(n.properties["criado_por"] == "researcher/m" for n in nodes)

    async def test_cli_passa_modelo_do_roteador(self) -> None:
        text = (REPO / "src/cli.py").read_text()
        assert 'llm_routing.resolution("researcher").id' in text and "researcher_model=researcher_model" in text


@pytest.mark.unit
class TestSugestoes:
    def test_cr_removido_e_titulo_em_uma_linha(self) -> None:
        draft = parse_problem_draft({"titulo": "a\r\nb\rc", "resumo": "x\ry\nz"})
        assert draft.titulo == "a b c"
        assert "\r" not in draft.resumo and "\n" in draft.resumo

    def test_active_project_0600_atomico_e_sem_symlink(self, tmp_path) -> None:
        pid = projects.create_project(InMemoryGraphStore(), "T", "O")
        path = projects.set_default_project(pid, tmp_path)
        assert oct(path.stat().st_mode & 0o777) == "0o600"
        assert not list(tmp_path.glob(".*.tmp"))
        victim = tmp_path / "vitima.txt"
        victim.write_text("intacto")
        path.unlink()
        path.symlink_to(victim)
        with pytest.raises(projects.ProjectError):
            projects.set_default_project(pid, tmp_path)
        with pytest.raises(projects.ProjectError):
            projects.get_default_project(tmp_path)
        assert victim.read_text() == "intacto"


# ---------------------------------------------------- orquestrador: prompts e id


def planner_result(text: str) -> AgentResult:
    return AgentResult(agent_id="researcher", session_id="s", status="success", response={"text": text})


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrquestradorProjeto:
    async def _orch(self):
        from src.agents.validator_agent import ValidationResult

        orch = Orchestrator(session_manager=MagicMock(), output_manager=MagicMock())
        orch.validator = MagicMock()
        approved = ValidationResult(is_valid=True, status="approved", reason="ok")
        orch.validator.validate_plan = AsyncMock(return_value=approved)
        orch._project_blocks["master_s"] = "BLOCO-DO-PROJETO"
        return orch

    async def test_bloco_no_prompt_do_plan(self) -> None:
        orch = await self._orch()
        with patch.object(orch, "_execute_agent", AsyncMock(return_value=planner_result("[]"))) as ex:
            await orch._run_planning_loop("Prompt", "master_s")
        sent = ex.call_args_list[0].args[0].prompt
        assert sent.startswith("MODO: PLAN") and "BLOCO-DO-PROJETO" in sent

    async def test_bloco_no_prompt_do_replan(self) -> None:
        orch = await self._orch()
        with patch.object(orch, "_execute_agent", AsyncMock(return_value=planner_result("[]"))) as ex:
            await orch._run_planning_loop("Prompt", "master_s", previous_plan=[{"task_name": "a"}],
                                          execution_feedback="falhou")
        sent = ex.call_args_list[0].args[0].prompt
        assert sent.startswith("MODO: REPLAN") and "BLOCO-DO-PROJETO" in sent

    async def test_bloco_isolado_por_sessao(self) -> None:
        orch = await self._orch()
        with patch.object(orch, "_execute_agent", AsyncMock(return_value=planner_result("[]"))) as ex:
            await orch._run_planning_loop("Prompt", "outra_sessao")
        assert "BLOCO-DO-PROJETO" not in ex.call_args_list[0].args[0].prompt

    async def test_project_id_invalido_recusado(self) -> None:
        orch = Orchestrator(session_manager=MagicMock(), agent_runtime=MagicMock())
        with pytest.raises(projects.ProjectError):
            await orch.handle_request("p", [AgentTask(agent_id="a", prompt="p")], project_id="../../x")

    async def test_project_mode_no_payload(self) -> None:
        from src.session import Session

        sm = MagicMock()
        sm.create.return_value = Session(id="s1", agent_id="orchestrator", status="active",
                                         created_at="2025-01-01T00:00:00+00:00",
                                         updated_at="2025-01-01T00:00:00+00:00", payload={})
        runtime = MagicMock()
        runtime.run = AsyncMock(return_value=AgentResult(agent_id="a", session_id="s1", status="success",
                                                         response={}, error=None))
        orch = Orchestrator(session_manager=sm, agent_runtime=runtime)
        await orch.handle_request("p", [AgentTask(agent_id="a", prompt="p")], project_mode="sem_grafo")
        payloads = [c.kwargs.get("payload", {}) for c in sm.update.call_args_list]
        assert any(p.get("project_mode") == "sem_grafo" and "project_id" not in p for p in payloads)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_modo_auto_passa_o_modo_e_pede_confirmacao_uma_vez(store, pid) -> None:
    """Scenario: Modo autônomo — execute_prompt(mode='auto') confirma uma vez, antes do orquestrador."""
    drafter = make_drafter(make_draft())
    binder = ProjectBinder(lambda: store, project_arg=pid, drafter=drafter, interactive=True,
                           input_fn=scripted("c", "m", "c"), output_fn=lambda _m: None, graph_optional=False)
    orch = MagicMock()
    calls: list[str] = []

    async def handle(prompt, **kw):
        calls.append(kw["mode"])
        assert projects.get_active_problem(store, pid) is not None  # confirmado ANTES da execução
        return MagicMock(session_id=None)

    orch.handle_request = handle
    with patch.object(cli, "format_result", lambda _r: "ok"):
        assert await cli.execute_prompt(orch, "p", mode="auto", project_binder=binder) is True
        assert await cli.execute_prompt(orch, "p2", mode="auto", project_binder=binder) is True
    assert calls == ["auto", "auto"] and drafter.await_count == 1
