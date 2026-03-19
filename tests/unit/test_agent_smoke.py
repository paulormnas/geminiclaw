import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from google.adk.agents import Agent
from google.genai import types as genai_types

from agents.base.agent import root_agent, AGENT_NAME


@pytest.mark.unit
class TestAgentSmoke:
    """Smoke tests do agente base com mock do Gemini."""

    def test_agent_is_valid_adk_agent(self) -> None:
        """root_agent deve ser uma instância válida de Agent do ADK."""
        assert isinstance(root_agent, Agent)

    def test_agent_can_be_referenced(self) -> None:
        """root_agent deve ser acessível e não-None."""
        assert root_agent is not None
        assert root_agent.name == AGENT_NAME

    @pytest.mark.asyncio
    async def test_before_callback_loads_session(self) -> None:
        """before_agent_callback deve carregar payload da sessão no state."""
        from agents.base.agent import _load_session_context
        from src.session import Session

        mock_session = Session(
            id="test_sess",
            agent_id="test_agent",
            status="active",
            created_at="2025-01-01T00:00:00+00:00",
            updated_at="2025-01-01T00:00:00+00:00",
            payload={"context_key": "context_value", "history": ["msg1"]},
        )

        # Mock do contexto ADK
        mock_ctx = MagicMock()
        mock_ctx.state = {}

        with patch.dict("os.environ", {"SESSION_ID": "test_sess", "AGENT_ID": "test_agent"}):
            with patch("agents.base.agent.SessionManager") as MockManager:
                mock_manager_instance = MagicMock()
                mock_manager_instance.get.return_value = mock_session
                MockManager.return_value = mock_manager_instance

                await _load_session_context(mock_ctx)

                assert mock_ctx.state["context_key"] == "context_value"
                assert mock_ctx.state["history"] == ["msg1"]

    @pytest.mark.asyncio
    async def test_after_callback_persists_session(self) -> None:
        """after_agent_callback deve persistir state no SessionManager."""
        from agents.base.agent import _persist_session_context

        # Mock do contexto ADK com state (dict real, iterável nativamente)
        mock_ctx = MagicMock()
        mock_ctx.state = {"result": "done", "count": 42}

        with patch.dict("os.environ", {"SESSION_ID": "test_sess", "AGENT_ID": "test_agent"}):
            with patch("agents.base.agent.SessionManager") as MockManager:
                mock_manager_instance = MagicMock()
                MockManager.return_value = mock_manager_instance

                await _persist_session_context(mock_ctx)

                mock_manager_instance.update.assert_called_once_with(
                    "test_sess",
                    payload={"result": "done", "count": 42},
                )

    @pytest.mark.asyncio
    async def test_before_callback_no_session_id(self) -> None:
        """before_agent_callback sem SESSION_ID deve pular sem erro."""
        from agents.base.agent import _load_session_context

        mock_ctx = MagicMock()
        mock_ctx.state = {}

        with patch.dict("os.environ", {"SESSION_ID": "", "AGENT_ID": "test"}):
            # Não deve lançar exceção
            await _load_session_context(mock_ctx)
            assert mock_ctx.state == {}

    @pytest.mark.asyncio
    async def test_before_callback_session_not_found(self) -> None:
        """before_agent_callback com sessão inexistente deve logar warning sem erro."""
        from agents.base.agent import _load_session_context

        mock_ctx = MagicMock()
        mock_ctx.state = {}

        with patch.dict("os.environ", {"SESSION_ID": "nonexistent", "AGENT_ID": "test"}):
            with patch("agents.base.agent.SessionManager") as MockManager:
                mock_manager_instance = MagicMock()
                mock_manager_instance.get.return_value = None
                MockManager.return_value = mock_manager_instance

                await _load_session_context(mock_ctx)
                assert mock_ctx.state == {}
