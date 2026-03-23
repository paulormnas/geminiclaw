import pytest
import asyncio
import tempfile
import os
import shutil
from unittest.mock import MagicMock, AsyncMock, patch

from src.orchestrator import Orchestrator, AgentTask, AgentResult
from src.session import SessionManager
from src.ipc import IPCChannel
from src.output_manager import OutputManager

@pytest.mark.integration
@pytest.mark.asyncio
async def test_autonomous_simple_flow_integration():
    """Testa o fluxo autônomo simples (triage SIMPLE -> Base Agent)."""
    ipc_dir = tempfile.mkdtemp(prefix="gc_ipc_")
    db_dir = tempfile.mkdtemp(prefix="gc_db_")
    output_dir = tempfile.mkdtemp(prefix="gc_out_")
    
    try:
        ipc = IPCChannel(socket_dir=ipc_dir)
        db_path = os.path.join(db_dir, "test.db")
        session_manager = SessionManager(db_path=db_path)
        output_manager = OutputManager(base_dir=output_dir)
        mock_runner = MagicMock()
        
        orchestrator = Orchestrator(mock_runner, ipc, session_manager, output_manager)
        
        # Mock _execute_agent para simular o comportamento dos agentes
        # 1. Triage (Planner) -> retorna "SIMPLE"
        triage_res = AgentResult(agent_id="planner", session_id="s1", status="success", response={"text": "SIMPLE"})
        # 2. Base Agent -> retorna a resposta final
        base_res = AgentResult(agent_id="base", session_id="s2", status="success", response={"text": "Resposta simples"})
        
        orchestrator._execute_agent = AsyncMock(side_effect=[triage_res, base_res])
        
        result = await orchestrator.handle_request("Diga olá")
        
        assert result.total == 1
        assert result.succeeded == 1
        assert result.results[0].agent_id == "base"
        assert result.results[0].response["text"] == "Resposta simples"
        
    finally:
        shutil.rmtree(ipc_dir, ignore_errors=True)
        shutil.rmtree(db_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

@pytest.mark.integration
@pytest.mark.asyncio
async def test_autonomous_complex_flow_integration():
    """Testa o fluxo autônomo complexo (triage COMPLEX -> Planner -> Subtasks)."""
    ipc_dir = tempfile.mkdtemp(prefix="gc_ipc_")
    db_dir = tempfile.mkdtemp(prefix="gc_db_")
    output_dir = tempfile.mkdtemp(prefix="gc_out_")
    
    try:
        ipc = IPCChannel(socket_dir=ipc_dir)
        db_path = os.path.join(db_dir, "test.db")
        session_manager = SessionManager(db_path=db_path)
        output_manager = OutputManager(base_dir=output_dir)
        mock_runner = MagicMock()
        
        orchestrator = Orchestrator(mock_runner, ipc, session_manager, output_manager)
        
        # 1. Triage (Planner) -> retorna "COMPLEX"
        triage_res = AgentResult(agent_id="planner", session_id="s_triage", status="success", response={"text": "COMPLEX"})
        
        # 2. Planejamento (Planner -> Validator via _run_planning_loop)
        # Mockamos _run_planning_loop diretamente para simplificar este teste de integração do loop
        task1 = AgentTask(agent_id="researcher", image="img", prompt="search X")
        orchestrator._run_planning_loop = AsyncMock(return_value=[task1])
        
        # 3. Execução da Subtarefa 1
        task1_res = AgentResult(agent_id="researcher", session_id="s_task1", status="success", response={"text": "resultado X"})
        
        # 4. Promoção de memória (Planner)
        promo_res = AgentResult(agent_id="planner", session_id="s_promo", status="success", response={})
        
        orchestrator._execute_agent = AsyncMock(side_effect=[triage_res, task1_res, promo_res])
        
        result = await orchestrator.handle_request("Pesquise sobre X e resuma")
        
        assert result.total == 1
        assert result.succeeded == 1
        assert result.results[0].agent_id == "researcher"
        assert orchestrator._execute_agent.call_count == 3 # triage + task1 + promotion
        
        # Verifica se a sessão mestra foi atualizada corretamente no banco
        # (Nós sabemos que handle_request cria uma sessão 'orchestrator' no início)
        # Como não temos o ID facilmente, vamos listar as sessões
        sessions = session_manager.list_recent(limit=10)
        master_session = next((s for s in sessions if s.agent_id == "orchestrator"), None)
        assert master_session is not None
        assert master_session.status == "closed"
        
    finally:
        shutil.rmtree(ipc_dir, ignore_errors=True)
        shutil.rmtree(db_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
