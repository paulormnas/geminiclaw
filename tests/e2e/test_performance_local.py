# tests/e2e/test_performance_local.py
"""
Teste de desempenho E2E com inferência local (Ollama + Qwen3.5-4B).
Mede a capacidade do framework de executar uma tarefa complexa de ponta a ponta 
utilizando exclusivamente recursos locais do Raspberry Pi 5.

Requer: Ollama rodando em localhost:11434 com qwen3.5:4b disponível.
"""
import pytest
import asyncio
import os
import httpx
from src.orchestrator import Orchestrator
from src.runner import ContainerRunner
from src.ipc import IPCChannel
from src.session import SessionManager

async def _ollama_available():
    """Verifica se o Ollama está respondendo em localhost."""
    url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/api/tags", timeout=2.0)
            return response.status_code == 200
    except Exception:
        return False

async def run_task(prompt: str):
    """Helper para executar uma tarefa completa via orquestrador."""
    runner = ContainerRunner()
    ipc = IPCChannel()
    session_manager = SessionManager()
    orchestrator = Orchestrator(runner, ipc, session_manager)
    
    # Força o uso do Ollama para o teste e2e local se não estiver configurado
    with pytest.MonkeyPatch().context() as m:
        m.setenv("LLM_PROVIDER", "ollama")
        m.setenv("LLM_MODEL", "qwen3.5:4b")
        
        result = await orchestrator.handle_request(prompt)
        
        # Consolida o texto de todos os agentes que tiveram sucesso
        text_parts = []
        for res in result.results:
            if res.status == "success" and "text" in res.response:
                text_parts.append(res.response["text"])
        
        return "\n\n".join(text_parts)

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_performance_pesquisa_e_relatorio_local():
    """Valida o desempenho em tarefa complexa: pesquisa sobre Python async + relatório markdown."""
    
    # Pula se o Ollama não estiver rodando (evita falha em CI sem hardware)
    if not await _ollama_available():
        pytest.skip("Ollama não disponível — execute: ollama serve")
        
    prompt = "Pesquise sobre asyncio em Python e gere um relatório markdown com exemplos"
    result = await run_task(prompt)
    
    assert result is not None
    assert len(result) > 50 # Pelo menos algum conteúdo gerado
    # Modelos menores podem não acertar 100% dos termos, mas 'async' é fundamental
    assert "async" in result.lower() or "await" in result.lower()
