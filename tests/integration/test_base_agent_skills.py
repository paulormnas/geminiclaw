import os
import pytest
from agents.base.agent import root_agent
from src.skills import registry

@pytest.mark.integration
def test_base_agent_has_skills():
    """Verifica se o agente base tem as ferramentas das skills habilitadas."""
    # Como as skills são carregadas no import do agent.py, 
    # elas já devem estar no root_agent.tools se habilitadas via env (padrão true)
    
    tool_names = [t.__name__ for t in root_agent.tools]
    
    # Skills padrão habilitadas
    if os.environ.get("SKILL_QUICK_SEARCH_ENABLED", "true") == "true":
        assert "quick_search" in tool_names
        
    if os.environ.get("SKILL_CODE_ENABLED", "true") == "true":
        assert "python_interpreter" in tool_names
        
    if os.environ.get("SKILL_MEMORY_ENABLED", "true") == "true":
        assert "memory" in tool_names

    # write_artifact também deve estar lá
    assert "write_artifact" in tool_names

@pytest.mark.asyncio
async def test_base_agent_skill_execution():
    """Verifica se as ferramentas das skills no agente base são chamáveis."""
    # Busca a ferramenta memory no root_agent
    memory_tool = next((t for t in root_agent.tools if t.__name__ == "memory"), None)
    assert memory_tool is not None
    
    # Executa a ferramenta (mockando kwargs)
    # Note: O ADK converte a saída em string
    result = await memory_tool(action="remember", session_id="test_session", key="test_key", value="test_value")
    assert "Resultado de memory" in result
    assert "test_key" in result
