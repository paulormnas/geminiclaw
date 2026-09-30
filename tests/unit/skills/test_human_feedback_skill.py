"""Testes unitários do HumanFeedbackSkill / ask_researcher (Roadmap V15.3 / Spec G5).

No runtime em processo (ADR 014) o modo de sessão e a ponte com o pesquisador vêm do
``AgentContext`` da tarefa; não há mais canal IPC.
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.agent_runtime.context import AgentContext, bind_agent_context, current_context
from src.skills.human_feedback.skill import HumanFeedbackSkill


def _bind(tmp_path: Path, mode: str, ask=None) -> AgentContext:
    ctx = AgentContext(
        session_id="sess_1",
        agent_session_id="sess_1_agent",
        agent_id="researcher",
        mode=mode,
        output_dir=tmp_path / "outputs" / "sess_1",
        model="test-model",
        ask_researcher=ask,
    )
    bind_agent_context(ctx)
    return ctx


@pytest.fixture(autouse=True)
def _clear_context():
    token = current_context.set(None)
    yield
    current_context.reset(token)


@pytest.mark.unit
@pytest.mark.asyncio
class TestNonBlockingModes:
    """Modos semi/auto nunca bloqueiam — documentam a suposição e retornam."""

    async def test_modo_semi_nao_bloqueia(self, tmp_path: Path) -> None:
        ask = AsyncMock(return_value="não deve ser chamado")
        _bind(tmp_path, "semi", ask)

        result = await HumanFeedbackSkill().run(question="Qual split usar?", why_cant_proceed="")

        assert result.success is True
        assert result.metadata["blocked"] is False
        assert "suposição" in result.output.lower()
        ask.assert_not_awaited()

    async def test_modo_auto_nao_bloqueia(self, tmp_path: Path) -> None:
        ask = AsyncMock()
        _bind(tmp_path, "auto", ask)

        result = await HumanFeedbackSkill().run(question="Qual seed usar?")

        assert result.success is True
        assert result.metadata["blocked"] is False
        ask.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
class TestBlockingAssistedMode:
    """Modo assisted consulta o pesquisador pelo callback do AgentContext."""

    async def test_assisted_sem_contexto_de_agente_retorna_erro(self) -> None:
        result = await HumanFeedbackSkill().run(
            question="Onde está o dataset?", why_cant_proceed="Não está em input_context/"
        )

        assert result.success is False
        assert "AgentContext" in result.error

    async def test_assisted_sem_callback_retorna_erro(self, tmp_path: Path) -> None:
        _bind(tmp_path, "assisted", ask=None)

        result = await HumanFeedbackSkill().run(question="Onde está o dataset?", why_cant_proceed="motivo")

        assert result.success is False
        assert "AgentContext" in result.error

    async def test_assisted_chama_o_callback_e_devolve_a_resposta(self, tmp_path: Path) -> None:
        ask = AsyncMock(return_value="Use o dataset em /outputs/dados.csv")
        _bind(tmp_path, "assisted", ask)

        result = await HumanFeedbackSkill().run(
            question="Onde está o dataset proprietário?",
            context="Artigo cita 'dataset X'",
            why_cant_proceed="Não está em input_context/ nem foi mencionado na tarefa",
            options=["Usar substituto público", "Pular esta subtarefa"],
        )

        assert result.success is True
        assert result.output == "Use o dataset em /outputs/dados.csv"
        assert result.metadata["blocked"] is True
        ask.assert_awaited_once_with(
            "Onde está o dataset proprietário?",
            "Artigo cita 'dataset X'",
            "Não está em input_context/ nem foi mencionado na tarefa",
            ["Usar substituto público", "Pular esta subtarefa"],
        )

    async def test_pergunta_sem_why_cant_proceed_segue_normalmente(self, tmp_path: Path) -> None:
        _bind(tmp_path, "semi")

        result = await HumanFeedbackSkill().run(question="Pergunta sem justificativa")

        # O aviso é emitido pelo logger estruturado; a chamada retorna normalmente.
        assert result.success is True
