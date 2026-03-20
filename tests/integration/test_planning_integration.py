import pytest
import asyncio
import os
from src.orchestrator import Orchestrator, AgentTask, AgentResult
from src.runner import ContainerRunner
from src.ipc import IPCChannel
from src.session import SessionManager
from src.output_manager import OutputManager

@pytest.fixture
def orchestrator():
    # Usa dependências reais para o teste de integração
    runner = ContainerRunner()
    ipc = IPCChannel()
    session_manager = SessionManager("store/geminiclaw_test.db")
    output_manager = OutputManager()
    return Orchestrator(runner, ipc, session_manager, output_manager)

@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_planning_flow_integration(orchestrator):
    """Testa o fluxo completo de planejamento com containers reais.
    
    Nota: Requer que as imagens geminiclaw-planner e geminiclaw-validator estejam built.
    Requer GEMINI_API_KEY válida para o agente responder via ADK.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY não definida")

    prompt = "Pesquise sobre a história do Raspberry Pi e salve um resumo."
    
    # Executa a orquestração (que deve disparar o planejamento primeiro)
    result = await orchestrator.handle_request(prompt)
    
    # Verifica se houve sucesso
    assert result.succeeded >= 1
    assert len(result.results) >= 1
    
    # Verifica se as tarefas planejadas foram executadas (provavelmente um 'researcher')
    agent_ids = [r.agent_id for r in result.results]
    assert "researcher" in agent_ids or "base" in agent_ids
    
    # Verifica se os artefatos foram gerados conforme o plano
    assert len(result.artifacts) > 0
