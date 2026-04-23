from agents.summarizer.agent import root_agent, AGENT_NAME

def test_summarizer_agent_initialization():
    """Testa se o agente summarizer foi inicializado corretamente."""
    assert root_agent is not None
    assert root_agent.name == AGENT_NAME
    assert "síntese" in root_agent.description.lower()
    
    # Verifica se as ferramentas adequadas estão presentes (write_artifact)
    tool_names = [getattr(t, "__name__", "") for t in root_agent.tools]
    assert "write_artifact" in tool_names

def test_summarizer_instruction():
    """Testa se a instrução do agente contém as regras essenciais."""
    instruction = root_agent.instruction
    assert "redator acadêmico especializado em síntese" in instruction
    assert "write_artifact" in instruction
    assert "relatorio_final.md" in instruction
