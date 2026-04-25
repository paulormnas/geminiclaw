import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from src.llm.agent_loop import run_agent_loop, AgentState
from src.llm.base import LLMResponse, ToolCall

@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_agent_loop_basic():
    """Testa o loop do agente em uma execução simples sem ferramentas."""
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = LLMResponse(
        text="Olá, eu sou o agente.",
        tool_calls=[]
    )
    
    with patch("src.llm.agent_loop.get_provider", return_value=mock_provider):
        response = await run_agent_loop(
            prompt="Oi",
            instruction="Seja educado",
            tools=[]
        )
        
        assert response == "Olá, eu sou o agente."
        mock_provider.generate.assert_called_once()
        
        # Verifica mensagens enviadas
        messages = mock_provider.generate.call_args[1]["messages"]
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Oi"

@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_agent_loop_with_tools():
    """Testa o loop do agente com chamada de ferramenta."""
    mock_provider = AsyncMock()
    
    # Primeira chamada retorna tool call
    mock_provider.generate.side_effect = [
        LLMResponse(
            text="Vou somar 2+2",
            tool_calls=[ToolCall(id="call_1", name="add", arguments={"a": 2, "b": 2})]
        ),
        # Segunda chamada retorna resposta final
        LLMResponse(
            text="O resultado é 4.",
            tool_calls=[]
        )
    ]
    
    def add(a, b):
        return str(a + b)
    add.__name__ = "add"
    
    with patch("src.llm.agent_loop.get_provider", return_value=mock_provider):
        response = await run_agent_loop(
            prompt="Quanto é 2+2?",
            instruction="",
            tools=[add]
        )
        
        assert response == "O resultado é 4."
        assert mock_provider.generate.call_count == 2
        
        # Verifica se o resultado da ferramenta foi enviado na segunda chamada
        messages = mock_provider.generate.call_args_list[1][1]["messages"]
        assert messages[-1]["role"] == "tool"
        assert messages[-1]["content"] == "4"

@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_agent_loop_callbacks():
    """Testa se os callbacks before/after são executados."""
    before = AsyncMock()
    after = AsyncMock()
    
    mock_provider = AsyncMock()
    mock_provider.generate.return_value = LLMResponse(text="Ok", tool_calls=[])
    
    with patch("src.llm.agent_loop.get_provider", return_value=mock_provider):
        await run_agent_loop(
            prompt="Teste",
            instruction="",
            tools=[],
            before_callback=before,
            after_callback=after
        )
        
        before.assert_called_once()
        after.assert_called_once()
        
        # Verifica se receberam o AgentState
        assert isinstance(before.call_args[0][0], AgentState)
        assert isinstance(after.call_args[0][0], AgentState)
