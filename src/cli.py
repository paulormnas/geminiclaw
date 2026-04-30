"""Interface de linha de comando do GeminiClaw.

Ponto de entrada para o usuário interagir com o framework.
Suporta execução direta com prompt ou modo interativo (REPL).
"""

import argparse
import asyncio
import signal
import sys
import os
from pathlib import Path
from typing import NoReturn

# Adiciona a raiz do projeto ao sys.path para permitir imports de 'src'
# quando o script é executado diretamente (ex: python3 src/cli.py)
root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.logger import get_logger
from src.config import AGENT_TIMEOUT_SECONDS, DEFAULT_MODEL
from src.session import SessionManager
from src.runner import ContainerRunner
from src.ipc import IPCChannel
from src.orchestrator import Orchestrator, OrchestratorResult, AgentResult
from src.utils.terminal import (
    RESET, BOLD, DIM, GREEN, RED, YELLOW, CYAN, MAGENTA,
    STATUS_ICONS, BANNER, VERSION
)

logger = get_logger(__name__)

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
        "success": GREEN,
        "error": RED,
        "timeout": YELLOW,
    }.get(result.status, DIM)

    lines = [
        f"  {icon} {BOLD}{result.agent_id}{RESET} "
        f"[{status_color}{result.status}{RESET}]"
    ]

    if result.session_id:
        lines.append(f"     {DIM}sessão: {result.session_id}{RESET}")

    if result.status == "success" and result.response:
        lines.append(f"     {CYAN}resposta:{RESET}")
        for key, value in result.response.items():
            lines.append(f"       {DIM}•{RESET} {key}: {value}")

    if result.error:
        lines.append(f"     {RED}erro: {result.error}{RESET}")

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
    lines.append(f"\n{BOLD}{'─' * 42}{RESET}")
    lines.append(f"{BOLD}  📊 Resultado da Orquestração{RESET}")
    lines.append(f"{BOLD}{'─' * 42}{RESET}")

    # Resumo
    success_str = f"{GREEN}{result.succeeded}{RESET}"
    failed_str = f"{RED}{result.failed}{RESET}" if result.failed > 0 else f"{DIM}0{RESET}"
    lines.append(
        f"  Total: {BOLD}{result.total}{RESET}  |  "
        f"✅ {success_str}  |  ❌ {failed_str}"
    )
    lines.append("")

    # Detalhes de cada agente
    for agent_result in result.results:
        lines.append(format_agent_result(agent_result))
        lines.append("")

    lines.append(f"{DIM}{'─' * 42}{RESET}")
    return "\n".join(lines)


def show_history() -> None:
    """Exibe o histórico recente de execuções."""
    from src.history import ExecutionHistory
    from datetime import datetime
    
    history = ExecutionHistory()
    records = history.list_recent(limit=10)
    
    if not records:
        print(f"\n  {DIM}Nenhum histórico encontrado.{RESET}\n")
        return
        
    print(f"\n{BOLD}  📜 Histórico de Execuções (últimas 10){RESET}")
    print(f"{BOLD}{'─' * 80}{RESET}")
    
    for r in records:
        status_color = GREEN if r.status == "success" else RED
        date_str = "Desconhecido"
        if r.started_at:
            try:
                dt = datetime.fromisoformat(r.started_at.replace('Z', '+00:00'))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = r.started_at[:16]
                
        prompt_trunc = r.prompt[:40] + "..." if len(r.prompt) > 40 else r.prompt
        dur = f"{r.duration_seconds:.1f}s" if r.duration_seconds else "??"
        
        print(f"  {DIM}{r.id[:8]}{RESET} | {date_str} | [{status_color}{r.status.upper()}{RESET}] | ⏱  {dur} | {prompt_trunc}")
        
    print(f"{BOLD}{'─' * 80}{RESET}\n")


def _create_orchestrator() -> tuple[Orchestrator, ContainerRunner]:
    """Cria as dependências e retorna o orquestrador.

    Returns:
        Tupla com (Orchestrator, ContainerRunner).
    """
    session_manager = SessionManager()
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
    print(f"\n  {STATUS_ICONS['running']} {DIM}Processando...{RESET}\n")

    try:
        result = await orchestrator.handle_request(prompt)
        print(format_result(result))
    except Exception as e:
        logger.error("Erro ao processar prompt", extra={"error": str(e)})
        print(f"\n  {STATUS_ICONS['error']} {RED}Erro: {e}{RESET}\n")


async def interactive_mode(orchestrator: Orchestrator) -> None:
    """Executa a CLI em modo interativo (REPL).

    Args:
        orchestrator: Instância do orquestrador.
    """
    print(BANNER)
    print(f"  {DIM}Modo interativo. Digite 'sair' para encerrar.{RESET}\n")

    while True:
        try:
            prompt = input(f"  {MAGENTA}🔮 >{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n  {DIM}Encerrando...{RESET}")
            break

        if not prompt:
            continue

        if prompt.lower() in EXIT_COMMANDS:
            print(f"\n  {DIM}Até logo! 👋{RESET}\n")
            break

        await execute_prompt(orchestrator, prompt)


def main() -> None:
    """Ponto de entrada principal da CLI."""
    parser = build_parser()
    args = parser.parse_args()

    runner: ContainerRunner | None = None

    def _signal_handler(sig: int, frame: object) -> None:
        """Handler para SIGINT (Ctrl+C)."""
        print(f"\n\n  {YELLOW}⚠  Interrupção recebida. Encerrando containers...{RESET}")
        if runner is not None:
            try:
                runner.cleanup_all()
                print(f"  {GREEN}✅ Cleanup concluído.{RESET}\n")
            except Exception as e:
                logger.error("Erro durante cleanup", extra={"error": str(e)})
                print(f"  {RED}❌ Erro no cleanup: {e}{RESET}\n")
        sys.exit(130)

    signal.signal(signal.SIGINT, _signal_handler)

    if args.prompt:
        if args.prompt.lower() == "history":
            show_history()
            sys.exit(0)

    try:
        orchestrator, runner = _create_orchestrator()
    except RuntimeError as e:
        print(f"\n  {STATUS_ICONS['error']} {RED}Falha na inicialização: {e}{RESET}\n")
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
