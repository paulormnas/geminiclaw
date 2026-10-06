"""Testes do fluxo de projeto/confirmação, CLI de projeto, rascunho do Researcher e orquestrador.

Sem rede, sem banco, sem LLM: grafo em memória e rascunhador/entrada simulados.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src import cli
from src.cli_project import handle_project_command
from src.knowledge import projects
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.problem import ProblemDraft
from src.orchestrator import AgentResult, AgentTask, Orchestrator
from src.project_session import (
    ProjectBinder,
    ProjectFlowError,
    ensure_confirmed_problem,
    resolve_project,
)
from tests.unit.research_project.test_projects import make_draft


def scripted(*answers: str):
    """Entrada simulada que devolve as respostas em ordem e falha se pedirem mais."""
    queue = list(answers)
    asked: list[str] = []

    def _input(prompt: str = "") -> str:
        asked.append(prompt)
        if not queue:
            raise AssertionError(f"entrada inesperada: {prompt!r}")
        return queue.pop(0)

    _input.asked = asked  # type: ignore[attr-defined]
    return _input


def make_drafter(*drafts: ProblemDraft):
    seq = list(drafts)
    mock = AsyncMock(side_effect=lambda *a, **k: seq.pop(0) if len(seq) > 1 else seq[0])
    return mock


@pytest.fixture
def store() -> InMemoryGraphStore:
    return InMemoryGraphStore()


@pytest.fixture
def pid(store) -> str:
    return projects.create_project(store, "P", "Obj", [])


async def run_flow(store, pid, drafter, input_fn, *, interactive=True):
    return await ensure_confirmed_problem(
        store, pid, "prompt", None, drafter=drafter, interactive=interactive,
        input_fn=input_fn, output_fn=lambda _m: None,
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestConfirmacaoNaCli:
    async def test_confirmar(self, store, pid) -> None:
        """Scenario: Confirmação (entrada simulada 'c')."""
        inp = scripted("c", "m", "c")  # métrica nova pede o sentido; depois confirma de novo
        detail = await run_flow(store, pid, make_drafter(make_draft()), inp)
        assert detail.problema is not None
        assert detail.problema.properties["status"] == "confirmado"

    async def test_editar_delta_min(self, store, pid) -> None:
        """Scenario: Edição de campo — altera delta_min para 0,02 antes de confirmar."""
        inp = scripted("e", "delta_min", "0,02", "c", "m", "c")
        detail = await run_flow(store, pid, make_drafter(make_draft()), inp)
        assert detail.problema.properties["criterio_sucesso"]["delta_min"] == 0.02

    async def test_delta_min_ausente_exige_valor(self, store, pid) -> None:
        """Scenario: delta_min ausente — a CLI exige o valor antes de gravar."""
        inp = scripted("c", "abc", "0.03", "m", "c")
        detail = await run_flow(store, pid, make_drafter(make_draft(delta_min=None)), inp)
        assert any("delta_min" in q for q in inp.asked)
        assert detail.problema.properties["criterio_sucesso"]["delta_min"] == 0.03

    async def test_delta_min_vazio_volta_ao_menu_sem_gravar(self, store, pid) -> None:
        inp = scripted("c", "", "q")
        with pytest.raises(ProjectFlowError):
            await run_flow(store, pid, make_drafter(make_draft(delta_min=None)), inp)
        assert projects.get_active_problem(store, pid) is None

    async def test_novo_rascunho_com_comentario(self, store, pid) -> None:
        """Pedir novo rascunho repassa o comentário ao Researcher."""
        drafter = make_drafter(make_draft(titulo="Primeiro"), make_draft(titulo="Segundo"))
        inp = scripted("n", "mais foco em ruído", "c", "m", "c")
        detail = await run_flow(store, pid, drafter, inp)
        assert drafter.await_count == 2
        assert drafter.await_args_list[1].args[3] == "mais foco em ruído"
        assert detail.problema.properties["titulo"] == "Segundo"

    async def test_cancelar_nao_grava(self, store, pid) -> None:
        with pytest.raises(ProjectFlowError):
            await run_flow(store, pid, make_drafter(make_draft()), scripted("q"))
        assert projects.get_active_problem(store, pid) is None

    async def test_eof_cancela_sem_gravar(self, store, pid) -> None:
        def eof(_p: str = "") -> str:
            raise EOFError

        with pytest.raises(ProjectFlowError):
            await run_flow(store, pid, make_drafter(make_draft()), eof)
        assert projects.get_active_problem(store, pid) is None

    async def test_sessao_nao_interativa_recusada(self, store, pid) -> None:
        """Scenario: Sessão não interativa — recusa com orientação, sem chamar o LLM."""
        drafter = make_drafter(make_draft())
        with pytest.raises(ProjectFlowError, match="project show"):
            await run_flow(store, pid, drafter, scripted(), interactive=False)
        drafter.assert_not_awaited()

    async def test_modo_auto_pede_confirmacao_uma_vez(self, store, pid) -> None:
        """Scenario: Modo autônomo — confirmação única antes da execução autônoma."""
        drafter = make_drafter(make_draft())
        binder = ProjectBinder(
            lambda: store, project_arg=pid, drafter=drafter, interactive=True,
            input_fn=scripted("c", "m", "c"), output_fn=lambda _m: None,
        )
        first = await binder.bind("prompt")
        second = await binder.bind("prompt")
        assert first is second
        assert drafter.await_count == 1

    async def test_sessoes_seguintes_sem_confirmacao(self, store, pid) -> None:
        """Scenario: Sessões seguintes — sem confirmação; o problema é injetado no contexto."""
        projects.confirm_problem(store, pid, make_draft(), sentido_metrica="maior_melhor")
        drafter = make_drafter(make_draft())
        binder = ProjectBinder(
            lambda: store, project_arg=pid, drafter=drafter, interactive=False,
            input_fn=scripted(), output_fn=lambda _m: None,
        )
        binding = await binder.bind("outro prompt")
        drafter.assert_not_awaited()
        assert "Previsão de rendimento" in binding.context_block

    async def test_grafo_indisponivel_falha_explicita(self) -> None:
        def boom():
            raise RuntimeError("KNOWLEDGE_READER_DATABASE_URL não configurada")

        with pytest.raises(ProjectFlowError, match="indisponível"):
            await ProjectBinder(boom, interactive=True).bind("p")


@pytest.mark.unit
class TestResolucaoDeProjeto:
    def test_sem_projeto_cria_com_titulo_do_prompt(self, store, tmp_path) -> None:
        """Scenario: Sem projeto informado — projeto criado com título derivado e ID exibido."""
        out: list[str] = []
        pid, created = resolve_project(
            store, "Prever rendimento\nmais detalhes", config_dir=tmp_path, output_fn=out.append
        )
        assert created
        detail = projects.get_project(store, pid)
        assert detail.titulo == "Prever rendimento"
        assert detail.objetivo == "Prever rendimento\nmais detalhes"
        assert pid in out[0]

    def test_projeto_padrao_e_usado(self, store, tmp_path) -> None:
        pid = projects.create_project(store, "P", "O")
        projects.set_default_project(pid, tmp_path)
        assert resolve_project(store, "x", config_dir=tmp_path) == (pid, False)

    def test_project_arg_tem_precedencia(self, store, tmp_path) -> None:
        a = projects.create_project(store, "A", "O")
        b = projects.create_project(store, "B", "O")
        projects.set_default_project(a, tmp_path)
        assert resolve_project(store, "x", project_arg=b, config_dir=tmp_path) == (b, False)

    def test_project_arg_invalido(self, store, tmp_path) -> None:
        with pytest.raises(ProjectFlowError):
            resolve_project(store, "x", project_arg="../../x", config_dir=tmp_path)


@pytest.mark.unit
class TestCliProjeto:
    def test_opcao_project_no_parser(self) -> None:
        args = cli.build_parser().parse_args(["--project", "abc", "tarefa"])
        assert args.project == "abc"

    def test_project_new_list_show_use(self, store, tmp_path) -> None:
        out: list[str] = []
        run = lambda *argv: handle_project_command(list(argv), store, config_dir=tmp_path, output_fn=out.append)  # noqa: E731
        assert run("new", "--titulo", "T", "--objetivo", "O", "--dominio", "Química") == 0
        pid = out[-1].split(": ")[1]
        assert run("list") == 0 and pid in out[-1]
        assert run("show", pid) == 0 and "sem problema confirmado" in "\n".join(out)
        assert run("use", pid) == 0
        assert projects.get_default_project(tmp_path) == pid
        assert run("show", "../x") == 1

    @pytest.mark.asyncio
    async def test_execute_prompt_recusa_sessao_sem_problema(self) -> None:
        """execute_prompt não chama o orquestrador quando o vínculo é recusado."""
        orch = MagicMock()
        orch.handle_request = AsyncMock()
        binder = MagicMock()
        binder.bind = AsyncMock(side_effect=ProjectFlowError("recusada"))
        ok = await cli.execute_prompt(orch, "p", mode="auto", project_binder=binder)
        assert ok is False
        orch.handle_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_prompt_repassa_projeto(self, monkeypatch) -> None:
        orch = MagicMock()
        orch.handle_request = AsyncMock(return_value=MagicMock(session_id=None))
        binder = MagicMock()
        binder.bind = AsyncMock(return_value=MagicMock(project_id="pid1", context_block="CTX"))
        monkeypatch.setattr(cli, "format_result", lambda _r: "ok")
        assert await cli.execute_prompt(orch, "p", mode="auto", project_binder=binder) is True
        kwargs = orch.handle_request.await_args.kwargs
        assert kwargs["project_id"] == "pid1" and kwargs["project_context"] == "CTX"


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrquestrador:
    async def test_sessao_em_projeto_existente(self, tmp_path) -> None:
        """Scenario: Sessão em projeto existente — payload da sessão com project_id."""
        from src.session import Session

        sm = MagicMock()
        sess = Session(id="s1", agent_id="orchestrator", status="active",
                       created_at="2025-01-01T00:00:00+00:00", updated_at="2025-01-01T00:00:00+00:00", payload={})
        sm.create.return_value = sess
        runtime = MagicMock()
        runtime.run = AsyncMock(return_value=AgentResult(
            agent_id="a", session_id="s1", status="success", response={}, error=None))
        # O grafo da ingestão de fatos é injetado: nenhum teste abre o banco real nem grava em outputs/.
        from src.output_manager import OutputManager

        orch = Orchestrator(
            session_manager=sm, agent_runtime=runtime,
            output_manager=OutputManager(str(tmp_path / "out"), str(tmp_path / "logs")),
            knowledge_store_factory=InMemoryGraphStore,
        )
        await orch.handle_request("p", [AgentTask(agent_id="a", prompt="p")],
                                  project_id="01890000-0000-7000-8000-000000000001", project_context="CTX")
        payloads = [c.kwargs.get("payload", {}) for c in sm.update.call_args_list]
        assert any(p.get("project_id") == "01890000-0000-7000-8000-000000000001" for p in payloads)
        assert orch._project_blocks == {sess.id: "CTX"}
