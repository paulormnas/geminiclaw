import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.autonomous_loop import AutonomousLoop
from src.orchestrator import AgentResult, AgentTask, OrchestratorResult
from src.telemetry import TelemetryCollector
from src.usage import StopReason, UsageBudget, UsageTracker

def _narrative(resumo: str = "Summary") -> str:
    """Narrativa JSON válida do Summarizer (v16-pipeline-robustness §6)."""
    fields = ("contexto_e_objetivo", "metodologia", "analise_divergencias", "limitacoes", "proximos_passos")
    data = {f: "texto" for f in fields}
    data.update(resumo_executivo=resumo, confianca_nivel="alto", confianca_justificativa="dados completos")
    return json.dumps(data)


@pytest.fixture
def mock_telemetry():
    with patch("src.autonomous_loop.get_telemetry") as mock:
        instance = MagicMock()
        mock.return_value = instance
        yield instance

@pytest.fixture
def mock_orchestrator():
    orchestrator = MagicMock()
    orchestrator._execute_agent = AsyncMock()
    orchestrator._run_planning_loop = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    return orchestrator

@pytest.mark.asyncio
async def test_autonomous_loop_simple_path():
    orchestrator = MagicMock()
    orchestrator._execute_agent = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    
    # Mock base execution result
    base_result = AgentResult(agent_id="base", session_id="s2", status="success", response={"text": "Hello"})
    orchestrator._execute_agent.side_effect = [base_result]
    
    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=False)):
        loop = AutonomousLoop(orchestrator)
        result = await loop.run("Hi", "m1")
    
    assert result.total == 1
    assert result.succeeded == 1
    assert result.results[0].agent_id == "base"
    assert orchestrator._execute_agent.call_count == 1

@pytest.mark.asyncio
async def test_autonomous_loop_complex_path_success(mock_telemetry):
    orchestrator = MagicMock()
    orchestrator._execute_agent = AsyncMock()
    orchestrator._run_planning_loop = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    
    # planning
    task1 = AgentTask(agent_id="researcher", prompt="search")
    orchestrator._run_planning_loop.return_value = [task1]
    
    # execution success
    success_result = AgentResult(agent_id="researcher", session_id="s2", status="success", response={"text": "data"})
    
    # promotion
    promo_result = AgentResult(agent_id="planner", session_id="s3", status="success", response={})
    
    # synthesis
    synth_result = AgentResult(agent_id="summarizer", session_id="s4", status="success", response={"text": _narrative()})

    orchestrator._execute_agent.side_effect = [success_result, promo_result, synth_result]
    
    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)), \
         patch("src.autonomous_loop.get_telemetry", return_value=mock_telemetry), \
         patch("src.config.REVIEW_ENABLED", False):
        loop = AutonomousLoop(orchestrator)
        result = await loop.run("Complex task", "m1")
    
    assert result.total == 1
    assert result.succeeded == 1
    assert orchestrator._execute_agent.call_count == 3

@pytest.mark.asyncio
async def test_autonomous_loop_complex_path_retry_success(mock_telemetry):
    orchestrator = MagicMock()
    orchestrator._execute_agent = AsyncMock()
    orchestrator._run_planning_loop = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    
    # planning
    task1 = AgentTask(agent_id="researcher", prompt="search")
    orchestrator._run_planning_loop.return_value = [task1]
    
    # execution: fail, then success
    fail_result = AgentResult(agent_id="researcher", session_id="s2", status="error", response={}, error="timeout")
    success_result = AgentResult(agent_id="researcher", session_id="s2", status="success", response={"text": "data"})
    
    # promotion
    promo_result = AgentResult(agent_id="planner", session_id="s3", status="success", response={})

    # synthesis
    synth_result = AgentResult(agent_id="summarizer", session_id="s4", status="success", response={"text": _narrative()})

    orchestrator._execute_agent.side_effect = [fail_result, success_result, promo_result, synth_result]
    
    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)), \
         patch("src.autonomous_loop.get_telemetry", return_value=mock_telemetry), \
         patch("src.config.REVIEW_ENABLED", False):
        loop = AutonomousLoop(orchestrator)
        loop.max_retries = 2
        # Mock sleep to speed up test
        with patch("asyncio.sleep", AsyncMock()):
            result = await loop.run("Complex task", "m1")
    
    assert result.total == 1
    assert result.succeeded == 1
    assert orchestrator._execute_agent.call_count == 4

@pytest.mark.asyncio
async def test_autonomous_loop_complex_path_fail_after_retries():
    orchestrator = MagicMock()
    orchestrator._execute_agent = AsyncMock()
    orchestrator._run_planning_loop = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    
    # planning
    task1 = AgentTask(agent_id="researcher", prompt="search")
    orchestrator._run_planning_loop.return_value = [task1]
    
    # execution: fail twice
    fail_result = AgentResult(agent_id="researcher", session_id="s2", status="error", response={}, error="timeout")
    
    orchestrator._execute_agent.side_effect = [fail_result, fail_result]
    
    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)), \
         patch("src.config.REVIEW_ENABLED", False):
        loop = AutonomousLoop(orchestrator)
        loop.max_retries = 2
        with patch("asyncio.sleep", AsyncMock()):
            result = await loop.run("Complex task", "m1")
    
    assert result.total == 1
    assert result.succeeded == 0
    assert orchestrator._execute_agent.call_count == 2 # 2 attempts

@pytest.mark.asyncio
async def test_autonomous_loop_reviewer_fail_then_success(mock_orchestrator, mock_telemetry):
    """Testa se uma falha na revisão causa retry da subtarefa.

    V18/usage-limits (design §2): retentativas da MESMA tarefa agora são contadas
    cumulativamente pelo UsageTracker entre ciclos de replanejamento (não mais um
    contador local reiniciado a cada dispatch). Com ``max_task_retries=2``, a
    tarefa tem exatamente 2 tentativas GLOBAIS: a 1a (ciclo de plano 1) falha na
    revisão; a 2a (ciclo de plano 2, reprocessada via recuperação incremental)
    passa. Usa objetos `AgentResult` distintos por tentativa (não reaproveitados)
    para evitar mutação cruzada entre chamadas do mock.
    """
    # Task com critérios de validação
    task1 = AgentTask(agent_id="researcher", prompt="search", task_name="t1", validation_criteria=["C1"])
    mock_orchestrator._run_planning_loop.return_value = [task1]

    # 1a tentativa: sucesso técnico, mas reprovada na revisão.
    success_result_1 = AgentResult(agent_id="researcher", session_id="s1", status="success", response={"text": "data"})
    # 2a tentativa (cumulativa, ciclo de plano 2): sucesso técnico e aprovada na revisão.
    success_result_2 = AgentResult(agent_id="researcher", session_id="s1", status="success", response={"text": "data2"})

    # Promoção
    promo_result = AgentResult(agent_id="planner", session_id="s5", status="success", response={})

    # Síntese
    synth_result = AgentResult(agent_id="summarizer", session_id="s5", status="success", response={"text": _narrative()})

    mock_orchestrator._execute_agent.side_effect = [
        success_result_1,  # 1a tentativa — review reprova
        success_result_2,  # 2a tentativa (cumulativa) — review aprova
        promo_result,
        synth_result,
    ]

    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)), \
         patch.object(AutonomousLoop, "_review_subtask", AsyncMock(side_effect=[{"status": "fail", "issues": ["error"]}, {"status": "pass"}])), \
         patch("src.config.REVIEW_ENABLED", True), \
         patch("src.config.REVIEW_MODE", "per_subtask"):

        budget = UsageBudget(
            max_tokens=500_000, max_minutes=120, max_task_retries=2,
            max_connection_retries=20, closing_reserve_pct=0.05,
        )
        loop = AutonomousLoop(mock_orchestrator)
        result = await loop.run("Complex task", "m1", budget=budget)

    assert result.succeeded == 1
    # 2 tentativas do researcher (cumulativas entre ciclos) + Promoção + Síntese = 4 chamadas.
    assert mock_orchestrator._execute_agent.call_count == 4

@pytest.mark.unit
@pytest.mark.asyncio
async def test_autonomous_loop_synthesis(mock_orchestrator, mock_telemetry):
    """Testa se a fase de síntese final é acionada e inclui metadados."""
    loop = AutonomousLoop(mock_orchestrator)
    
    # Mock para o Summarizer
    mock_orchestrator._execute_agent.side_effect = [
        # Planner (Plano) - O orchestrator._run_planning_loop usa isso.
        # Mas aqui o AutonomousLoop._run_complex_path chama orchestrator._run_planning_loop direto.
        # E o orchestrator._run_planning_loop está mockado no fixture!
        
        # Researcher (Execução)
        AgentResult(agent_id="researcher", session_id="s1", status="success", response={"text": "r1"}),
        
        # Planner (Promotion)
        AgentResult(agent_id="planner", session_id="s1", status="success", response={}),
        # Summarizer (Síntese)
        AgentResult(agent_id="summarizer", session_id="s1", status="success", response={"text": _narrative("Final Summary")}),
    ]
    
    mock_orchestrator._run_planning_loop.return_value = [
        AgentTask(agent_id="researcher", prompt="p1", task_name="t1")
    ]
    
    mock_telemetry.get_summarized_stats.return_value = "Stats: 100 tokens"
    
    with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)), \
         patch("src.config.REVIEW_ENABLED", False):
        result = await loop.run("Complex task", "master_s1")
    
    assert result.succeeded >= 1
    # Researcher, Promotion, Summarizer -> 3 chamadas via _execute_agent
    assert mock_orchestrator._execute_agent.call_count == 3
    
    # Verifica se o resumo final está nos resultados
    assert any("Final Summary" in r.response.get("text", "") for r in result.results)


# ---------------------------------------------------------------------------
# V18/usage-limits — fechamento gracioso por limite de orçamento
# (src/usage.py UsageBudget/UsageTracker como condições de parada reais)
# ---------------------------------------------------------------------------


def _make_closing_test_orchestrator(tasks):
    """Orchestrator mínimo para exercitar `_close_session` sem tocar Postgres real."""
    orchestrator = MagicMock()
    orchestrator._run_planning_loop = AsyncMock(return_value=tasks)
    orchestrator._execute_agent = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    orchestrator.session_manager = MagicMock()
    orchestrator.session_manager.get.return_value = None
    return orchestrator


@pytest.mark.unit
@pytest.mark.asyncio
async def test_autonomous_loop_closes_session_when_token_budget_exhausted():
    """V18/usage-limits (design §3): se o orçamento de tokens já está esgotado
    (>= exploration_token_ceiling) antes do ciclo de planejamento, a sessão
    fecha graciosamente SEM despachar nenhuma chamada de exploração, e
    `motivo_parada='limite_tokens'` é gravado no payload da sessão.

    Como aqui o consumo (1000) também esgota `max_tokens` (sem sobrar nem a
    reserva de fechamento), cobre também design §3 "Reserva esgotada": o
    checkpoint determinístico é gravado com `consolidation_pending=True` e a
    consolidação via LLM (Summarizer) NÃO é tentada (5.6)."""
    task1 = AgentTask(agent_id="researcher", prompt="p1", task_name="t1")
    orchestrator = _make_closing_test_orchestrator([task1])

    loop = AutonomousLoop(orchestrator)
    budget = UsageBudget(
        max_tokens=1000, max_minutes=120, max_task_retries=3,
        max_connection_retries=20, closing_reserve_pct=0.05,
    )
    # exploration_token_ceiling = 950; já no teto — e também == max_tokens (reserva esgotada).
    loop._usage_tracker = UsageTracker(
        budget, execution_id="exec_tokens",
        token_reader=lambda: 1000,
        connection_retry_reader=lambda: 0,
        clock=lambda: 0.0,
    )

    with patch("src.autonomous_loop.get_telemetry", return_value=MagicMock()), \
         patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)):
        result = await loop._run_complex_path("tarefa", "exec_tokens")

    orchestrator._run_planning_loop.assert_not_called()
    orchestrator._execute_agent.assert_not_called()  # sem consolidação via LLM (reserva esgotada)
    assert result.succeeded == 0

    update_kwargs = orchestrator.session_manager.update.call_args.kwargs
    assert update_kwargs["payload"]["motivo_parada"] == StopReason.TOKENS.value
    assert update_kwargs["payload"]["checkpoint"]["consolidation_pending"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_autonomous_loop_closes_session_when_connection_retries_exhausted():
    """V18/usage-limits (design §3): retentativas de conexão esgotadas fecham a
    sessão com `motivo_parada='limite_conexao'` (problema de infraestrutura, não
    de uma tarefa específica)."""
    task1 = AgentTask(agent_id="researcher", prompt="p1", task_name="t1")
    orchestrator = _make_closing_test_orchestrator([task1])

    loop = AutonomousLoop(orchestrator)
    budget = UsageBudget(
        max_tokens=500_000, max_minutes=120, max_task_retries=3,
        max_connection_retries=20, closing_reserve_pct=0.05,
    )
    loop._usage_tracker = UsageTracker(
        budget, execution_id="exec_conn",
        token_reader=lambda: 0,
        connection_retry_reader=lambda: 20,  # no limite
        clock=lambda: 0.0,
    )

    with patch("src.autonomous_loop.get_telemetry", return_value=MagicMock()), \
         patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)):
        result = await loop._run_complex_path("tarefa", "exec_conn")

    orchestrator._run_planning_loop.assert_not_called()
    assert result.succeeded == 0

    update_kwargs = orchestrator.session_manager.update.call_args.kwargs
    assert update_kwargs["payload"]["motivo_parada"] == StopReason.CONNECTION.value


@pytest.mark.unit
@pytest.mark.asyncio
async def test_autonomous_loop_time_limit_cancels_pending_and_closes_session():
    """V18/usage-limits (design §2-3): quando o tempo de relógio da sessão se
    esgota durante a execução do ciclo, subtarefas em andamento têm até
    LIMIT_GRACE_SECONDS para terminar; se excederem, o ciclo é cancelado e a
    sessão fecha com `motivo_parada='limite_tempo'`.

    Usa orçamento de tempo e carência muito pequenos (tempo de relógio REAL,
    não um clock injetado) para que o teste seja rápido e, ao mesmo tempo,
    robusto a mudanças no número de verificações internas de `UsageTracker.check()`."""
    task_lenta = AgentTask(agent_id="base", prompt="p1", task_name="lenta")
    orchestrator = _make_closing_test_orchestrator([task_lenta])

    async def never_finishes(task, master_session_id=None):
        await asyncio.sleep(5)  # nunca terminaria dentro da carência de teste

    orchestrator._execute_agent = AsyncMock(side_effect=never_finishes)

    loop = AutonomousLoop(orchestrator)
    # max_minutes=0.002min=120ms de orçamento; sem readers customizados —
    # usa o clock real (time.monotonic) via UsageTracker default.
    budget = UsageBudget(
        max_tokens=500_000, max_minutes=0.002, max_task_retries=3,
        max_connection_retries=20, closing_reserve_pct=0.0,
    )
    loop._usage_tracker = UsageTracker(
        budget, execution_id="exec_time",
        token_reader=lambda: 0,
        connection_retry_reader=lambda: 0,
    )

    with patch("src.autonomous_loop.get_telemetry", return_value=MagicMock()), \
         patch("src.autonomous_loop.LIMIT_GRACE_SECONDS", 0.05), \
         patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)):
        result = await loop._run_complex_path("tarefa lenta", "exec_time")

    assert result.succeeded == 0

    update_kwargs = orchestrator.session_manager.update.call_args.kwargs
    assert update_kwargs["payload"]["motivo_parada"] == StopReason.TIME.value


@pytest.mark.unit
@pytest.mark.asyncio
async def test_autonomous_loop_all_tasks_abandoned_closes_session_with_retries_reason():
    """V18/usage-limits (design §3): se TODAS as tarefas pendentes de um ciclo
    forem abandonadas por esgotamento de retentativas (nenhum progresso), a
    sessão inteira fecha com `motivo_parada='limite_retentativas'`."""
    task_falha = AgentTask(agent_id="base", prompt="p1", task_name="sempre_falha")
    orchestrator = _make_closing_test_orchestrator([task_falha])

    orchestrator._execute_agent = AsyncMock(
        return_value=AgentResult(
            agent_id="base", session_id="s1", status="error", response={}, error="erro persistente",
        )
    )

    loop = AutonomousLoop(orchestrator)
    budget = UsageBudget(
        max_tokens=500_000, max_minutes=120, max_task_retries=1,
        max_connection_retries=20, closing_reserve_pct=0.05,
    )
    loop._usage_tracker = UsageTracker(
        budget, execution_id="exec_retries",
        token_reader=lambda: 0,
        connection_retry_reader=lambda: 0,
        clock=lambda: 0.0,
    )

    with patch("src.autonomous_loop.get_telemetry", return_value=MagicMock()), \
         patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)):
        result = await loop._run_complex_path("tarefa", "exec_retries")

    assert result.succeeded == 0
    assert "sempre_falha" in loop._usage_tracker.abandoned_tasks

    update_kwargs = orchestrator.session_manager.update.call_args.kwargs
    assert update_kwargs["payload"]["motivo_parada"] == StopReason.RETRIES.value


@pytest.mark.unit
@pytest.mark.asyncio
async def test_autonomous_loop_does_not_redispatch_task_abandoned_in_earlier_cycle():
    """V18/usage-limits — code review do PR #68 (apontamento importante 1):
    `UsageTracker.is_task_abandoned()` precisa ser checado ANTES do despacho em
    `_execute_task_in_dag`. Sem esse guard, uma tarefa abandonada por
    esgotamento de retentativas em um ciclo de planejamento poderia ser
    reintroduzida (mesmo `task_name`) por um ciclo de recuperação incremental
    subsequente e ser redespachada com tentativas "novas", ultrapassando
    `SESSION_MAX_TASK_RETRIES` de forma cumulativa.

    Cenário: ciclo 1 tem `t_abandon` (que sempre falha, com
    `max_task_retries=1` — abandonada já na 1ª tentativa) e `b` (depende de
    `t_abandon`, portanto cancelada quando a dependência não termina em
    sucesso). `b` cancelada faz `failed_tasks` não-vazio, disparando um 2º
    ciclo de planejamento (recuperação incremental) que reintroduz
    `t_abandon` sozinha. O guard deve impedir um novo despacho: nenhuma
    chamada adicional a `_execute_agent` deve ocorrer no 2º ciclo."""
    task_abandon = AgentTask(agent_id="base", prompt="p1", task_name="t_abandon")
    task_b = AgentTask(
        agent_id="base", prompt="p2", task_name="b", depends_on=["t_abandon"],
    )

    orchestrator = MagicMock()
    # Ciclo 1: t_abandon + b (dependente). Ciclo 2: t_abandon reintroduzida sozinha
    # pela recuperação incremental (mesmo task_name).
    orchestrator._run_planning_loop = AsyncMock(
        side_effect=[[task_abandon, task_b], [task_abandon]]
    )
    orchestrator._execute_agent = AsyncMock(
        return_value=AgentResult(
            agent_id="base", session_id="s1", status="error", response={}, error="erro persistente",
        )
    )
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    orchestrator.session_manager = MagicMock()
    orchestrator.session_manager.get.return_value = None

    loop = AutonomousLoop(orchestrator)
    budget = UsageBudget(
        max_tokens=500_000, max_minutes=120, max_task_retries=1,
        max_connection_retries=20, closing_reserve_pct=0.05,
    )
    loop._usage_tracker = UsageTracker(
        budget, execution_id="exec_reintro",
        token_reader=lambda: 0,
        connection_retry_reader=lambda: 0,
        clock=lambda: 0.0,
    )

    with patch("src.autonomous_loop.get_telemetry", return_value=MagicMock()), \
         patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)):
        result = await loop._run_complex_path("tarefa", "exec_reintro")

    # Reproduz o gap do apontamento 1: sem o guard, o 2º ciclo despacharia
    # `t_abandon` de novo (2ª chamada a _execute_agent). Com o guard, a
    # tarefa já abandonada nunca é redespachada — apenas a 1 chamada do
    # ciclo 1 deve existir.
    assert orchestrator._execute_agent.call_count == 1
    assert orchestrator._run_planning_loop.call_count == 2
    assert result.succeeded == 0
    assert "t_abandon" in loop._usage_tracker.abandoned_tasks

    update_kwargs = orchestrator.session_manager.update.call_args.kwargs
    assert update_kwargs["payload"]["motivo_parada"] == StopReason.RETRIES.value
