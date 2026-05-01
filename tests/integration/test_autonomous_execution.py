"""Roadmap V3 - Testes de integração — Fluxo autônomo simples e complexo.

Valida o ciclo completo do AutonomousLoop com o triage heurístico (Etapa V3).
"""

import pytest
import asyncio
import tempfile
import os
import shutil
from unittest.mock import MagicMock, AsyncMock, patch

from src.orchestrator import Orchestrator, AgentTask, AgentResult
from src.session import SessionManager
from src.db import get_connection
from src.ipc import IPCChannel
from src.output_manager import OutputManager


@pytest.mark.integration
@pytest.mark.asyncio
async def test_autonomous_simple_flow_integration():
    """Testa o fluxo autônomo simples (triage SIMPLE → Base Agent).

    Roadmap V3 - Etapa V3: o triage agora usa heurísticas locais,
    sem spawnar container para o Planner. TRIAGE_MODE=heuristic garante
    que o classificador decide diretamente.
    """
    ipc_dir = tempfile.mkdtemp(prefix="gc_ipc_")
    db_dir = tempfile.mkdtemp(prefix="gc_db_")
    output_dir = tempfile.mkdtemp(prefix="gc_out_")

    try:
        ipc = IPCChannel(socket_dir=ipc_dir)
        session_manager = SessionManager()
        output_manager = OutputManager(base_dir=output_dir)
        mock_runner = MagicMock()

        orchestrator = Orchestrator(mock_runner, ipc, session_manager, output_manager)

        # Prompt curto → heurística classifica como SIMPLE → Base Agent direto
        base_res = AgentResult(
            agent_id="base", session_id="s1", status="success", response={"text": "Olá!"}
        )
        orchestrator._execute_agent = AsyncMock(return_value=base_res)

        # Força modo heuristic para evitar chamada LLM em teste
        with patch.dict(os.environ, {"TRIAGE_MODE": "heuristic"}):
            result = await orchestrator.handle_request("Diga olá")

        assert result.total == 1
        assert result.succeeded == 1
        assert result.results[0].agent_id == "base"
        assert result.results[0].response["text"] == "Olá!"
        # Sem container de triage: apenas 1 chamada (Base Agent)
        assert orchestrator._execute_agent.call_count == 1

    finally:
        shutil.rmtree(ipc_dir, ignore_errors=True)
        shutil.rmtree(db_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_autonomous_complex_flow_integration():
    """Testa o fluxo autônomo complexo (triage COMPLEX → Planner → Subtasks).

    Roadmap V3 - Etapa V3: o triage classifica como COMPLEX via heurística
    (palavras-chave 'pesquise', 'analise'), sem container. O _run_planning_loop
    é mockado para isolar o planejamento.
    """
    ipc_dir = tempfile.mkdtemp(prefix="gc_ipc_")
    db_dir = tempfile.mkdtemp(prefix="gc_db_")
    output_dir = tempfile.mkdtemp(prefix="gc_out_")

    try:
        ipc = IPCChannel(socket_dir=ipc_dir)
        session_manager = SessionManager()
        output_manager = OutputManager(base_dir=output_dir)
        mock_runner = MagicMock()

        orchestrator = Orchestrator(mock_runner, ipc, session_manager, output_manager)

        # Planejamento mockado diretamente para isolar o teste do fluxo do loop
        task1 = AgentTask(
            agent_id="researcher", image="img", prompt="search X", task_name="pesquisa_x"
        )
        orchestrator._run_planning_loop = AsyncMock(return_value=[task1])

        # Execução da subtarefa + promoção de memória
        task1_res = AgentResult(
            agent_id="researcher", session_id="s_task1", status="success", response={"text": "resultado X"}
        )
        promo_res = AgentResult(
            agent_id="planner", session_id="s_promo", status="success", response={}
        )
        orchestrator._execute_agent = AsyncMock(side_effect=[task1_res, promo_res])

        # "pesquise" e "analise" → heurística classifica como COMPLEX
        with patch.dict(os.environ, {"TRIAGE_MODE": "heuristic"}):
            result = await orchestrator.handle_request(
                "Pesquise sobre X e analise os dados para gerar um relatório completo."
            )

        assert result.total == 1
        assert result.succeeded == 1
        assert result.results[0].agent_id == "researcher"
        # Sem container de triage: task1 + promotion = 2 chamadas
        assert orchestrator._execute_agent.call_count == 2

        # Verifica que a sessão mestra foi fechada corretamente
        sessions = session_manager.list_recent(limit=10)
        master_session = next((s for s in sessions if s.agent_id == "orchestrator"), None)
        assert master_session is not None
        assert master_session.status == "closed"

    finally:
        shutil.rmtree(ipc_dir, ignore_errors=True)
        shutil.rmtree(db_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)
