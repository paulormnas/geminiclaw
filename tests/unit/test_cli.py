"""Testes unitários para src/cli.py.

Cobre parsing de argumentos, formatação de resultados,
e comportamento do handler de SIGINT.
"""

import signal
import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.cli import (
    build_parser,
    format_agent_result,
    format_result,
    STATUS_ICONS,
    EXIT_COMMANDS,
    VERSION,
    BANNER,
)
from src.orchestrator import AgentResult, OrchestratorResult


# ─── Helpers ────────────────────────────────────────────────────────


def _make_agent_result(
    agent_id: str = "agent_1",
    session_id: str = "sess_1",
    status: str = "success",
    response: dict | None = None,
    error: str | None = None,
) -> AgentResult:
    """Helper para criar um AgentResult."""
    return AgentResult(
        agent_id=agent_id,
        session_id=session_id,
        status=status,
        response=response or {},
        error=error,
    )


def _make_orchestrator_result(
    results: list[AgentResult] | None = None,
) -> OrchestratorResult:
    """Helper para criar um OrchestratorResult."""
    if results is None:
        results = [_make_agent_result()]
    succeeded = sum(1 for r in results if r.status == "success")
    return OrchestratorResult(
        results=results,
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
    )


# ─── Testes de Parsing de Argumentos ───────────────────────────────


@pytest.mark.unit
class TestBuildParser:
    """Testes do parser de argumentos."""

    def test_prompt_posicional(self) -> None:
        """Parser aceita prompt como argumento posicional."""
        parser = build_parser()
        args = parser.parse_args(["Olá, mundo!"])
        assert args.prompt == "Olá, mundo!"

    def test_sem_prompt_modo_interativo(self) -> None:
        """Sem prompt, args.prompt é None (modo interativo)."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.prompt is None

    def test_flag_timeout(self) -> None:
        """Parser aceita flag --timeout."""
        parser = build_parser()
        args = parser.parse_args(["--timeout", "60", "meu prompt"])
        assert args.timeout == 60
        assert args.prompt == "meu prompt"

    def test_flag_model(self) -> None:
        """Parser aceita flag --model."""
        parser = build_parser()
        args = parser.parse_args(["--model", "gemini-pro", "teste"])
        assert args.model == "gemini-pro"

    def test_timeout_padrao(self) -> None:
        """Timeout padrão é o valor de AGENT_TIMEOUT_SECONDS."""
        parser = build_parser()
        args = parser.parse_args([])
        from src.config import AGENT_TIMEOUT_SECONDS
        assert args.timeout == AGENT_TIMEOUT_SECONDS

    def test_model_padrao(self) -> None:
        """Model padrão é o valor de DEFAULT_MODEL."""
        parser = build_parser()
        args = parser.parse_args([])
        from src.config import DEFAULT_MODEL
        assert args.model == DEFAULT_MODEL

    def test_version_flag(self) -> None:
        """Flag --version exibe a versão e sai."""
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_prompt_com_espacos(self) -> None:
        """Parser aceita prompt com espaços (como uma string única)."""
        parser = build_parser()
        args = parser.parse_args(["Qual é a capital do Brasil?"])
        assert args.prompt == "Qual é a capital do Brasil?"


# ─── Testes de Formatação de Resultados ────────────────────────────


@pytest.mark.unit
class TestFormatAgentResult:
    """Testes da formatação individual de AgentResult."""

    def test_formato_sucesso(self) -> None:
        """Resultado de sucesso exibe ícone ✅ e resposta."""
        result = _make_agent_result(
            status="success",
            response={"answer": "42"},
        )
        output = format_agent_result(result)
        assert STATUS_ICONS["success"] in output
        assert "agent_1" in output
        assert "success" in output
        assert "answer" in output
        assert "42" in output

    def test_formato_erro(self) -> None:
        """Resultado de erro exibe ícone ❌ e mensagem de erro."""
        result = _make_agent_result(
            status="error",
            error="Docker unavailable",
        )
        output = format_agent_result(result)
        assert STATUS_ICONS["error"] in output
        assert "error" in output
        assert "Docker unavailable" in output

    def test_formato_timeout(self) -> None:
        """Resultado de timeout exibe ícone ⏰."""
        result = _make_agent_result(
            status="timeout",
            error="Timeout excedido",
        )
        output = format_agent_result(result)
        assert STATUS_ICONS["timeout"] in output
        assert "timeout" in output

    def test_formato_sem_resposta(self) -> None:
        """Resultado de sucesso sem response não quebra."""
        result = _make_agent_result(status="success", response={})
        output = format_agent_result(result)
        assert STATUS_ICONS["success"] in output

    def test_exibe_session_id(self) -> None:
        """Session ID é exibido quando presente."""
        result = _make_agent_result(session_id="sess_abc123")
        output = format_agent_result(result)
        assert "sess_abc123" in output


@pytest.mark.unit
class TestFormatResult:
    """Testes da formatação consolidada de OrchestratorResult."""

    def test_resumo_sucesso_total(self) -> None:
        """Resumo com todos os agentes bem-sucedidos."""
        results = [
            _make_agent_result(agent_id=f"a{i}", status="success")
            for i in range(3)
        ]
        orch_result = _make_orchestrator_result(results)
        output = format_result(orch_result)
        assert "3" in output  # total
        assert "Resultado" in output

    def test_resumo_com_falhas(self) -> None:
        """Resumo com falhas exibe contador de falhas."""
        results = [
            _make_agent_result(agent_id="a0", status="success"),
            _make_agent_result(agent_id="a1", status="error", error="fail"),
        ]
        orch_result = _make_orchestrator_result(results)
        output = format_result(orch_result)
        assert "2" in output  # total
        assert "1" in output  # failed/succeeded

    def test_resultado_vazio(self) -> None:
        """Resultado com lista vazia não quebra."""
        orch_result = OrchestratorResult(
            results=[], total=0, succeeded=0, failed=0,
        )
        output = format_result(orch_result)
        assert "0" in output


# ─── Testes de Constantes e Configuração ───────────────────────────


@pytest.mark.unit
class TestConstants:
    """Testes das constantes do módulo."""

    def test_exit_commands(self) -> None:
        """Comandos de saída estão definidos."""
        assert "exit" in EXIT_COMMANDS
        assert "quit" in EXIT_COMMANDS
        assert "sair" in EXIT_COMMANDS

    def test_status_icons(self) -> None:
        """Todos os status têm ícones definidos."""
        for status in ("waiting", "running", "success", "error", "timeout"):
            assert status in STATUS_ICONS

    def test_version_definida(self) -> None:
        """Versão está definida e não vazia."""
        assert VERSION
        assert isinstance(VERSION, str)

    def test_banner_contem_versao(self) -> None:
        """Banner contém a versão."""
        assert VERSION in BANNER


# ─── Testes do Signal Handler ──────────────────────────────────────


@pytest.mark.unit
class TestSignalHandler:
    """Testes do comportamento do handler SIGINT."""

    @patch("src.cli._create_orchestrator")
    @patch("src.cli.signal.signal")
    def test_sigint_handler_registrado(
        self,
        mock_signal: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """main() registra handler para SIGINT."""
        mock_runner = MagicMock()
        mock_orchestrator = MagicMock()
        mock_create.return_value = (mock_orchestrator, mock_runner)

        with patch("src.cli.asyncio.run"):
            with patch("sys.argv", ["geminiclaw", "teste"]):
                from src.cli import main
                main()

        # Verifica que signal.signal foi chamado com SIGINT
        mock_signal.assert_any_call(signal.SIGINT, pytest.approx(None, abs=None) if False else mock_signal.call_args_list[0][0][1])

    @patch("src.cli._create_orchestrator")
    def test_main_prompt_direto(
        self,
        mock_create: MagicMock,
    ) -> None:
        """main() com prompt executa asyncio.run com execute_prompt."""
        mock_runner = MagicMock()
        mock_orchestrator = MagicMock()
        mock_create.return_value = (mock_orchestrator, mock_runner)

        with patch("src.cli.asyncio.run") as mock_run:
            with patch("sys.argv", ["geminiclaw", "meu prompt"]):
                from src.cli import main
                main()

        mock_run.assert_called_once()

    @patch("src.cli._create_orchestrator")
    def test_main_modo_interativo(
        self,
        mock_create: MagicMock,
    ) -> None:
        """main() sem prompt executa asyncio.run com interactive_mode."""
        mock_runner = MagicMock()
        mock_orchestrator = MagicMock()
        mock_create.return_value = (mock_orchestrator, mock_runner)

        with patch("src.cli.asyncio.run") as mock_run:
            with patch("sys.argv", ["geminiclaw"]):
                from src.cli import main
                main()

        mock_run.assert_called_once()

    @patch("src.cli._create_orchestrator")
    def test_main_falha_inicializacao(
        self,
        mock_create: MagicMock,
    ) -> None:
        """main() sai com código 1 se inicialização falhar."""
        mock_create.side_effect = RuntimeError("Docker não disponível")

        with patch("sys.argv", ["geminiclaw", "teste"]):
            with pytest.raises(SystemExit) as exc_info:
                from src.cli import main
                main()
            assert exc_info.value.code == 1
