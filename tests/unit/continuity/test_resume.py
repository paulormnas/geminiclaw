"""Retomada a partir do checkpoint (v18-research-continuity): cenários da spec ``session-continuity``."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.base.tools import read_artifact, write_artifact
from src.agent_runtime.context import AgentContext, bind_agent_context, current_context
from src.autonomous_loop import AutonomousLoop
from src.continuity import CheckpointRecorder, plan_entry, read_checkpoint
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.ingestion import SessionContext, ingest_session_start
from src.knowledge.projects import confirm_problem, create_project
from src.knowledge.provenance import Actor
from src.orchestrator import AgentResult, AgentTask, Orchestrator
from src.output_manager import OutputManager
from src.resume import ResumeError, prepare_resume, select_session_for_project
from src.usage import UsageBudget
from tests.support.session_fakes import FakeSessionManager
from tests.unit.research_project.test_projects import make_draft

pytestmark = pytest.mark.unit

NAMES = ["coleta", "limpeza", "baseline", "treino", "avaliacao"]


class World:
    """Sessão de origem `sessao-a` (3 concluídas, 2 pendentes) com projeto, Problema confirmado e grafo."""

    def __init__(self, tmp_path: Path, *, motivo="limite_tokens", status="closed", curator_pendente=False,
                 confirm=True) -> None:
        self.store = InMemoryGraphStore()
        self.pid = create_project(self.store, "P", "O", [])
        if confirm:
            confirm_problem(self.store, self.pid, make_draft(), sentido_metrica="maior_melhor")
        self.sm = FakeSessionManager()
        self.runtime = MagicMock()
        self.ran: list[str] = []
        self.prompts: dict[str, str] = {}
        self.contexts: dict[str, AgentContext] = {}

        async def _run(task, ctx):
            self.ran.append(task.task_name)
            self.prompts[task.task_name] = task.prompt
            self.contexts[task.task_name] = ctx
            return AgentResult(agent_id=task.agent_id, session_id="x", status="success", response={"text": "feito"})

        self.runtime.run = _run
        self.orch = Orchestrator(
            session_manager=self.sm,
            output_manager=OutputManager(str(tmp_path / "out"), str(tmp_path / "logs")),
            agent_runtime=self.runtime,
            knowledge_store_factory=lambda: self.store,
        )
        self.orch.rate_limiter.acquire = AsyncMock()
        self.base = self.orch.output_manager.base_dir
        self.sdir = self.orch.output_manager.init_session("sessao-a")
        rec = CheckpointRecorder.start(
            self.sdir, session_id="sessao-a", project_id=self.pid, continues_session_id=None,
            prompt="Estudar rendimento", modo="auto",
        )
        rec.set_plan([
            plan_entry(AgentTask(agent_id="developer", prompt=f"faça {n}", task_name=n, subtask_id=f"id-{n}",
                                 depends_on=[NAMES[i - 1]] if i else []))
            for i, n in enumerate(NAMES)
        ])
        for n in NAMES[:3]:
            (self.sdir / n).mkdir()
            (self.sdir / n / "metrics.json").write_text('{"r2": 0.7}', encoding="utf-8")
            rec.subtask_finished(n, status="concluida", tentativas=1, resumo=f"resultado de {n}",
                                 artefatos=[f"{n}/metrics.json"])
        (self.sdir / "artifacts").mkdir(exist_ok=True)
        (self.sdir / "artifacts" / "dados.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        rec.close("fechado", motivo, curator_pendente=curator_pendente)
        self.sm.add("sessao-a", status, {"project_id": self.pid, "prompt": "Estudar rendimento", "mode": "auto"})
        ingest_session_start(
            self.store, SessionContext(self.pid, "sessao-a", "auto", "2026-10-06T10:00:00+00:00", "no")
        )

    async def prepare(self, **kw):
        return await prepare_resume(
            session_manager=self.sm, base_dir=self.base, session_id=kw.pop("session_id", "sessao-a"),
            store=self.store, **kw,
        )

    def patch_loop(self):
        """Planejamento devolve o plano completo; síntese e promoção não chamam LLM."""
        tasks = [
            AgentTask(agent_id="developer", prompt=f"faça {n}", task_name=n,
                      depends_on=[NAMES[i - 1]] if i else [])
            for i, n in enumerate(NAMES)
        ]
        self.orch._run_planning_loop = AsyncMock(side_effect=lambda **k: [
            AgentTask(agent_id=t.agent_id, prompt=t.prompt, task_name=t.task_name, depends_on=list(t.depends_on))
            for t in tasks
        ])
        stack = [
            patch.object(AutonomousLoop, "_promote_findings", AsyncMock()),
            patch.object(AutonomousLoop, "_synthesize_results", AsyncMock(return_value=None)),
            patch("src.config.REVIEW_ENABLED", False),
            patch("src.orchestrator.generate_session_slug", return_value="sessao-b"),
        ]
        return stack

    async def run_resume(self, budget=None, **kw):
        prep = await self.prepare(**kw)
        from contextlib import ExitStack

        with ExitStack() as st:
            for p in self.patch_loop():
                st.enter_context(p)
            result = await self.orch.handle_request(
                prep.prompt, mode=prep.mode, budget=budget, project_id=prep.state.project_id,
                project_context=prep.project_context, resume=prep.state,
                llm_routing=MagicMock(catalogo=MagicMock(hash="h", versao="1"), politica="p", modo="m",
                                      payload=lambda: {}),
            )
        return prep, result


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture(autouse=True)
def _no_context():
    token = current_context.set(None)
    yield
    current_context.reset(token)


@pytest.fixture(autouse=True)
def _routing_stub():
    with patch("src.orchestrator.bind_session_routing"), patch("src.orchestrator.build_session_routing", AsyncMock()):
        yield


# -- Retomada a partir do checkpoint -------------------------------------------------------------


@pytest.mark.asyncio
async def test_retomada_apos_limite_nao_reexecuta_concluidas(world):
    """Scenario: Retomada após limite — nova sessão com `continues_session_id`, aresta CONTINUA e as 3
    subtarefas concluídas não são reexecutadas, mas seus resultados chegam às dependentes (4.4)."""
    prep, result = await world.run_resume()

    assert world.ran == ["treino", "avaliacao"]  # 2 pendentes; as 3 concluídas não rodaram
    nova = world.sm.get("sessao-b")
    assert nova.payload["continues_session_id"] == "sessao-a"
    assert nova.payload["project_id"] == world.pid
    assert "resultado de baseline" in world.prompts["treino"]  # resultado reaproveitado pela dependente
    assert "sessao-a/baseline/metrics.json" in world.prompts["treino"]  # artefato anterior referenciado
    assert result.succeeded == result.total == 5  # as concluídas contam como já realizadas
    # grafo: aresta CONTINUA da nova para a anterior
    nova_no = world.store.find_nodes("Sessao", {"sessao_id": "sessao-b"})[0]
    antiga_no = world.store.find_nodes("Sessao", {"sessao_id": "sessao-a"})[0]
    edges = world.store.neighbors(nova_no.id, ["CONTINUA"], direction="out", depth=1).edges
    assert [(e.src_id, e.dst_id) for e in edges] == [(nova_no.id, antiga_no.id)]
    # checkpoint da nova sessão herda as concluídas e fecha
    cp, _ = read_checkpoint(world.base / "sessao-b")
    assert cp.continues_session_id == "sessao-a" and cp.estado == "fechado"
    assert {s.task_name for s in cp.subtarefas if s.status == "concluida"} == set(NAMES)
    assert (cp.find("treino").tentativas, cp.find("treino").resultado_resumo) == (1, "feito")  # 4.1 no laço


@pytest.mark.asyncio
async def test_retomada_apos_limite_tokens_recebe_orcamento_novo(world):
    """Scenario: Retomada após `limite_tokens` recebe orçamento novo (4.5)."""
    budget = UsageBudget(max_tokens=777, max_minutes=11, max_task_retries=2, max_connection_retries=3,
                         closing_reserve_pct=0.1)
    await world.run_resume(budget=budget)
    nova = world.sm.get("sessao-b")
    assert nova.payload["budget"]["max_tokens"] == 777
    assert nova.payload["budget"]["max_minutes"] == 11
    cp, _ = read_checkpoint(world.base / "sessao-b")
    assert cp.orcamento["max_tokens"] == 777
    assert cp.consumo["tokens"] == 0  # consumo da sessão nova parte de zero
    # a sessão de origem não é alterada
    assert world.sm.get("sessao-a").payload.get("budget") is None


@pytest.mark.asyncio
async def test_continuar_o_projeto(world):
    """Scenario: Continuar o projeto — `continue --project` retoma a sessão mais recente do projeto."""
    world.sm.add("sessao-velha", "closed", {"project_id": world.pid})
    world.sm.rows["sessao-velha"].created_at = "2020-01-01T00:00:00+00:00"
    assert select_session_for_project(world.sm, world.pid) == "sessao-a"
    with pytest.raises(ResumeError, match="não tem sessões"):
        select_session_for_project(world.sm, "01890000-0000-7000-8000-0000000000ff")

    from src import cli

    orch = MagicMock(session_manager=world.sm)
    orch.recover_interrupted_sessions = AsyncMock()
    with patch.object(cli, "_run_resume", AsyncMock(return_value=True)) as run:
        assert await cli.continue_project(orch, world.pid, mode="auto") is True
    assert run.await_args.args[1] == "sessao-a" and run.await_args.kwargs["project_arg"] == world.pid
    with patch.object(cli, "_run_resume", AsyncMock()) as run:
        assert await cli.continue_project(orch, "nao-e-uuid") is False
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_pesquisa_dada_como_resolvida_pede_confirmacao(tmp_path):
    """Scenario: Pesquisa dada como resolvida — a CLI pede confirmação antes de continuar (4.7)."""
    w = World(tmp_path, motivo="solucao_encontrada")
    asked: list[str] = []
    with pytest.raises(ResumeError, match="não confirmada"):
        await w.prepare(confirm=lambda q: asked.append(q) or False)
    with pytest.raises(ResumeError, match="não confirmada"):
        await w.prepare(confirm=None)  # sem terminal: nunca confirma por omissão
    assert "continuar explorando" in asked[0]
    prep = await w.prepare(confirm=lambda q: True)
    assert prep.state.source_session_id == "sessao-a"
    from src import cli

    with patch("src.project_session.is_interactive", return_value=False):
        assert cli._ask_yes_no("continuar?") is False


@pytest.mark.asyncio
async def test_caminho_sem_conclusao_no_contexto_do_researcher(world):
    """Scenario: Caminho sem conclusão — o contexto contém o caminho e o próximo passo sugerido."""
    world.store.create_node(
        "Descoberta",
        {"projeto_id": world.pid, "sessao_id": "sessao-a", "tipo": "caminho_sem_conclusao",
         "enunciado": "Caminho sem conclusão: treino com GPU", "n_evidencias": 1, "status": "ativa",
         "ponto_de_parada": "treino com GPU", "motivo": "limite_tokens",
         "proximo_passo_sugerido": "repetir com batch menor",
         "justificativa_criacao": "x", "nos_consultados": []},
        actor=Actor(kind="agente", role="curator"),
    )
    prep = await world.prepare()
    block = prep.state.context_block
    assert "treino com GPU" in block and "repetir com batch menor" in block
    assert "<dado_nao_confiavel" in block  # entregue como dado, nunca como instrução
    assert "resultado de coleta" in block and "pendente" in block  # estado do plano


@pytest.mark.asyncio
async def test_researcher_replaneja_em_modo_replan_com_contexto(world):
    """Contexto de retomada: o primeiro planejamento da sessão retomada é `MODO: REPLAN` com o bloco."""
    prep = await world.prepare()
    world.orch._resumes["sessao-b"] = prep.state
    world.orch._resume_planning.add("sessao-b")
    prompts: list[str] = []

    async def fake_exec(task, master_session_id=None, run_kind="execution"):
        prompts.append(task.prompt)
        plan = [{"agent_id": "developer", "task_name": "treino", "prompt": "x", "validation_criteria": ["c"]}]
        return AgentResult(agent_id="researcher", session_id="x", status="success",
                           response={"text": json.dumps(plan)})

    world.orch._execute_agent = fake_exec
    world.orch.validator.validate_plan = AsyncMock(return_value=SimpleNamespace(
        is_valid=True, signature="", deterministic=False, approved_with_warnings=False, status="approved",
        issues=[], reason="",
    ))
    tasks = await world.orch._run_planning_loop("Estudar rendimento", "sessao-b")
    assert [t.task_name for t in tasks] == ["treino"]
    assert prompts[0].startswith("MODO: REPLAN") and "RETOMADA DE SESSÃO ANTERIOR" in prompts[0]
    assert "NUNCA são repetidas" in prompts[0] and "resultado de coleta" in prompts[0]
    assert "sessao-b" not in world.orch._resume_planning  # replanos seguintes seguem o fluxo normal


@pytest.mark.asyncio
async def test_curator_pendente_fecha_a_sessao_anterior_antes_do_novo_plano(tmp_path):
    """Scenario: Curator pendente — executa o fechamento da sessão anterior antes do replanejamento."""
    w = World(tmp_path, curator_pendente=True)
    order: list[str] = []
    curator = MagicMock()

    async def close(motivo):
        order.append(f"curator:{motivo}")
        return SimpleNamespace(ok=True)

    curator.close_session = close
    w.orch._curator_for = MagicMock(return_value=curator)
    prep = await w.prepare()
    assert prep.state.curator_pending is True
    inner = w.patch_loop()
    original = w.orch._run_planning_loop

    async def planning(**kw):
        order.append("planejamento")
        return await original(**kw)

    from contextlib import ExitStack

    with ExitStack() as st:
        for p in inner:
            st.enter_context(p)
        w.orch._run_planning_loop = planning
        await w.orch.handle_request(
            prep.prompt, mode="auto", project_id=prep.state.project_id, project_context=prep.project_context,
            resume=prep.state,
            llm_routing=MagicMock(catalogo=MagicMock(hash="h", versao="1"), politica="p", modo="m", payload=lambda: {}),
        )
    assert order[:2] == ["curator:limite_tokens", "planejamento"]
    assert w.orch._curator_for.call_args.args[0] == "sessao-a"  # fecha a ANTERIOR
    cp, _ = read_checkpoint(w.sdir)
    assert cp.curator_pendente is False


@pytest.mark.asyncio
async def test_curator_pendente_que_falha_fica_pendente_na_nova_sessao(tmp_path):
    w = World(tmp_path, curator_pendente=True)
    curator = MagicMock()
    curator.close_session = AsyncMock(return_value=SimpleNamespace(ok=False))
    w.orch._curator_for = MagicMock(return_value=curator)
    await w.run_resume()
    cp_new, _ = read_checkpoint(w.base / "sessao-b")
    assert cp_new.curator_pendente is True
    cp_old, _ = read_checkpoint(w.sdir)
    assert cp_old.curator_pendente is True


# -- Artefatos anteriores legíveis, escrita isolada ---------------------------------------------


def _bind(w: World, agent="developer") -> Path:
    cur = w.base / "sessao-b"
    cur.mkdir(exist_ok=True)
    bind_agent_context(AgentContext(
        session_id="sessao-b", agent_session_id="x", agent_id=agent, mode="auto", output_dir=cur.resolve(),
        model="m", readable_dirs=((w.base / "sessao-a").resolve(),),
    ))
    return cur


@pytest.mark.asyncio
async def test_leitura_e_escrita_isoladas(world):
    """Scenario: Leitura e escrita — o Developer lê o artefato anterior e a escrita na anterior é recusada (4.6)."""
    cur = _bind(world)
    out = await read_artifact("artifacts/dados.csv", session_id="sessao-a")
    assert "a,b" in out and "sessao-a" in out

    original = (world.sdir / "artifacts" / "dados.csv").read_bytes()
    for target in (
        "sessao-a/artifacts/dados.csv",
        str((world.sdir / "artifacts" / "dados.csv").resolve()),
    ):
        refused = await write_artifact(target, "SOBRESCRITO")
        assert "recusada" in refused
    assert (world.sdir / "artifacts" / "dados.csv").read_bytes() == original
    ok = await write_artifact("novo.txt", "ok")  # a sessão atual continua gravável
    assert "sucesso" in ok and (cur / "artifacts" / "novo.txt").read_text() == "ok"


@pytest.mark.asyncio
async def test_leitura_recusa_sessao_fora_da_cadeia_travessia_e_link(world, tmp_path):
    _bind(world)
    outra = world.base / "sessao-x"
    (outra / "artifacts").mkdir(parents=True)
    (outra / "artifacts" / "s.txt").write_text("segredo")
    assert "não permitida" in await read_artifact("artifacts/s.txt", session_id="sessao-x")
    assert "inválido" in await read_artifact("../sessao-x/artifacts/s.txt", session_id="sessao-a")
    assert "inválido" in await read_artifact("/etc/passwd", session_id="sessao-a")
    assert "inválido" in await read_artifact("artifacts/x", session_id="../sessao-x")
    assert "controle" in await read_artifact("checkpoint.json", session_id="sessao-a")
    os.symlink(outra / "artifacts" / "s.txt", world.sdir / "artifacts" / "atalho.txt")
    assert "recusado" in await read_artifact("artifacts/atalho.txt", session_id="sessao-a")
    assert "não encontrado" in await read_artifact("artifacts/nada.txt", session_id="sessao-a")
    with patch("src.config.RESUME_ARTIFACT_MAX_READ_BYTES", 3):
        assert "truncado" in await read_artifact("artifacts/dados.csv", session_id="sessao-a")


@pytest.mark.asyncio
async def test_agent_context_recebe_readable_dirs_da_cadeia(world):
    await world.run_resume()
    ctx = world.contexts["treino"]
    assert [d.name for d in ctx.readable_dirs] == ["sessao-a"] and ctx.output_dir.name == "sessao-b"


# -- Segurança da retomada ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retomada_recusa_sessao_ativa_erro_e_ja_continuada(tmp_path):
    w = World(tmp_path, status="active")
    with pytest.raises(ResumeError, match="ainda está em execução"):
        await w.prepare()
    w2 = World(tmp_path / "e", motivo="erro")
    with pytest.raises(ResumeError, match="erro"):
        await w2.prepare()
    w3 = World(tmp_path / "c")
    w3.sm.add("sessao-b", "closed", {"continues_session_id": "sessao-a", "project_id": w3.pid, "motivo_parada": "limite_tempo"})
    w3.sm.rows["sessao-a"].payload["continued_by"] = "sessao-b"
    rec_b = CheckpointRecorder.start(w3.orch.output_manager.init_session("sessao-b"), session_id="sessao-b",
                                     project_id=w3.pid, continues_session_id="sessao-a", prompt="p", modo="auto")
    rec_b.close("fechado", "limite_tempo")
    with pytest.raises(ResumeError, match="já foi continuada por 'sessao-b'"):
        await w3.prepare()


@pytest.mark.asyncio
async def test_retomada_nao_confirma_problema(tmp_path):
    w = World(tmp_path, confirm=False)
    with pytest.raises(ResumeError, match="não confirma o Problema"):
        await w.prepare()
    assert w.store.find_nodes("Problema", {}) == []  # nada foi criado nem confirmado
    assert w.orch.human_gate is not None


@pytest.mark.asyncio
async def test_retomada_nao_atravessa_projetos(world):
    other = create_project(world.store, "Q", "O2", [])
    # projeto informado diferente do da sessão
    with pytest.raises(ResumeError, match="outro projeto"):
        await world.prepare(project_arg=other)
    # ancestral de outro projeto na cadeia
    world.sm.rows["sessao-a"].payload["continues_session_id"] = "sessao-z"
    world.orch.output_manager.init_session("sessao-z")
    world.sm.add("sessao-z", "closed", {"project_id": other})
    with pytest.raises(ResumeError, match="outro projeto"):
        await world.prepare()
    world.sm.rows["sessao-a"].payload.pop("continues_session_id")
    # a Sessao do grafo pertence a outro projeto
    ingest_session_start(world.store, SessionContext(other, "sessao-q", "auto", "2026", "no"))
    world.sm.add("sessao-q", "closed", {"project_id": world.pid, "prompt": "p"})
    world.orch.output_manager.init_session("sessao-q")
    rec = CheckpointRecorder.start(world.base / "sessao-q", session_id="sessao-q", project_id=world.pid,
                                   continues_session_id=None, prompt="p", modo="auto")
    rec.close("fechado", "limite_tempo")
    with pytest.raises(ResumeError, match="outro projeto no grafo"):
        await world.prepare(session_id="sessao-q")


@pytest.mark.asyncio
async def test_retomada_recusa_checkpoint_adulterado_e_ciclo(world):
    cp_path = world.sdir / "checkpoint.json"
    data = json.loads(cp_path.read_text(encoding="utf-8"))
    data["session_id"] = "sessao-outra"
    cp_path.write_text(json.dumps(data), encoding="utf-8")
    (world.sdir / "checkpoint.json.bak").unlink(missing_ok=True)
    with pytest.raises(ResumeError, match="checkpoint"):
        await world.prepare()
    # project_id do checkpoint diverge do banco de sessões
    data["session_id"] = "sessao-a"
    data["project_id"] = "01890000-0000-7000-8000-0000000000aa"
    cp_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ResumeError, match="diverge"):
        await world.prepare()
    # session_id malicioso
    with pytest.raises(ResumeError):
        await world.prepare(session_id="../../etc")


@pytest.mark.asyncio
async def test_ciclo_na_cadeia(world):
    world.sm.rows["sessao-a"].payload["continues_session_id"] = "sessao-a"
    with pytest.raises(ResumeError, match="ciclo"):
        await world.prepare()


@pytest.mark.asyncio
async def test_handle_request_recusa_retomada_de_outro_projeto(world):
    prep = await world.prepare()
    with pytest.raises(ValueError, match="outro projeto"):
        await world.orch.handle_request("p", project_id=create_project(world.store, "Z", "o", []),
                                        resume=prep.state, llm_routing=MagicMock())
    assert "sessao-b" not in world.sm.rows


@pytest.mark.asyncio
async def test_telemetria_da_recuperacao_sem_dado_de_pesquisa(tmp_path):
    from tests.unit.continuity.test_interruption import _crashed_session, _orch

    sm = FakeSessionManager()
    orch = _orch(tmp_path, sm, InMemoryGraphStore())
    _crashed_session(tmp_path, sm, orch, None)
    with patch("src.orchestrator.get_telemetry") as tel:
        await orch.recover_interrupted_sessions()
    payloads = [c.kwargs["payload"] for c in tel.return_value.record_agent_event.call_args_list]
    assert payloads and all(set(p) <= {"subtarefas_em_andamento", "retomavel", "segundos_sem_batimento"} for p in payloads)


# -- Ciclo de vida do checkpoint no orquestrador -----------------------------------------------


@pytest.mark.asyncio
async def test_suspensao_mantem_sessao_retomavel(world):
    """Sessão suspensa pelo pesquisador continua `suspended` (não vira `closed`) e é retomável."""
    async def suspend(self, master_session_id):
        cur = self.orchestrator.session_manager.get(master_session_id)
        self.orchestrator.session_manager.update(
            master_session_id, status="suspended", payload={**cur.payload, "motivo_parada": "interrompida"}
        )
        return True

    with patch.object(AutonomousLoop, "_check_operational_thresholds", suspend):
        await world.run_resume()
    assert world.sm.get("sessao-b").status == "suspended"
    cp, _ = read_checkpoint(world.base / "sessao-b")
    assert (cp.estado, cp.motivo_parada) == ("interrompido", "interrompida")
    prep = await world.prepare(session_id="sessao-b")
    assert prep.state.source_session_id == "sessao-b"


@pytest.mark.asyncio
async def test_erro_fatal_grava_checkpoint_interrompido(world):
    prep = await world.prepare()
    world.orch._run_planning_loop = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("src.orchestrator.generate_session_slug", return_value="sessao-b"), \
            pytest.raises(RuntimeError):
        await world.orch.handle_request(
            prep.prompt, mode="auto", project_id=prep.state.project_id, resume=prep.state,
            llm_routing=MagicMock(catalogo=MagicMock(hash="h", versao="1"), politica="p", modo="m", payload=lambda: {}),
        )
    cp, _ = read_checkpoint(world.base / "sessao-b")
    assert (cp.estado, cp.motivo_parada) == ("interrompido", "erro")
