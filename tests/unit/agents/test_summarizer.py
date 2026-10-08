from agents.summarizer.agent import AGENT_NAME, root_agent


def test_summarizer_agent_initialization():
    """Testa se o agente summarizer foi inicializado corretamente."""
    assert root_agent is not None
    assert root_agent.name == AGENT_NAME
    assert "síntese" in root_agent.description.lower()
    
    # v16-pipeline-robustness §6: o Summarizer só produz a narrativa e não tem ferramentas
    assert list(root_agent.tools) == []

def test_summarizer_instruction():
    """Testa se a instrução do agente contém as regras essenciais."""
    instruction = root_agent.instruction
    assert "redator científico especializado em síntese" in instruction
    assert "JSON" in instruction and "confianca_nivel" in instruction
    assert "Containers" not in instruction
