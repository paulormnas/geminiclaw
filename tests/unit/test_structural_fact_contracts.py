"""Contratos e ligações da ``v17-structural-fact-ingestion``.

Cobre o contrato de artefatos (``datasets``/``baselines``), o plano com ``approach``, a saída
estruturada do sandbox, o manifest, e a ligação do orquestrador, do laço autônomo e da CLI com a
ingestão. Sem rede, sem LLM, sem Docker real e sem AGE.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.autonomous_loop import AutonomousLoop
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.ingestion_queue import PENDING_FILENAME
from src.knowledge.projects import create_project
from src.orchestrator import AgentResult, AgentTask, Orchestrator
from src.output_manager import OutputManager
from src.plan_normalizer import normalize_plan
from src.session import Session
from src.skills.code.manifest import WorkspaceManifest
from src.skills.code.sandbox import PythonSandbox, extract_exception_type
from src.skills.code.scientific_helpers import save_experiment_artifacts

# --- 1.1 contrato de artefatos ------------------------------------------------


@pytest.mark.unit
def test_save_experiment_artifacts_grava_datasets_e_baselines(tmp_path):
    save_experiment_artifacts(
        "t", {"seed": 1, "a": 2}, {"r2": 0.8}, output_dir=str(tmp_path),
        datasets=["dados.csv"], baselines={"r2": 0.7},
    )
    params = json.loads((tmp_path / "params.json").read_text(encoding="utf-8"))
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert params["datasets"] == ["dados.csv"]
    assert metrics["datasets"] == ["dados.csv"] and metrics["baselines"] == {"r2": 0.7}


@pytest.mark.unit
def test_save_experiment_artifacts_retrocompativel(tmp_path):
    save_experiment_artifacts("t", {"a": 1}, {"r2": 0.8}, output_dir=str(tmp_path), seed=3)
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["datasets"] == [] and metrics["baselines"] == {} and metrics["seed"] == 3


# --- 1.2 plano com approach ---------------------------------------------------


def _task(**extra):
    base = {"agent_id": "developer", "task_name": "t1", "prompt": "p", "validation_criteria": ["c"]}
    base.update(extra)
    return base


@pytest.mark.unit
def test_plano_aceita_approach_objeto_e_ausente():
    raw = {"nome": " gradient boosting ", "tipo": "algoritmo", "x": 1}
    plan = normalize_plan([_task(approach=raw), _task(task_name="t2")])
    assert plan.tasks[0]["approach"] == {"nome": "gradient boosting", "tipo": "algoritmo"}
    assert "approach" not in plan.tasks[1]
    assert not plan.unrecoverable


@pytest.mark.unit
def test_plano_approach_texto_vira_objeto_e_invalido_e_removido():
    plan = normalize_plan([_task(approach="random forest"), _task(task_name="t2", approach=42),
                           _task(task_name="t3", approach={"tipo": "algoritmo"})])
    assert plan.tasks[0]["approach"] == {"nome": "random forest"}
    assert "approach" not in plan.tasks[1] and "approach" not in plan.tasks[2]
    assert {r.kind for r in plan.repairs} >= {"coerce_approach"}


@pytest.mark.unit
def test_agent_task_tem_approach_opcional():
    assert AgentTask(agent_id="a", prompt="p").approach is None
    assert AgentTask(agent_id="a", prompt="p", approach={"nome": "x"}).approach == {"nome": "x"}


@pytest.mark.unit
def test_instrucoes_pedem_approach_datasets_e_baselines():
    from agents.developer.agent import AGENT_INSTRUCTION as dev
    from agents.researcher.agent import AGENT_INSTRUCTION as res

    assert "datasets" in dev and "baselines" in dev
    assert '"approach"' in res


# --- 1.4 sandbox estruturado --------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "stderr,expected",
    [
        ("Traceback (most recent call last):\n  File x\nMemoryError\n", "MemoryError"),
        ("Traceback (most recent call last):\n  File x\nValueError: bad\n", "ValueError"),
        ("Traceback (most recent call last):\nsklearn.exceptions.NotFittedError: x\n", "NotFittedError"),
        ("ValueError: sem traceback\n", None),
        ("Traceback (most recent call last):\n\x1b[31m@@ injeção\n", None),
        ("", None),
    ],
)
def test_extract_exception_type(stderr, expected):
    assert extract_exception_type(stderr) == expected


@pytest.fixture
def docker_client():
    with patch("src.skills.code.sandbox.docker.from_env") as mock_env:
        client = MagicMock()
        mock_env.return_value = client
        yield client


def _run_sandbox(client, tmp_path, *, exit_code, stderr=b""):
    container = MagicMock()
    client.containers.run.return_value = container
    exec_result = MagicMock()
    exec_result.output = (b"", stderr)
    exec_result.exit_code = exit_code
    container.exec_run.return_value = exec_result
    with patch("src.skills.code.sandbox.os.getuid", return_value=1000):
        return PythonSandbox().run(code="x", session_id="s1", task_name="t1", output_dir=str(tmp_path))


@pytest.mark.unit
def test_sandbox_devolve_excecao_estruturada(docker_client, tmp_path):
    result = _run_sandbox(
        docker_client, tmp_path, exit_code=1, stderr=b"Traceback (most recent call last):\n  File x\nMemoryError\n"
    )
    assert result.exception_type == "MemoryError" and result.oom_killed is False and result.infra_error is None


@pytest.mark.unit
def test_sandbox_exit_137_e_oom(docker_client, tmp_path):
    result = _run_sandbox(docker_client, tmp_path, exit_code=137)
    assert result.oom_killed is True and result.exit_code == 137


@pytest.mark.unit
def test_sandbox_sem_inicio_e_infraestrutura(docker_client, tmp_path):
    docker_client.containers.run.side_effect = ConnectionError("daemon fora")
    with patch("src.skills.code.sandbox.os.getuid", return_value=1000), patch(
        "src.skills.code.sandbox.RETRY_BACKOFFS_SECONDS", ()
    ):
        result = PythonSandbox().run(code="x", session_id="s1", task_name="t1", output_dir=str(tmp_path))
    assert result.infra_error == "docker_unavailable" and result.exit_code == -1


# --- manifest -----------------------------------------------------------------


@pytest.mark.unit
def test_manifest_registra_task_name_e_saida_estruturada(tmp_path):
    manifest = WorkspaceManifest(tmp_path, "s", "t1")
    manifest.record_step(
        1, "failed", [], "falhou", error={"error_type": "E"}, code_file="step_01.py", task_name="t1",
        run_info={"exit_code": 137, "oom_killed": True},
    )
    manifest.record_step(2, "success", [], "ok")  # chamadores antigos continuam válidos
    steps = manifest.read()["steps"]
    assert steps[0]["task_name"] == "t1" and steps[0]["run"]["oom_killed"] is True
    assert "task_name" not in steps[1] and "run" not in steps[1]


# --- ligação do laço autônomo -------------------------------------------------


def _session(sid="s1"):
    return Session(id=sid, agent_id="orchestrator", status="active", created_at="2025-01-01T00:00:00+00:00",
                   updated_at="2025-01-01T00:00:00+00:00", payload={})


def _orch(tmp_path, store):
    sm = MagicMock()
    sm.create.return_value = _session()
    sm.get.return_value = _session()
    runtime = MagicMock()
    runtime.run = AsyncMock(return_value=AgentResult(agent_id="a", session_id="s1", status="success", response={}))
    return Orchestrator(
        session_manager=sm, output_manager=OutputManager(str(tmp_path / "out"), str(tmp_path / "logs")),
        agent_runtime=runtime, knowledge_store_factory=lambda: store,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orquestrador_ingere_inicio_e_fim_da_sessao(tmp_path):
    store = InMemoryGraphStore()
    pid = create_project(store, "P", "O", [])
    orch = _orch(tmp_path, store)
    await orch.handle_request("p", [AgentTask(agent_id="a", prompt="p")], project_id=pid)
    (sessao,) = store.find_nodes("Sessao", {})
    assert sessao.properties["sessao_id"] == "s1"
    assert sessao.properties["motivo_parada"] == "solucao_encontrada"
    assert sessao.properties["fim"]
    assert orch.get_ingestor("s1") is None  # limpo no fim


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orquestrador_grafo_fora_nao_derruba_a_sessao(tmp_path):
    def _down():
        raise ConnectionError("grafo fora do ar")

    orch = _orch(tmp_path, InMemoryGraphStore())
    orch._knowledge_store_factory = _down
    pid = "01890000-0000-7000-8000-000000000001"
    result = await orch.handle_request("p", [AgentTask(agent_id="a", prompt="p")], project_id=pid)
    assert result.succeeded == 1
    pending = orch.output_manager.base_dir / "s1" / PENDING_FILENAME
    kinds = [json.loads(line)["kind"] for line in pending.read_text(encoding="utf-8").splitlines()]
    assert kinds == ["session_start", "session_end"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orquestrador_sem_projeto_nao_abre_o_grafo(tmp_path):
    opened = []
    orch = _orch(tmp_path, InMemoryGraphStore())
    orch._knowledge_store_factory = lambda: opened.append(1)
    await orch.handle_request("p", [AgentTask(agent_id="a", prompt="p")])
    assert opened == [] and orch.get_ingestor("s1") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_laco_ingere_subtarefa_revisada(tmp_path):
    store = InMemoryGraphStore()
    pid = create_project(store, "P", "O", [])
    orch = _orch(tmp_path, store)
    session_dir = orch.output_manager.base_dir / "s1"
    (session_dir / "treinar").mkdir(parents=True)
    (session_dir / "treinar" / "metrics.json").write_text(
        json.dumps({"metrics": {"r2": 0.8}, "baselines": {"r2": 0.7}}), encoding="utf-8")
    (session_dir / "treinar" / "params.json").write_text(
        json.dumps({"seed": 1, "parameters": {"n": 5, "seed": 1}}), encoding="utf-8")
    ingestor = orch._start_ingestor("s1", pid, "auto", "2026-10-06T10:00:00+00:00", None)
    ingestor.session_start()

    loop = AutonomousLoop(orch)
    task = AgentTask(agent_id="developer", prompt="p", task_name="treinar", subtask_id="sub-9",
                     validation_criteria=["r2 >= 0.75"], approach={"nome": "boosting", "tipo": "algoritmo"},
                     hypothesis="H", scientific_rationale="R")
    result = AgentResult(agent_id="developer", session_id="x", status="success", response={})
    await loop._ingest_subtask(task, result, {"status": "pass"}, "s1")

    (exp,) = store.find_nodes("Experimento", {})
    assert exp.properties["subtarefa_id"] == "sub-9" and exp.properties["status"] == "sucesso"
    (res,) = store.find_nodes("Resultado", {})
    assert res.properties["status_validacao"] == "validado" and res.properties["baseline"] == 0.7
    assert store.find_nodes("Abordagem", {})[0].properties["nome"] == "boosting"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_laco_ingestao_nao_levanta_com_orquestrador_sem_ingestor():
    orch = MagicMock()
    orch.get_ingestor.return_value = None
    loop = AutonomousLoop(orch)
    await loop._ingest_subtask(AgentTask(agent_id="developer", prompt="p", task_name="t"),
                               AgentResult(agent_id="d", session_id="x", status="error", response={}), None, "s1")


# --- 3.2 geminiclaw knowledge sync -------------------------------------------


@pytest.mark.unit
def test_cli_knowledge_sync_aplica_pendentes(tmp_path, capsys):
    from src import config
    from src.knowledge.ingestion import FactIngestor, SessionContext
    from src.knowledge.semantic_runtime import run_knowledge_command

    store = InMemoryGraphStore()
    pid = create_project(store, "P", "O", [])
    session_dir = tmp_path / "sessao-x"
    session_dir.mkdir()

    def _down():
        raise ConnectionError("fora")

    ctx = SessionContext(project_id=pid, session_id="sessao-x", modo="auto", inicio="x", no_execucao="n")
    FactIngestor(_down, ctx, session_dir).session_start()
    assert (session_dir / PENDING_FILENAME).exists()

    runtime = MagicMock(store=store)
    with patch.object(config, "OUTPUT_BASE_DIR", str(tmp_path)):
        assert run_knowledge_command(["sync", "--session", "sessao-x"], runtime=runtime) == 0
        assert run_knowledge_command(["sync", "--session", "../x"], runtime=runtime) == 1
    assert "1 aplicado" in capsys.readouterr().out
    assert len(store.find_nodes("Sessao", {})) == 1
    assert not (session_dir / PENDING_FILENAME).exists()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("exc,category", [(ConnectionError("rede"), "llm_connection"), (ValueError("x"), None)])
async def test_agent_runtime_marca_categoria_do_erro(monkeypatch, exc, category):
    """Erro de conexão com o provedor vira ``error_category`` estruturada (sem heurística de texto)."""
    from src.agent_runtime.context import AgentContext
    from src.agent_runtime.runtime import AgentRuntime

    async def failing(**kwargs):
        raise exc

    monkeypatch.setattr("src.agent_runtime.runtime.run_agent_loop", failing)
    monkeypatch.setattr("src.agent_runtime.runtime.ModelRouter.get_provider", lambda role, model=None: object())
    ctx = AgentContext(session_id="s", agent_session_id="a", agent_id="developer", mode="assisted",
                       output_dir=Path("/tmp/geminiclaw-test-outputs/s"), model="m")
    result = await AgentRuntime().run(AgentTask(agent_id="developer", prompt="p"), ctx)
    assert result.status == "error" and result.error_category == category
