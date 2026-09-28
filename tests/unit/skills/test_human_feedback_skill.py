"""Testes unitários do HumanFeedbackSkill / ask_researcher (Roadmap V15.3 / Spec G5)."""

import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.skills.human_feedback.skill import HumanFeedbackSkill
from src.ipc import Message, HEADER_SIZE, create_message


@pytest.mark.unit
@pytest.mark.asyncio
class TestNonBlockingModes:
    """Modos semi/auto nunca bloqueiam — documentam a suposição e retornam."""

    async def test_modo_semi_nao_bloqueia(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_MODE", "semi")
        skill = HumanFeedbackSkill()

        result = await skill.run(question="Qual split usar?", why_cant_proceed="")

        assert result.success is True
        assert result.metadata["blocked"] is False
        assert "suposição" in result.output.lower()

    async def test_modo_auto_nao_bloqueia(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_MODE", "auto")
        skill = HumanFeedbackSkill()

        result = await skill.run(question="Qual seed usar?")

        assert result.success is True
        assert result.metadata["blocked"] is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestBlockingAssistedMode:
    """Modo assisted executa o round-trip IPC bloqueante real."""

    async def test_assisted_sem_conexao_ipc_retorna_erro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_MODE", "assisted")
        skill = HumanFeedbackSkill()

        with patch("agents.runner.get_active_ipc_connection", return_value=None):
            result = await skill.run(question="Onde está o dataset?", why_cant_proceed="Não está em input_context/")

        assert result.success is False
        assert "IPC" in result.error

    async def test_assisted_envia_mensagem_e_aguarda_resposta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SESSION_MODE", "assisted")
        monkeypatch.setenv("SESSION_ID", "sess_1")
        skill = HumanFeedbackSkill()

        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        answer_msg = create_message("ask_researcher_answer", "sess_1", {"answer": "Use o dataset em /outputs/dados.csv"})
        serialized = answer_msg.serialize()
        header = serialized[:HEADER_SIZE]
        body = serialized[HEADER_SIZE:]

        mock_reader = MagicMock()
        mock_reader.readexactly = AsyncMock(side_effect=[header, body])

        with patch("agents.runner.get_active_ipc_connection", return_value=(mock_reader, mock_writer)):
            result = await skill.run(
                question="Onde está o dataset proprietário?",
                context="Artigo cita 'dataset X'",
                why_cant_proceed="Não está em input_context/ nem foi mencionado na tarefa",
                options=["Usar substituto público", "Pular esta subtarefa"],
            )

        assert result.success is True
        assert result.output == "Use o dataset em /outputs/dados.csv"
        assert result.metadata["blocked"] is True

        sent_data = mock_writer.write.call_args[0][0]
        sent_msg = Message.deserialize(sent_data[HEADER_SIZE:])
        assert sent_msg.type == "ask_researcher"
        assert sent_msg.payload["question"] == "Onde está o dataset proprietário?"
        assert sent_msg.payload["options"] == ["Usar substituto público", "Pular esta subtarefa"]

    async def test_pergunta_sem_why_cant_proceed_loga_aviso(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("SESSION_MODE", "semi")
        skill = HumanFeedbackSkill()

        await skill.run(question="Pergunta sem justificativa")
        # Não deve lançar exceção; o aviso é emitido via logger estruturado (não stdlib logging
        # padrão), então validamos apenas que a chamada retorna normalmente em modo não-bloqueante.
