import pytest
from unittest.mock import patch

from agents.base.agent import (
    root_agent,
    AGENT_NAME,
    AGENT_DESCRIPTION,
    AGENT_INSTRUCTION,
    _load_session_context,
    _persist_session_context,
)
from src.config import DEFAULT_MODEL


@pytest.mark.unit
class TestAgentAttributes:
    """Testes dos atributos obrigatórios do agente base."""

    def test_agent_has_name(self) -> None:
        """root_agent deve ter o campo name definido."""
        assert root_agent.name == AGENT_NAME

    def test_agent_name_value(self) -> None:
        """O nome do agente deve ser 'geminiclaw_base'."""
        assert root_agent.name == "geminiclaw_base"

    def test_agent_has_model(self) -> None:
        """root_agent deve ter o campo model definido e correspondente ao DEFAULT_MODEL."""
        assert root_agent.model == DEFAULT_MODEL

    def test_agent_has_description(self) -> None:
        """root_agent deve ter description não-vazia."""
        assert root_agent.description
        assert len(root_agent.description) > 0

    def test_agent_has_instruction(self) -> None:
        """root_agent deve ter instruction não-vazia."""
        assert root_agent.instruction
        assert len(root_agent.instruction) > 0

    def test_agent_description_value(self) -> None:
        """Description deve corresponder à constante AGENT_DESCRIPTION."""
        assert root_agent.description == AGENT_DESCRIPTION

    def test_agent_instruction_value(self) -> None:
        """Instruction deve conter o conteúdo base de AGENT_INSTRUCTION.

        O root_agent recebe a instrução processada por _get_agent_instruction(),
        que anexa um system_context dinâmico (catálogo de skills, memória de
        longo prazo, informações de hardware). Portanto a instrução final sempre
        começa com AGENT_INSTRUCTION, mas pode ter conteúdo adicional.
        """
        assert root_agent.instruction.startswith(AGENT_INSTRUCTION)


    def test_agent_has_before_callback(self) -> None:
        """root_agent deve ter before_agent_callback configurado."""
        assert root_agent.before_agent_callback is not None

    def test_agent_has_after_callback(self) -> None:
        """root_agent deve ter after_agent_callback configurado."""
        assert root_agent.after_agent_callback is not None

    def test_agent_callbacks_are_correct_functions(self) -> None:
        """Os callbacks devem ser as funções corretas."""
        assert root_agent.before_agent_callback == _load_session_context
        assert root_agent.after_agent_callback == _persist_session_context
