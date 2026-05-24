"""Testes de integração para V13.5 — Enriquecimento de Contexto no Retry.

Verifica se o orquestrador popula a memória de curto prazo com o contexto
da tentativa falha anterior, se inclui a lista de artefatos existentes no disco,
e se o revisor recebe a lista de artefatos.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator import AgentTask, AgentResult
from src.autonomous_loop import AutonomousLoop
from src.skills.memory.short_term import ShortTermMemory


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_context_enrichment(monkeypatch):
    """V13.5: Verifica persistência de retry_context na ShortTermMemory."""
    # Mock das dependências
    orchestrator = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = ["file1.txt", "file2.csv"]
    
    loop = AutonomousLoop(orchestrator)
    loop.max_retries = 2
    loop._short_term_memory = ShortTermMemory() # Instância limpa
    
    # Faz o orquestrador falhar na primeira vez e ter sucesso na segunda
    fail_result = AgentResult(
        agent_id="test",
        session_id="test_session",
        status="error",
        response={},
        error="Fail on first try"
    )
    success_result = AgentResult(
        agent_id="test",
        session_id="test_session",
        status="success",
        response={"text": "Sucesso na segunda"}
    )
    
    async def mock_execute_agent(task, session_id):
        if task.retry_attempt == 0:
            return fail_result
        return success_result

    orchestrator._execute_agent = AsyncMock(side_effect=mock_execute_agent)
    
    # Mock do planner para retornar 1 subtarefa
    task = AgentTask(
        agent_id="test_agent",
        image="test_image",
        prompt="Faça X",
        task_name="task_x"
    )
    orchestrator._run_planning_loop = AsyncMock(return_value=[task])
    
    monkeypatch.setenv("MAX_PLAN_RETRIES", "1")
    
    # Previne limpeza da memória ao final do loop
    loop._short_term_memory.clear = MagicMock()
    
    # Executa caminho complexo
    await loop._run_complex_path("Faça X", "test_session")
    
    # Verifica ShortTermMemory (foi populada na tentativa 1 que falhou e registrada como retry_context_task_x_1)
    entry = loop._short_term_memory.read("test_session", "retry_context_task_x_1")
    assert entry is not None
    data = json.loads(entry.value)
    
    assert data["type"] == "retry_context"
    assert data["task"] == "task_x"
    assert data["attempt"] == 1
    assert data["previous_error"] == "Fail on first try"
    assert "file1.txt" in data["artifacts_available"]
    
    # Verifica se os artefatos foram injetados no prompt da segunda chamada
    assert orchestrator._execute_agent.call_count >= 2
    second_call_task = orchestrator._execute_agent.call_args_list[1][0][0]
    assert "ARTEFATOS PARCIAIS EXISTENTES EM DISCO" in second_call_task.prompt
    assert "file1.txt" in second_call_task.prompt


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reviewer_receives_artifacts_context(monkeypatch):
    """V13.5.3: Verifica se _review_subtask injeta contexto de artefatos existentes."""
    orchestrator = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = ["file_on_disk.csv"]
    
    loop = AutonomousLoop(orchestrator)
    
    task = AgentTask(
        agent_id="test_agent",
        image="test_image",
        prompt="Gerar csv",
        task_name="task_csv",
        expected_artifacts=["file_on_disk.csv"]
    )
    result = AgentResult(
        agent_id="test_agent",
        session_id="sess_123",
        status="success",
        response={"text": "Aí está o csv"}
    )
    
    review_mock_result = AgentResult(
        agent_id="reviewer",
        session_id="sess_123",
        status="success",
        response={"text": '{"status": "pass", "issues": []}'}
    )
    orchestrator._execute_agent = AsyncMock(return_value=review_mock_result)
    
    review_data = await loop._review_subtask(task, result, "sess_123")
    
    assert review_data["status"] == "pass"
    assert orchestrator._execute_agent.call_count == 1
    
    # Inspeciona o prompt passado para o reviewer
    reviewer_task = orchestrator._execute_agent.call_args[0][0]
    assert "ARTEFATOS EXISTENTES NO DISCO (considerar como parte do resultado):" in reviewer_task.prompt
    assert "- file_on_disk.csv" in reviewer_task.prompt
