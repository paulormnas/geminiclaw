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
  V12.5.2: Limite de containers por sessão — ao atingir MAX_CONTAINERS_PER_SESSION
           em _execute_agent, a execução é abortada com RuntimeError descritivo.
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
    from src.orchestrator import AgentTask, AgentResult, AGENT_REGISTRY
    from src.autonomous_loop import AutonomousLoop
    from src.usage import UsageBudget

    # Planner sempre retorna o mesmo plano com as mesmas 2 tarefas independentes
    tarefas = [
        AgentTask(
            agent_id="base",
            image=AGENT_REGISTRY["base"],
            prompt="tarefa 1",
            task_name="tarefa_ok",
        ),
        AgentTask(
            agent_id="base",
            image=AGENT_REGISTRY["base"],
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
    from src.orchestrator import AgentTask, AgentResult, AGENT_REGISTRY
    from src.autonomous_loop import AutonomousLoop

    ciclo = [0]

    async def mock_planning_loop(*args, **kwargs):
        ciclo[0] += 1
        if ciclo[0] == 1:
            return [
                AgentTask(
                    agent_id="base",
                    image=AGENT_REGISTRY["base"],
                    prompt="etapa 1",
                    task_name="etapa_1",
                ),
                AgentTask(
                    agent_id="base",
                    image=AGENT_REGISTRY["base"],
                    prompt="etapa 2 — vai falhar",
                    task_name="etapa_2",
                ),
            ]
        # Segundo ciclo: só a etapa_2 precisa ser re-executada e agora passa
        return [
            AgentTask(
                agent_id="base",
                image=AGENT_REGISTRY["base"],
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
# V12.5.2 — Limite de containers por sessão
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_circuit_breaker_aborta_ao_atingir_limite_containers():
    """_execute_agent deve levantar RuntimeError ao ultrapassar
    MAX_CONTAINERS_PER_SESSION containers spawnados na mesma sessão."""
    from src.orchestrator import Orchestrator, AgentTask, AGENT_REGISTRY

    mock_runner = AsyncMock()
    mock_runner.spawn = AsyncMock(return_value="container_id")
    mock_runner.is_running = AsyncMock(return_value=True)
    mock_runner.stop = AsyncMock()

    mock_ipc = AsyncMock()
    mock_ipc.create_socket = AsyncMock()
    mock_ipc.get_port = MagicMock(return_value=9999)
    mock_ipc._connections = {"base_sess": True}
    mock_ipc.send = AsyncMock()
    mock_ipc.receive = AsyncMock(return_value=MagicMock(
        type="response",
        payload={"text": "ok"},
    ))
    mock_ipc.close = AsyncMock()

    mock_session_manager = MagicMock()
    mock_session_manager.create = MagicMock(return_value=MagicMock(id="sess"))
    mock_session_manager.update = MagicMock()
    mock_session_manager.close = MagicMock()

    # Roadmap V16/ADR 014: AGENT_RUNTIME agora tem padrão "inprocess" —
    # este teste cobre especificamente o circuit breaker de containers do
    # caminho legado (_execute_agent_container), então fixa o modo.
    orchestrator = Orchestrator(
        runner=mock_runner,
        ipc=mock_ipc,
        session_manager=mock_session_manager,
        agent_runtime_mode="container",
    )

    task = AgentTask(
        agent_id="base",
        image=AGENT_REGISTRY["base"],
        prompt="teste",
        task_name="tarefa_x",
    )

    # Seta o contador já próximo do limite (default=30)
    # O patch deve ser no ponto de importação do módulo orchestrator
    with patch("src.orchestrator.MAX_CONTAINERS_PER_SESSION", 3):
        orchestrator._session_container_counts = {"master_sess": 3}
        with pytest.raises(RuntimeError, match="[Ll]imite.*[Cc]ontainer"):
            await orchestrator._execute_agent(task, "master_sess")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_agent_incrementa_contador_containers():
    """_execute_agent deve incrementar o contador de containers da sessão."""
    from src.orchestrator import Orchestrator, AgentTask, AGENT_REGISTRY

    mock_runner = AsyncMock()
    mock_runner.spawn = AsyncMock(return_value="cid")
    mock_runner.is_running = AsyncMock(return_value=True)
    mock_runner.stop = AsyncMock()
    mock_runner.get_logs = AsyncMock(return_value="")

    mock_ipc = AsyncMock()
    mock_ipc.create_socket = AsyncMock()
    mock_ipc.get_port = MagicMock(return_value=9999)
    mock_ipc._connections = {}
    mock_ipc.send = AsyncMock()
    mock_ipc.receive = AsyncMock(return_value=MagicMock(
        type="response",
        payload={"text": "resultado"},
    ))
    mock_ipc.close = AsyncMock()

    mock_session_manager = MagicMock()
    mock_session_manager.create = MagicMock(return_value=MagicMock(id="sess_abc"))
    mock_session_manager.update = MagicMock()
    mock_session_manager.close = MagicMock()

    # Roadmap V16/ADR 014: fixa o modo container — este teste cobre
    # especificamente o contador de containers do caminho legado.
    orchestrator = Orchestrator(
        runner=mock_runner,
        ipc=mock_ipc,
        session_manager=mock_session_manager,
        agent_runtime_mode="container",
    )

    task = AgentTask(
        agent_id="base",
        image=AGENT_REGISTRY["base"],
        prompt="teste",
        task_name="tarefa_y",
    )

    # Simula o IPC conectando imediatamente (coloca o ipc_id no dicionário)
    original_create = mock_ipc.create_socket.side_effect

    async def mock_create_socket(ipc_id):
        mock_ipc._connections[ipc_id] = True

    mock_ipc.create_socket.side_effect = mock_create_socket

    with patch("src.config.MAX_CONTAINERS_PER_SESSION", 30):
        with patch("src.autonomous_loop.get_telemetry", return_value=MagicMock()):
            with patch("src.orchestrator.get_telemetry", return_value=MagicMock()):
                await orchestrator._execute_agent(task, "master_sess_x")

    # Contador deve ter sido criado e incrementado
    assert orchestrator._session_container_counts.get("master_sess_x", 0) >= 1
