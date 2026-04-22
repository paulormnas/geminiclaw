import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from src.orchestrator import Orchestrator, AgentTask, AgentResult
from src.autonomous_loop import AutonomousLoop
from src.output_manager import OutputManager
from src.session import SessionManager

@pytest.fixture
def mock_orchestrator():
    orch = MagicMock(spec=Orchestrator)
    orch.output_manager = MagicMock(spec=OutputManager)
    orch.output_manager.list_artifacts.return_value = []
    
    # Fazemos mock do _run_planning_loop para retornar um plano com paralelismo
    tasks = [
        AgentTask(agent_id="base", image="img", prompt="T1", task_name="task_1", depends_on=[]),
        AgentTask(agent_id="base", image="img", prompt="T2", task_name="task_2", depends_on=[]),
        AgentTask(agent_id="base", image="img", prompt="T3", task_name="task_3", depends_on=["task_1", "task_2"]),
    ]
    orch._run_planning_loop = AsyncMock(return_value=tasks)
    return orch

@pytest.mark.asyncio
async def test_parallel_execution_success(mock_orchestrator):
    """Testa se as tarefas independentes rodam concorrentemente e a dependente depois."""
    
    execution_order = []
    
    async def mock_execute_agent(task, session_id):
        execution_order.append(f"start_{task.task_name}")
        # Simulamos um delay para permitir a concorrência
        await asyncio.sleep(0.1)
        execution_order.append(f"end_{task.task_name}")
        return AgentResult(
            agent_id=task.agent_id,
            session_id=session_id,
            status="success",
            response={"text": f"Result {task.task_name}"}
        )

    mock_orchestrator._execute_agent = AsyncMock(side_effect=mock_execute_agent)
    
    loop = AutonomousLoop(mock_orchestrator)
    loop._short_term_memory = MagicMock()
    
    result = await loop._run_complex_path("Test Prompt", "session_123")
    
    assert result.succeeded == 3
    assert result.failed == 0
    
    # task_1 e task_2 devem ter iniciado antes do fim de qualquer uma (concorrência)
    assert execution_order.index("start_task_1") < execution_order.index("end_task_2") or \
           execution_order.index("start_task_2") < execution_order.index("end_task_1")
           
    # task_3 só pode iniciar após o fim da 1 e 2
    assert execution_order.index("start_task_3") > execution_order.index("end_task_1")
    assert execution_order.index("start_task_3") > execution_order.index("end_task_2")

@pytest.mark.asyncio
async def test_parallel_execution_failure_cancels_dependent(mock_orchestrator):
    """Testa se a falha em uma tarefa cancela as dependentes, mas permite a execução de independentes."""
    
    execution_order = []
    
    async def mock_execute_agent(task, session_id):
        execution_order.append(f"start_{task.task_name}")
        await asyncio.sleep(0.1)
        execution_order.append(f"end_{task.task_name}")
        
        status = "error" if task.task_name == "task_1" else "success"
        
        return AgentResult(
            agent_id=task.agent_id,
            session_id=session_id,
            status=status,
            response={"text": "err"} if status == "error" else {"text": "ok"},
            error="failed" if status == "error" else None
        )

    mock_orchestrator._execute_agent = AsyncMock(side_effect=mock_execute_agent)
    
    # Alteramos o orquestrador para gerar plano com apenas uma tentativa
    loop = AutonomousLoop(mock_orchestrator)
    loop.max_retries = 1  # Evitar múltiplos retries de task_1 para o teste ir rápido
    loop._short_term_memory = MagicMock()
    
    # O mock_execute_agent vai falhar task_1. Como task_3 depende dela, task_3 será cancelada.
    # task_2 é independente e deve completar.
    # O loop fará re-planejamento. Precisamos simular o segundo planejamento retornando vazio 
    # para sair do loop.
    mock_orchestrator._run_planning_loop.side_effect = [
        mock_orchestrator._run_planning_loop.return_value, # 1º round
        [], # 2º round retorna vazio para finalizar
    ]
    
    result = await loop._run_complex_path("Test Prompt", "session_123")
    
    # O plano original tinha 3 tarefas. Task_1 falhou, Task_2 sucedeu, Task_3 cancelada (não executada)
    assert "start_task_1" in execution_order
    assert "start_task_2" in execution_order
    assert "start_task_3" not in execution_order
