"""Disjuntor de progresso e limites de execução (v16-pipeline-robustness §4 e §5)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.autonomous_loop import AutonomousLoop, CycleProgress, error_signature
from src.orchestrator import AgentResult, AgentTask, Orchestrator
from src.pipeline_errors import AgentRunLimitReached
from src.usage import StopReason

pytestmark = pytest.mark.unit


# --- Disjuntor -------------------------------------------------------------------------------

def test_erro_diferente_e_progresso():
    """Scenario: Erro diferente é progresso."""
    before = CycleProgress(frozenset(), frozenset({error_signature("a", "Falha na revisão: critério x")}))
    after = CycleProgress(frozenset(), frozenset({error_signature("a", "Falha na revisão: critério y")}))
    assert after.advanced_from(before)


def test_mesmo_erro_sem_sucessos_novos_nao_e_progresso():
    sig = frozenset({error_signature("a", "erro")})
    assert not CycleProgress(frozenset({"b"}), sig).advanced_from(CycleProgress(frozenset({"b"}), sig))


def test_sucesso_novo_e_progresso():
    sig = frozenset({error_signature("a", "erro")})
    assert CycleProgress(frozenset({"b"}), sig).advanced_from(CycleProgress(frozenset(), sig))


def test_assinatura_ignora_numeros_e_caminhos():
    """Scenario: Assinatura ignora números e caminhos."""
    one = error_signature("t", "Falha na revisão: acurácia 0.91 abaixo de 0.95 em /outputs/t/a.json")
    two = error_signature("t", "Falha na revisão: acurácia 0.88 abaixo de 0.95 em /outputs/t/b.json")
    assert one == two


def test_assinatura_distingue_revisao_de_agente():
    assert error_signature("t", "Falha na revisão: x") != error_signature("t", "x")


def _stalling_loop():
    """Plano com A (falha sempre) e B (depende de A): A é abandonada e B cancelada a cada ciclo."""
    tasks = [
        AgentTask(agent_id="base", prompt="a", task_name="a"),
        AgentTask(agent_id="base", prompt="b", task_name="b", depends_on=["a"]),
    ]
    calls = {"planning": 0}

    async def planning(*args, **kwargs):
        calls["planning"] += 1
        return list(tasks)

    async def execute(task, master_session_id=None):
        return AgentResult(agent_id="base", session_id="s", status="error", response={}, error="falhou")

    orch = MagicMock()
    orch._execute_agent = execute
    orch._run_planning_loop = planning
    orch.output_manager = MagicMock()
    orch.output_manager.list_artifacts.return_value = []
    return AutonomousLoop(orch), calls


@pytest.mark.asyncio
async def test_dois_ciclos_identicos_encerram_com_stalled_cycles():
    """Scenario: Dois ciclos idênticos / Primeiro ciclo."""
    loop, calls = _stalling_loop()
    with patch("src.autonomous_loop.get_telemetry") as tel, \
            patch("src.autonomous_loop.asyncio.sleep", AsyncMock()), \
            patch("src.autonomous_loop.CIRCUIT_BREAKER_STALL_CYCLES", 2):
        with patch.object(loop, "_is_complex_triage", AsyncMock(return_value=True)):
            result = await loop.run("tarefa", "exec_stall")
    assert calls["planning"] == 3  # ciclo 1 nunca dispara; 2 e 3 contam como estagnados
    events = [c.kwargs for c in tel.return_value.record_agent_event.call_args_list
              if c.kwargs.get("event_type") == "circuit_breaker"]
    assert events and events[0]["payload"]["stalled_cycles"] == 2
    assert any("progresso" in (r.response.get("text") or "").lower() for r in result.results)


@pytest.mark.asyncio
async def test_um_ciclo_identico_nao_encerra_com_padrao_dois():
    loop, calls = _stalling_loop()
    with patch("src.autonomous_loop.get_telemetry"), patch("src.autonomous_loop.asyncio.sleep", AsyncMock()), \
            patch("src.autonomous_loop.CIRCUIT_BREAKER_STALL_CYCLES", 3):
        with patch.object(loop, "_is_complex_triage", AsyncMock(return_value=True)):
            await loop.run("tarefa", "exec_stall2")
    assert calls["planning"] == 4


# --- Limites de execução ----------------------------------------------------------------------

def _orch():
    session_manager = MagicMock()
    session_manager.create = MagicMock(return_value=MagicMock(id="sess_abc"))
    runtime = MagicMock()
    runtime.run = AsyncMock(return_value=AgentResult(agent_id="base", session_id="s", status="success",
                                                     response={"text": "ok"}))
    orch = Orchestrator(session_manager=session_manager, agent_runtime=runtime)
    orch.rate_limiter.acquire = AsyncMock()
    return orch


def _task():
    return AgentTask(agent_id="base", prompt="x", task_name="t")


@pytest.mark.asyncio
async def test_planejamento_nao_consome_o_limite_de_subtarefas():
    """Scenario: Planejamento não consome o limite de subtarefas."""
    orch = _orch()
    with patch("src.orchestrator.get_telemetry"):
        for _ in range(12):
            await orch._execute_agent(_task(), "m", run_kind="planning")
    assert orch._session_planning_run_counts["m"] == 12
    assert orch._session_agent_run_counts.get("m", 0) == 0


def test_limite_acompanha_o_plano():
    """Scenario: Limite acompanha o plano."""
    orch = _orch()
    orch._session_plan_size["m"] = 10
    with patch("src.orchestrator.MAX_AGENT_RUNS_PER_SESSION", 30), \
            patch("src.orchestrator.SESSION_MAX_TASK_RETRIES", 3):
        assert orch.effective_run_limit("m") == 42
        assert orch.effective_run_limit("sem_plano") == 30


@pytest.mark.asyncio
async def test_limite_de_planejamento_levanta_erro_tipado():
    orch = _orch()
    with patch("src.orchestrator.MAX_PLANNING_RUNS_PER_SESSION", 2), patch("src.orchestrator.get_telemetry"):
        await orch._execute_agent(_task(), "m", run_kind="planning")
        await orch._execute_agent(_task(), "m", run_kind="planning")
        with pytest.raises(AgentRunLimitReached) as err:
            await orch._execute_agent(_task(), "m", run_kind="planning")
    assert err.value.kind == "planning" and err.value.limit == 2 and err.value.count == 2


@pytest.mark.asyncio
async def test_sessao_fecha_com_limite_execucoes_ao_estourar_o_planejamento():
    """Scenario: Limite de planejamento atingido."""
    orch = MagicMock()
    orch._run_planning_loop = AsyncMock(side_effect=AgentRunLimitReached("planning", 20, 20, "s"))
    orch.output_manager = MagicMock()
    orch.output_manager.list_artifacts.return_value = []
    loop = AutonomousLoop(orch)
    close = AsyncMock(return_value="fechada")
    with patch("src.autonomous_loop.get_telemetry") as tel, patch.object(loop, "_close_session", close):
        with patch.object(loop, "_is_complex_triage", AsyncMock(return_value=True)):
            result = await loop.run("tarefa", "exec_lim")
    assert result == "fechada"
    assert close.call_args.args[0] == StopReason.RUNS and StopReason.RUNS.value == "limite_execucoes"
    payloads = [c.kwargs["payload"] for c in tel.return_value.record_agent_event.call_args_list
                if c.kwargs.get("event_type") == "limit_reached"]
    assert payloads[0]["limit"] == "agent_runs" and payloads[0]["kind"] == "planning"


@pytest.mark.asyncio
async def test_sessao_fecha_com_consolidacao_ao_estourar_a_execucao_sem_excecao():
    """Scenario: Limite de execução atingido."""
    orch = MagicMock()
    orch._run_planning_loop = AsyncMock(return_value=[AgentTask(agent_id="base", prompt="x", task_name="t")])
    orch._execute_agent = AsyncMock(side_effect=AgentRunLimitReached("execution", 30, 30, "s"))
    orch.output_manager = MagicMock()
    orch.output_manager.list_artifacts.return_value = []
    loop = AutonomousLoop(orch)
    close = AsyncMock(return_value="fechada")
    with patch("src.autonomous_loop.get_telemetry"), patch.object(loop, "_close_session", close):
        with patch.object(loop, "_is_complex_triage", AsyncMock(return_value=True)):
            result = await loop.run("tarefa", "exec_lim2")
    assert result == "fechada" and close.call_args.args[0] == StopReason.RUNS
