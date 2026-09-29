"""Testes de src/agent_runtime/definitions.py (Roadmap V16/ADR 014)."""

import pytest

from src.agent_runtime.definitions import (
    get_agent_definition,
    get_agent_definitions,
    reset_definitions_cache,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_definitions_cache()
    yield
    reset_definitions_cache()


@pytest.mark.unit
class TestAgentDefinitions:
    """Cobre o Requirement 'Agentes executam em processo no host'."""

    def test_known_roles_resolve(self) -> None:
        for role in ("base", "developer", "researcher", "summarizer", "reviewer"):
            definition = get_agent_definition(role)
            assert definition.agent_id == role
            assert definition.role == role
            assert callable(definition.instruction)
            assert isinstance(definition.instruction(), str)
            assert len(definition.instruction()) > 0

    def test_unknown_role_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Papel de agente desconhecido"):
            get_agent_definition("nonexistent_role")

    def test_definitions_cached_across_calls(self) -> None:
        first = get_agent_definitions()
        second = get_agent_definitions()
        assert first is second

    def test_developer_tools_do_not_include_web_search(self) -> None:
        """Developer é exclusivo de código/dados (agents/developer/agent.py)."""
        definition = get_agent_definition("developer")
        tool_names = {getattr(t, "__name__", "") for t in definition.tools}
        assert "quick_search" not in tool_names
        assert "python_interpreter" in tool_names or any("python" in n for n in tool_names)
