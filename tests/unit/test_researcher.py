import pytest
from google.adk.agents import Agent

from agents.researcher.agent import (
    root_agent,
    AGENT_NAME,
    AGENT_DESCRIPTION,
    AGENT_INSTRUCTION,
)
from agents.researcher.tools import search
from agents.base.agent import _load_session_context, _persist_session_context
from src.config import DEFAULT_MODEL


@pytest.mark.unit
class TestResearcherAttributes:
    """Testes dos atributos obrigatórios do agente researcher."""

    def test_agent_is_valid_adk_agent(self) -> None:
        """root_agent deve ser uma instância válida de Agent do ADK."""
        assert isinstance(root_agent, Agent)

    def test_agent_has_correct_name(self) -> None:
        """O nome do agente deve ser 'geminiclaw_researcher'."""
        assert root_agent.name == AGENT_NAME
        assert root_agent.name == "geminiclaw_researcher"

    def test_agent_has_model(self) -> None:
        """root_agent deve usar o DEFAULT_MODEL."""
        assert root_agent.model == DEFAULT_MODEL

    def test_agent_has_description(self) -> None:
        """root_agent deve ter description não-vazia."""
        assert root_agent.description
        assert len(root_agent.description) > 0
        assert root_agent.description == AGENT_DESCRIPTION

    def test_agent_has_instruction(self) -> None:
        """root_agent deve ter instruction não-vazia."""
        assert root_agent.instruction
        assert len(root_agent.instruction) > 0
        assert root_agent.instruction == AGENT_INSTRUCTION

    def test_agent_instruction_in_portuguese(self) -> None:
        """Instrução deve estar em português."""
        assert "português" in root_agent.instruction.lower()

    def test_agent_instruction_mentions_search(self) -> None:
        """Instrução deve mencionar a ferramenta de busca."""
        assert "search" in root_agent.instruction.lower() or "busca" in root_agent.instruction.lower()

    def test_agent_has_tools(self) -> None:
        """root_agent deve ter a ferramenta 'search' registrada."""
        assert root_agent.tools is not None
        assert len(root_agent.tools) > 0

    def test_agent_has_search_tool(self) -> None:
        """A ferramenta 'search' deve estar na lista de tools."""
        tool_names = [t.__name__ if callable(t) else str(t) for t in root_agent.tools]
        assert "search" in tool_names

    def test_agent_has_before_callback(self) -> None:
        """root_agent deve ter before_agent_callback configurado."""
        assert root_agent.before_agent_callback is not None

    def test_agent_has_after_callback(self) -> None:
        """root_agent deve ter after_agent_callback configurado."""
        assert root_agent.after_agent_callback is not None

    def test_agent_callbacks_reuse_base(self) -> None:
        """Os callbacks devem reutilizar os do agente base."""
        assert root_agent.before_agent_callback == _load_session_context
        assert root_agent.after_agent_callback == _persist_session_context
