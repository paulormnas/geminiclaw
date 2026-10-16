"""Testes unitários para src/cli/main.py.

Cobre parsing de argumentos, formatação de resultados,
e comportamento do handler de SIGINT.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.cli.main import build_parser
from src.cli.repl import EXIT_COMMANDS
from src.cli.reports import format_agent_result, format_result
from src.orchestration.orchestrator import AgentResult, OrchestratorResult
from src.utils.terminal import BANNER, STATUS_ICONS, VERSION

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

    def test_timeout_nao_e_argumento_da_cli(self) -> None:
        """O tempo limite do agente vem de AGENT_TIMEOUT_SECONDS; a CLI não tem --timeout."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--timeout", "60", "meu prompt"])

    def test_flag_model(self) -> None:
        """Parser aceita flag --model."""
        parser = build_parser()
        args = parser.parse_args(["--model", "gemini-pro", "teste"])
        assert args.model == "gemini-pro"

    def test_model_padrao(self) -> None:
        """Sem --model não há pin: o catálogo decide o modelo do researcher (ADR 017)."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.model is None

    def test_model_e_pin_provedor_modelo(self) -> None:
        """--model recebe o pin provedor/modelo do researcher."""
        args = build_parser().parse_args(["--model", "ollama/qwen3:8b"])
        assert args.model == "ollama/qwen3:8b"

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
class TestMainDispatch:
    """``main()`` só despacha: toda pesquisa roda em processo próprio (v18.7-background-sessions, design §1.1)."""

    def _run(self, argv: list[str], target: str, result: int = 0) -> tuple[int, MagicMock]:
        mock = MagicMock(return_value=object())
        with (
            patch("sys.argv", ["geminiclaw", *argv]),
            patch(f"src.cli.main.{target}", mock),
            patch("src.cli.main.asyncio.run", return_value=result) as run,
            patch("src.cli.main.install_provider_resolver"),
        ):
            from src.cli.main import main

            with pytest.raises(SystemExit) as exc_info:
                main()
        run.assert_any_call(mock.return_value)
        return exc_info.value.code, mock

    def test_prompt_direto_sai_com_o_codigo_da_sessao(self) -> None:
        code, start = self._run(["meu prompt"], "start_research", result=3)
        assert code == 3
        assert start.call_args.args[0] == "meu prompt"
        assert start.call_args.kwargs["background"] is False

    def test_background_e_repassado(self) -> None:
        _, start = self._run(["--background", "--mode", "auto", "meu prompt"], "start_research")
        assert start.call_args.kwargs["background"] is True and start.call_args.kwargs["mode"] == "auto"

    def test_resume_e_continue_vao_ao_modulo_direto(self) -> None:
        code, resume = self._run(["resume", "--session", "sessao-a"], "resume_research", result=4)
        assert code == 4 and resume.call_args.args[0] == "sessao-a"
        _, cont = self._run(["continue", "--project", "p1"], "continue_project")
        assert cont.call_args.args[0] == "p1"

    def test_sem_prompt_abre_o_repl(self) -> None:
        with patch("src.observability.telemetry.get_telemetry"):
            code, repl = self._run([], "interactive_mode")
        assert code == 0 and repl.call_args.kwargs["mode"]

    def test_background_sem_tarefa_e_recusado(self) -> None:
        with patch("sys.argv", ["geminiclaw", "--background"]), patch("src.cli.main.install_provider_resolver"):
            from src.cli.main import main

            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
