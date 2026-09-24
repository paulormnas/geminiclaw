"""Testes de integração para gerenciamento de sessão via CLI (Roadmap V14.6).

Cobre:
- Listagem de containers ativos com `geminiclaw sessions`.
- Encerramento de containers com `geminiclaw stop` e `geminiclaw stop --session <id>`.
- Encerramento gracioso de containers de sessão ao receber SIGINT.
"""

import signal
import sys
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from src.cli import show_sessions, stop_sessions, build_parser, main


def _make_mock_container(
    cid: str,
    session_id: str,
    agent_id: str = "developer",
    image: str = "geminiclaw-developer:latest",
    status: str = "running",
):
    """Helper para simular um container retornado pela Docker API."""
    c = MagicMock()
    c.id = cid
    c.short_id = cid[:12]
    c.status = status
    c.labels = {
        "project": "geminiclaw",
        "geminiclaw.managed": "true",
        "session_id": session_id,
        "agent_id": agent_id,
    }
    img = MagicMock()
    img.tags = [image]
    c.image = img
    return c


@pytest.mark.unit
class TestCliSessionParser:
    """Valida argumentos do parser para sessões."""

    def test_parser_session_flag(self):
        parser = build_parser()
        args = parser.parse_args(["stop", "--session", "sess_xyz"])
        assert args.prompt == "stop"
        assert args.session == "sess_xyz"

    def test_parser_sessions_prompt(self):
        parser = build_parser()
        args = parser.parse_args(["sessions"])
        assert args.prompt == "sessions"
        assert args.session is None


@pytest.mark.unit
class TestCliSessionsListing:
    """Valida comando `geminiclaw sessions`."""

    def test_show_sessions_empty(self, capsys):
        mock_client = MagicMock()
        mock_client.containers.list.return_value = []

        res = show_sessions(docker_client=mock_client)
        assert res == []
        captured = capsys.readouterr().out
        assert "Nenhum container de sessão ativo encontrado" in captured

    def test_show_sessions_with_active_containers(self, capsys):
        c1 = _make_mock_container("c111111111111111", "sess_001", "developer", "geminiclaw-developer")
        c2 = _make_mock_container("c222222222222222", "sess_002", "researcher", "geminiclaw-researcher")

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [c1, c2]

        res = show_sessions(docker_client=mock_client)
        assert len(res) == 2
        assert res[0]["session_id"] == "sess_001"
        assert res[0]["agent_id"] == "developer"
        assert res[1]["session_id"] == "sess_002"
        assert res[1]["agent_id"] == "researcher"

        captured = capsys.readouterr().out
        assert "Sessões e Containers Ativos do GeminiClaw" in captured
        assert "sess_001" in captured
        assert "sess_002" in captured
        assert "geminiclaw-developer" in captured
        assert "geminiclaw-researcher" in captured


@pytest.mark.unit
class TestCliStopSessions:
    """Valida comando `geminiclaw stop`."""

    def test_stop_all_sessions(self, capsys):
        c1 = _make_mock_container("c111111111111111", "sess_001")
        c2 = _make_mock_container("c222222222222222", "sess_002")

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [c1, c2]

        count = stop_sessions(session_id=None, docker_client=mock_client)
        assert count == 2
        c1.stop.assert_called_once_with(timeout=10)
        c2.stop.assert_called_once_with(timeout=10)

        captured = capsys.readouterr().out
        assert "2 container(s) encerrado(s) com sucesso" in captured

    def test_stop_specific_session(self, capsys):
        c1 = _make_mock_container("c111111111111111", "sess_target")
        c2 = _make_mock_container("c222222222222222", "sess_other")

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [c1, c2]

        count = stop_sessions(session_id="sess_target", docker_client=mock_client)
        assert count == 1
        c1.stop.assert_called_once_with(timeout=10)
        c2.stop.assert_not_called()

        captured = capsys.readouterr().out
        assert "1 container(s) encerrado(s) com sucesso" in captured

    def test_stop_session_with_session_runner(self):
        mock_runner = MagicMock()
        mock_runner.stop = AsyncMock()
        mock_runner.stop_all = AsyncMock()

        # Com session_id
        stop_sessions(session_id="sess_target", session_runner=mock_runner)
        mock_runner.stop.assert_awaited_once_with("sess_target")

        # Sem session_id
        stop_sessions(session_id=None, session_runner=mock_runner)
        mock_runner.stop_all.assert_awaited_once()


@pytest.mark.unit
class TestCliMainCommands:
    """Valida despache dos comandos sessions e stop na função main()."""

    @patch("src.cli.show_sessions")
    def test_main_sessions_command(self, mock_show):
        with patch("sys.argv", ["geminiclaw", "sessions"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            mock_show.assert_called_once()

    @patch("src.cli.stop_sessions")
    def test_main_stop_all_command(self, mock_stop):
        with patch("sys.argv", ["geminiclaw", "stop"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            mock_stop.assert_called_once_with(session_id=None)

    @patch("src.cli.stop_sessions")
    def test_main_stop_with_flag(self, mock_stop):
        with patch("sys.argv", ["geminiclaw", "stop", "--session", "sess_123"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            mock_stop.assert_called_once_with(session_id="sess_123")


@pytest.mark.unit
class TestCliSigintGracefulShutdown:
    """Valida que o handler de SIGINT realiza encerramento gracioso via session_runner."""

    @patch("src.cli._create_orchestrator")
    @patch("src.cli.signal.signal")
    def test_sigint_handler_invokes_session_runner_stop_all(
        self,
        mock_signal: MagicMock,
        mock_create: MagicMock,
    ):
        mock_orchestrator = MagicMock()
        mock_orchestrator.session_runner = MagicMock()
        mock_orchestrator.session_runner.stop_all = AsyncMock()

        mock_runner = MagicMock()
        mock_create.return_value = (mock_orchestrator, mock_runner)

        with patch("src.cli.asyncio.run"):
            with patch("src.cli.execute_prompt", new_callable=MagicMock):
                with patch("sys.argv", ["geminiclaw", "teste"]):
                    main()

        # O handler deve ter sido registrado
        assert mock_signal.call_count >= 1
        handler = mock_signal.call_args_list[0][0][1]

        # Simula o disparo do sinal SIGINT
        with patch("sys.exit") as mock_exit:
            with patch("src.telemetry.get_telemetry") as mock_tel:
                mock_tel.return_value.flush = AsyncMock()
                handler(signal.SIGINT, None)

            # Verifica que session_runner.stop_all foi invocado
            mock_orchestrator.session_runner.stop_all.assert_awaited_once()
            # Verifica que runner.cleanup_all foi invocado
            mock_runner.cleanup_all.assert_called_once()
            # Verifica código de saída 130
            mock_exit.assert_called_once_with(130)
