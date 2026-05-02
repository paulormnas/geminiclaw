import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.autonomous_loop import AutonomousLoop
from src.orchestrator import AgentResult, AgentTask, Orchestrator
from src.telemetry import get_telemetry
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_subtask_metrics_lifecycle():
    """Valida se as métricas de subtarefa são registradas nos estados corretos."""
    from src.orchestrator import Orchestrator
    from src.runner import ContainerRunner
    from src.ipc import IPCChannel
    from src.session import SessionManager
    
    # Mocks das dependências do orquestrador
    mock_runner = MagicMock(spec=ContainerRunner)
    mock_runner.spawn = AsyncMock(return_value="c1")
    mock_runner.is_running = AsyncMock(return_value=True)
    mock_runner.stop = AsyncMock()
    
    mock_ipc = MagicMock(spec=IPCChannel)
    mock_ipc.create_socket = AsyncMock()
    mock_ipc.send = AsyncMock()
    mock_ipc.receive = AsyncMock(return_value=MagicMock(type="response", payload={"status": "success", "text": "ok"}))
    mock_ipc.close = AsyncMock()
    mock_ipc._connections = {"base_s1": True} # Simula conexão imediata
    
    mock_session_manager = MagicMock(spec=SessionManager)
    mock_session = MagicMock()
    mock_session.id = "s1"
    mock_session_manager.create.return_value = mock_session
    
    orchestrator = Orchestrator(
        runner=mock_runner,
        ipc=mock_ipc,
        session_manager=mock_session_manager
    )
    orchestrator.output_manager = MagicMock()
    
    # Mock do Telemetria
    telemetry = get_telemetry()
    with patch.object(telemetry, "record_subtask_metrics") as mock_record:
        loop = AutonomousLoop(orchestrator)
        
        # Simula o caminho simples
        with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=False)), \
             patch("src.orchestrator.AGENT_TIMEOUT_SECONDS", 0.1): # Timeout curto para o wait_for_connection
            await loop.run("Teste", "exec1")
            
        # Verificações
        subtask_calls = [c for c in mock_record.call_args_list]
        
        # Debe haver chamadas para pending, running e success
        statuses = [c.kwargs.get("status") for c in subtask_calls]
        assert "pending" in statuses
        assert "running" in statuses
        assert "success" in statuses

@pytest.mark.asyncio
async def test_complex_path_subtask_id_generation():
    """Valida se subtarefas em um plano complexo recebem IDs únicos."""
    orchestrator = MagicMock(spec=Orchestrator)
    orchestrator._execute_agent = AsyncMock()
    orchestrator._run_planning_loop = AsyncMock()
    orchestrator.output_manager = MagicMock()
    
    # Mock do plano com 2 tarefas
    task1 = AgentTask(agent_id="researcher", image="img", prompt="p1", task_name="t1")
    task2 = AgentTask(agent_id="researcher", image="img", prompt="p2", task_name="t2")
    orchestrator._run_planning_loop.return_value = [task1, task2]
    
    # Mock resultados
    res = AgentResult(agent_id="r", session_id="s", status="success", response={})
    orchestrator._execute_agent.return_value = res
    
    telemetry = get_telemetry()
    with patch.object(telemetry, "record_subtask_metrics") as mock_record:
        loop = AutonomousLoop(orchestrator)
        with patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)), \
             patch("src.autonomous_loop.datetime") as mock_dt:
            
            mock_dt.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            await loop.run("Complex", "exec2")
            
        # Verifica se record_subtask_metrics foi chamado para t1 e t2 com IDs diferentes
        pending_calls = [c for c in mock_record.call_args_list if c.kwargs.get("status") == "pending"]
        assert len(pending_calls) >= 2
        ids = {c.kwargs.get("subtask_id") for c in pending_calls}
        assert len(ids) >= 2
        assert None not in ids
