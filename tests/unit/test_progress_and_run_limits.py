"""Disjuntor de progresso e limites de execução (v16-pipeline-robustness §4 e §5)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestration.autonomous_loop import AutonomousLoop, CycleProgress, error_signature
from src.orchestration.orchestrator import AgentResult, AgentTask, Orchestrator

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
    with patch("src.orchestration.autonomous_loop.get_telemetry") as tel, \
            patch("src.orchestration.autonomous_loop.asyncio.sleep", AsyncMock()), \
            patch("src.orchestration.autonomous_loop.CIRCUIT_BREAKER_STALL_CYCLES", 2):
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
    with patch("src.orchestration.autonomous_loop.get_telemetry"), patch("src.orchestration.autonomous_loop.asyncio.sleep", AsyncMock()), \
            patch("src.orchestration.autonomous_loop.CIRCUIT_BREAKER_STALL_CYCLES", 3):
        with patch.object(loop, "_is_complex_triage", AsyncMock(return_value=True)):
            await loop.run("tarefa", "exec_stall2")
    assert calls["planning"] == 4


# --- Execuções sem limite ---------------------------------------------------------------------

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
    with patch("src.orchestration.orchestrator.get_telemetry"):
        for _ in range(12):
            await orch._execute_agent(_task(), "m", run_kind="planning")
    assert orch._session_planning_run_counts["m"] == 12
    assert orch._session_agent_run_counts.get("m", 0) == 0


@pytest.mark.asyncio
async def test_muitas_execucoes_nao_encerram_a_sessao():
    """Scenario: Muitas execuções não encerram a sessão (ADR 021 §5.1)."""
    orch = _orch()
    orch._session_agent_run_counts["m"] = 45
    orch._session_planning_run_counts["m"] = 25
    with patch("src.orchestration.orchestrator.get_telemetry"):
        result = await orch._execute_agent(_task(), "m")
    assert result.status == "success"
    assert orch._session_agent_run_counts["m"] == 46 and orch._session_planning_run_counts["m"] == 25


def test_nao_ha_mais_limite_de_execucoes_no_codigo():
    from src.orchestration import errors, usage

    assert not hasattr(errors, "AgentRunLimitReached") and not hasattr(Orchestrator, "effective_run_limit")
    assert "limite_execucoes" not in {reason.value for reason in usage.StopReason}


@pytest.mark.asyncio
async def test_contagens_de_execucao_vao_para_as_metricas_de_operacao():
    """Scenario: ``custo_recursos.execucoes_agente`` registra planejamento e execução no fechamento."""
    from src.report.operation_metrics import CostResourcesReader

    orch = MagicMock()
    orch._session_planning_run_counts = {"m": 25}
    orch._session_agent_run_counts = {"m": 46}
    payloads: dict = {}
    orch.session_manager.get.side_effect = lambda sid: MagicMock(payload=dict(payloads))
    orch.session_manager.update.side_effect = lambda sid, payload: payloads.update(payload)
    loop = AutonomousLoop(orch)
    with patch("src.orchestration.loop_report.get_telemetry") as tel, patch(
        "src.report.operation_metrics.aggregate_operation_metrics", return_value={}
    ):
        tel.return_value.flush = AsyncMock()
        await loop.record_operation_metrics("m", parcial=False)
    assert payloads["execucoes_agente"] == {"planejamento": 25, "execucao": 46}

    reader = CostResourcesReader(runs_loader=lambda sid: payloads["execucoes_agente"])
    with patch("src.observability.telemetry.get_telemetry") as tel:
        tel.return_value.get_usage_by_task.return_value = []
        tel.return_value.get_hardware_peaks.return_value = {}
        tel.return_value.get_average_cpu.return_value = None
        assert reader.read("m")["execucoes_agente"] == {"planejamento": 25, "execucao": 46}
