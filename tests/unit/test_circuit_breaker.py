"""Testes unitários para V12.5 — Circuit Breaker e Detecção de Progresso Zero.

Cobre:
  V12.5.1: Detecção de progresso zero — dois ciclos consecutivos com o mesmo
           conjunto de subtarefas bem-sucedidas abortavam o loop com mensagem
           explicativa. V18/usage-limits (design §3) SUBSTITUI esse
           comportamento para o caso de uma única subtarefa persistentemente
           falha: ela agora é ABANDONADA (SESSION_MAX_TASK_RETRIES esgotado,
           contado cumulativamente entre ciclos — ver src/usage.py), e o
           restante do DAG e a sessão continuam, em vez de abortar a sessão
           inteira. Ver `test_persistent_task_failure_is_abandoned_not_session_aborted`.
  V12.5.2: Limite de execuções de agente por sessão — ao atingir o limite efetivo em
           _execute_agent, levanta AgentRunLimitReached (subclasse de RuntimeError) com mensagem
           descritiva; o AutonomousLoop a captura e fecha a sessão com consolidação
           (v16-pipeline-robustness §5; ver tests/unit/test_progress_and_run_limits.py).
  v16-pipeline-robustness §4: o disjuntor de "zero progresso" só dispara após
           CIRCUIT_BREAKER_STALL_CYCLES ciclos sem mudança de sucessos nem de erros.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# V12.5.1 — Detecção de progresso zero (comportamento substituído por V18 para
# o caso de uma única tarefa persistentemente falha — ver módulo acima)
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_persistent_task_failure_is_abandoned_not_session_aborted():
    """V18/usage-limits (design §3): uma subtarefa que esgota
    SESSION_MAX_TASK_RETRIES é ABANDONADA — não aciona mais o antigo circuit
    breaker de progresso zero (V12.5.1), que abortava a sessão inteira. O
    restante do DAG ('tarefa_ok', independente) e a sessão continuam
    normalmente."""
    from src.orchestrator import AgentTask, AgentResult
    from src.autonomous_loop import AutonomousLoop
    from src.usage import UsageBudget

    # Planner sempre retorna o mesmo plano com as mesmas 2 tarefas independentes
    tarefas = [
        AgentTask(
            agent_id="base",
            prompt="tarefa 1",
            task_name="tarefa_ok",
        ),
        AgentTask(
            agent_id="base",
            prompt="tarefa 2",
            task_name="tarefa_falha",
        ),
    ]

    async def mock_execute(task, master_session_id=None):
        # tarefa_ok sempre sucesso, tarefa_falha sempre falha
        if task.task_name == "tarefa_ok":
            return AgentResult(
                agent_id=task.agent_id,
                session_id="s1",
                status="success",
                response={"text": "ok"},
            )
        return AgentResult(
            agent_id=task.agent_id,
            session_id="s1",
            status="error",
            response={},
            error="erro persistente",
        )

    mock_orchestrator = MagicMock()
    mock_orchestrator._execute_agent = mock_execute
    mock_orchestrator._run_planning_loop = AsyncMock(return_value=tarefas)
    mock_orchestrator.output_manager = MagicMock()
    mock_orchestrator.output_manager.list_artifacts.return_value = []

    loop = AutonomousLoop(mock_orchestrator)
    budget = UsageBudget(
        max_tokens=500_000, max_minutes=120, max_task_retries=1,
        max_connection_retries=20, closing_reserve_pct=0.05,
    )

    with patch("src.autonomous_loop.get_telemetry", return_value=MagicMock()):
        with patch.object(loop, "_is_complex_triage", AsyncMock(return_value=True)):
            result = await loop.run("tarefa complexa", "exec_test", budget=budget)

    # tarefa_ok concluiu com sucesso; tarefa_falha foi abandonada (não "failed"),
    # então a sessão NÃO aborta com uma mensagem de circuit breaker.
    assert result.succeeded == 1
    assert "tarefa_falha" in loop._usage_tracker.abandoned_tasks
    final_texts = " ".join(
        r.response.get("text", "") or ""
        for r in result.results
    )
    assert "progresso" not in final_texts.lower(), (
        f"Circuit breaker antigo (V12.5.1) não deveria mais ser acionado. Textos: {final_texts}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_breaker_nao_aborta_com_progresso_real():
    """Se o progresso muda entre ciclos (nova subtarefa bem-sucedida),
    o loop deve continuar normalmente."""
    from src.orchestrator import AgentTask, AgentResult
    from src.autonomous_loop import AutonomousLoop

    ciclo = [0]

    async def mock_planning_loop(*args, **kwargs):
        ciclo[0] += 1
        if ciclo[0] == 1:
            return [
                AgentTask(
                    agent_id="base",
                    prompt="etapa 1",
                    task_name="etapa_1",
                ),
                AgentTask(
                    agent_id="base",
                    prompt="etapa 2 — vai falhar",
                    task_name="etapa_2",
                ),
            ]
        # Segundo ciclo: só a etapa_2 precisa ser re-executada e agora passa
        return [
            AgentTask(
                agent_id="base",
                prompt="etapa 2 — revisada",
                task_name="etapa_2",
            ),
        ]

    async def mock_execute(task, master_session_id=None):
        if task.task_name == "etapa_1":
            return AgentResult(
                agent_id=task.agent_id,
                session_id="s1",
                status="success",
                response={"text": "etapa_1 ok"},
            )
        if task.task_name == "etapa_2" and ciclo[0] == 1:
            return AgentResult(
                agent_id=task.agent_id,
                session_id="s1",
                status="error",
                response={},
                error="erro na etapa 2",
            )
        # Segundo ciclo: etapa_2 passa
        return AgentResult(
            agent_id=task.agent_id,
            session_id="s1",
            status="success",
            response={"text": "etapa_2 ok agora"},
        )

    mock_orchestrator = MagicMock()
    mock_orchestrator._execute_agent = mock_execute
    mock_orchestrator._run_planning_loop = AsyncMock(side_effect=mock_planning_loop)
    mock_orchestrator.output_manager = MagicMock()
    mock_orchestrator.output_manager.list_artifacts.return_value = []

    loop = AutonomousLoop(mock_orchestrator)

    with patch("src.autonomous_loop.get_telemetry", return_value=MagicMock()):
        result = await loop.run("tarefa de 2 etapas", "exec_test")

    # Deve ter concluído com sucesso (sem circuit breaker)
    final_texts = " ".join(
        r.response.get("text", "") or ""
        for r in result.results
    )
    assert "progresso" not in final_texts.lower() or result.succeeded > 0, (
        "Circuit breaker ativado indevidamente quando havia progresso real"
    )
    assert result.succeeded > 0


# ---------------------------------------------------------------------------
# V12.5.2 — Limite de execuções de agente por sessão
# ---------------------------------------------------------------------------

def _orchestrator_with_mocks():
    from src.orchestrator import Orchestrator

    mock_session_manager = MagicMock()
    mock_session_manager.create = MagicMock(return_value=MagicMock(id="sess_abc"))
    mock_session_manager.update = MagicMock()
    mock_session_manager.close = MagicMock()

    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock()
    return Orchestrator(session_manager=mock_session_manager, agent_runtime=mock_runtime), mock_runtime


@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_breaker_aborta_ao_atingir_limite_de_execucoes():
    """_execute_agent deve levantar RuntimeError ao ultrapassar
    MAX_AGENT_RUNS_PER_SESSION execuções de agente na mesma sessão."""
    from src.orchestrator import AgentTask

    orchestrator, mock_runtime = _orchestrator_with_mocks()
    task = AgentTask(agent_id="base", prompt="teste", task_name="tarefa_x")

    with patch("src.orchestrator.MAX_AGENT_RUNS_PER_SESSION", 3):
        orchestrator._session_agent_run_counts = {"master_sess": 3}
        with pytest.raises(RuntimeError, match="[Ll]imite.*[Ee]xecuç"):
            await orchestrator._execute_agent(task, "master_sess")

    mock_runtime.run.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_agent_incrementa_contador_de_execucoes():
    """_execute_agent deve incrementar o contador de execuções da sessão."""
    from src.orchestrator import AgentResult, AgentTask

    orchestrator, mock_runtime = _orchestrator_with_mocks()
    mock_runtime.run.return_value = AgentResult(
        agent_id="base", session_id="sess_abc", status="success", response={"text": "resultado"}
    )
    task = AgentTask(agent_id="base", prompt="teste", task_name="tarefa_y")

    with patch("src.orchestrator.get_telemetry", return_value=MagicMock()):
        await orchestrator._execute_agent(task, "master_sess_x")
        await orchestrator._execute_agent(task, "master_sess_x")

    assert orchestrator._session_agent_run_counts.get("master_sess_x", 0) == 2
