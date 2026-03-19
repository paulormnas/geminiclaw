"""Interface de linha de comando do GeminiClaw.

Ponto de entrada para o usuário interagir com o framework.
Suporta execução direta com prompt ou modo interativo (REPL).
"""

import argparse
import asyncio
import signal
import sys
from typing import NoReturn

from src.logger import get_logger
from src.config import AGENT_TIMEOUT_SECONDS, DEFAULT_MODEL, SQLITE_DB_PATH
from src.session import SessionManager
from src.runner import ContainerRunner
from src.ipc import IPCChannel
from src.orchestrator import Orchestrator, OrchestratorResult, AgentResult

logger = get_logger(__name__)

# Códigos ANSI para cores no terminal
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"

# Ícones de status
STATUS_ICONS: dict[str, str] = {
    "waiting": "⏳",
    "running": "🔄",
    "success": "✅",
    "error": "❌",
    "timeout": "⏰",
}

VERSION = "0.1.0"

BANNER = f"""{_CYAN}{_BOLD}
  ╔═══════════════════════════════════════╗
  ║          🔮 GeminiClaw v{VERSION}          ║
  ║   Framework de Orquestração de IA     ║
  ╚═══════════════════════════════════════╝
{_RESET}"""

EXIT_COMMANDS = {"exit", "quit", "sair"}


def build_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos da CLI.

    Returns:
        Parser configurado com todos os argumentos suportados.
    """
    parser = argparse.ArgumentParser(
        prog="geminiclaw",
        description="GeminiClaw — Framework de orquestração de agentes IA.",
        epilog="Sem argumentos, entra em modo interativo (REPL).",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="Prompt a ser enviado ao orquestrador. Se omitido, entra em modo interativo.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=AGENT_TIMEOUT_SECONDS,
        help=f"Timeout em segundos para cada agente (padrão: {AGENT_TIMEOUT_SECONDS}).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Modelo Gemini a ser utilizado (padrão: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    return parser


def format_agent_result(result: AgentResult) -> str:
    """Formata o resultado de um agente para exibição no terminal.

    Args:
        result: Resultado da execução do agente.

    Returns:
        String formatada para exibição.
    """
    icon = STATUS_ICONS.get(result.status, "❓")
    status_color = {
        "success": _GREEN,
        "error": _RED,
        "timeout": _YELLOW,
    }.get(result.status, _DIM)

    lines = [
        f"  {icon} {_BOLD}{result.agent_id}{_RESET} "
        f"[{status_color}{result.status}{_RESET}]"
    ]

    if result.session_id:
        lines.append(f"     {_DIM}sessão: {result.session_id}{_RESET}")

    if result.status == "success" and result.response:
        lines.append(f"     {_CYAN}resposta:{_RESET}")
        for key, value in result.response.items():
            lines.append(f"       {_DIM}•{_RESET} {key}: {value}")

    if result.error:
        lines.append(f"     {_RED}erro: {result.error}{_RESET}")

    return "\n".join(lines)


def format_result(result: OrchestratorResult) -> str:
    """Formata o resultado consolidado para exibição no terminal.

    Args:
        result: Resultado consolidado do orquestrador.

    Returns:
        String formatada para exibição.
    """
    lines: list[str] = []

    # Cabeçalho do resultado
    lines.append(f"\n{_BOLD}{'─' * 42}{_RESET}")
    lines.append(f"{_BOLD}  📊 Resultado da Orquestração{_RESET}")
    lines.append(f"{_BOLD}{'─' * 42}{_RESET}")

    # Resumo
    success_str = f"{_GREEN}{result.succeeded}{_RESET}"
    failed_str = f"{_RED}{result.failed}{_RESET}" if result.failed > 0 else f"{_DIM}0{_RESET}"
    lines.append(
        f"  Total: {_BOLD}{result.total}{_RESET}  |  "
        f"✅ {success_str}  |  ❌ {failed_str}"
    )
    lines.append("")

    # Detalhes de cada agente
    for agent_result in result.results:
        lines.append(format_agent_result(agent_result))
        lines.append("")

    lines.append(f"{_DIM}{'─' * 42}{_RESET}")
    return "\n".join(lines)


def _create_orchestrator() -> tuple[Orchestrator, ContainerRunner]:
    """Cria as dependências e retorna o orquestrador.

    Returns:
        Tupla com (Orchestrator, ContainerRunner).
    """
    session_manager = SessionManager(SQLITE_DB_PATH)
    runner = ContainerRunner()
    ipc = IPCChannel()
    orchestrator = Orchestrator(
        runner=runner,
        ipc=ipc,
        session_manager=session_manager,
    )
    return orchestrator, runner


async def execute_prompt(orchestrator: Orchestrator, prompt: str) -> None:
    """Executa um prompt no orquestrador e exibe o resultado.

    Args:
        orchestrator: Instância do orquestrador.
        prompt: Prompt do usuário.
    """
    print(f"\n  {STATUS_ICONS['running']} {_DIM}Processando...{_RESET}\n")

    try:
        result = await orchestrator.handle_request(prompt)
        print(format_result(result))
    except Exception as e:
        logger.error("Erro ao processar prompt", extra={"error": str(e)})
        print(f"\n  {STATUS_ICONS['error']} {_RED}Erro: {e}{_RESET}\n")


async def interactive_mode(orchestrator: Orchestrator) -> None:
    """Executa a CLI em modo interativo (REPL).

    Args:
        orchestrator: Instância do orquestrador.
    """
    print(BANNER)
    print(f"  {_DIM}Modo interativo. Digite 'sair' para encerrar.{_RESET}\n")

    while True:
        try:
            prompt = input(f"  {_MAGENTA}🔮 >{_RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n  {_DIM}Encerrando...{_RESET}")
            break

        if not prompt:
            continue

        if prompt.lower() in EXIT_COMMANDS:
            print(f"\n  {_DIM}Até logo! 👋{_RESET}\n")
            break

        await execute_prompt(orchestrator, prompt)


def main() -> None:
    """Ponto de entrada principal da CLI."""
    parser = build_parser()
    args = parser.parse_args()

    runner: ContainerRunner | None = None

    def _signal_handler(sig: int, frame: object) -> None:
        """Handler para SIGINT (Ctrl+C)."""
        print(f"\n\n  {_YELLOW}⚠  Interrupção recebida. Encerrando containers...{_RESET}")
        if runner is not None:
            try:
                runner.cleanup_all()
                print(f"  {_GREEN}✅ Cleanup concluído.{_RESET}\n")
            except Exception as e:
                logger.error("Erro durante cleanup", extra={"error": str(e)})
                print(f"  {_RED}❌ Erro no cleanup: {e}{_RESET}\n")
        sys.exit(130)

    signal.signal(signal.SIGINT, _signal_handler)

    try:
        orchestrator, runner = _create_orchestrator()
    except RuntimeError as e:
        print(f"\n  {STATUS_ICONS['error']} {_RED}Falha na inicialização: {e}{_RESET}\n")
        logger.error("Falha ao inicializar CLI", extra={"error": str(e)})
        sys.exit(1)

    if args.prompt:
        # Modo direto: executa o prompt e sai
        asyncio.run(execute_prompt(orchestrator, args.prompt))
    else:
        # Modo interativo (REPL)
        asyncio.run(interactive_mode(orchestrator))


if __name__ == "__main__":
    main()
