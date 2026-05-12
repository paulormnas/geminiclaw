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
    parser.add_argument(
        "--metrics",
        type=str,
        metavar="EXECUTION_ID",
        default=None,
        help="Exibe métricas de telemetria de uma execução específica.",
    )
    parser.add_argument(
        "--export",
        type=str,
        metavar="EXECUTION_ID",
        default=None,
        help="Exporta métricas de telemetria de uma execução para CSV.",
    )
    parser.add_argument(
        "--export-dir",
        type=str,
        default="./metrics",
        help="Diretório de saída para exportação CSV (padrão: ./metrics).",
    )
    parser.add_argument(
        "--log",
        type=str,
        metavar="SESSION_ID",
        default=None,
        help="Exibe e agrega os logs de todos os agentes de uma sessão.",
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
        
    _sep = "─" * 80
    print(f"{BOLD}{_sep}{RESET}\n")


def show_metrics(execution_id: str) -> None:
    """Exibe métricas de telemetria de uma execução.

    Args:
        execution_id: ID da execução a consultar.
    """
    from src.telemetry import get_telemetry

    tel = get_telemetry()

    _sep = "─" * 80
    print(f"\n{BOLD}  \U0001f4ca M\u00e9tricas de Telemetria \u2014 {DIM}{execution_id}{RESET}")
    print(f"{BOLD}{_sep}{RESET}")

    # Timeline de eventos
    timeline = tel.get_execution_timeline(execution_id)
    if timeline:
        print(f"\n  {BOLD}{CYAN}Timeline de Agentes ({len(timeline)} eventos){RESET}")
        for ev in timeline[:20]:  # mostra até 20 eventos
            ts = str(ev.get("timestamp", ""))[:19]
            agent = ev.get("agent_id", "?")
            etype = ev.get("event_type", "?")
            task = ev.get("task_name") or ""
            dur = f"  [{ev['duration_ms']}ms]" if ev.get("duration_ms") else ""
            print(f"    {DIM}{ts}{RESET}  {CYAN}{agent:<18}{RESET} {BOLD}{etype:<22}{RESET} {DIM}{task}{dur}{RESET}")
        if len(timeline) > 20:
            print(f"    {DIM}... e mais {len(timeline) - 20} eventos{RESET}")
    else:
        print(f"  {DIM}Nenhum evento de agente registrado.{RESET}")

    # Subtask Summary (Roadmap V9)
    subtasks = tel.get_subtask_metrics(execution_id)
    if subtasks:
        print(f"\n  {BOLD}{CYAN}Performance por Subtarefa (Roadmap V9){RESET}")
        header = f"    {'TASK':<25} {'AGENT':<12} {'STATUS':<10} {'DUR':>8} {'WAIT':>8} {'TOKENS':>8}"
        print(f"    {DIM}{header}{RESET}")
        for s in subtasks:
            name = (s['task_name'] or "unnamed")[:25]
            agent = s['agent_id'][:12]
            status = s['status']
            color = GREEN if status == "success" else (RED if status in ("error", "failure") else YELLOW)
            
            dur = f"{s['duration_total_ms']/1000:.1f}s" if s['duration_total_ms'] else "N/A"
            wait = f"{s['waiting_time_ms']/1000:.1f}s" if s['waiting_time_ms'] else "0s"
            tokens = s['total_tokens'] or 0
            
            print(f"    {name:<25} {agent:<12} {color}{status:<10}{RESET} {dur:>8} {wait:>8} {tokens:>8}")
    

    # Token summary
    token_sum = tel.get_token_summary(execution_id)
    by_provider = token_sum.get("by_provider_model", [])
    if by_provider:
        print(f"\n  {BOLD}{MAGENTA}Consumo de Tokens por Modelo{RESET}")
        for row in by_provider:
            prov = f"{row.get('llm_provider', '?')}/{row.get('llm_model', '?')}"
            tot = row.get("total_tokens", 0)
            lat = f"{row.get('avg_latency_ms', 0):.0f}ms" if row.get('avg_latency_ms') else "N/A"
            calls = row.get("calls", 0)
            cost = f"${row.get('total_cost_usd', 0):.4f}" if row.get('total_cost_usd') else "local"
            print(f"    {DIM}•{RESET} {prov:<35} {tot:>8} tokens  |  {lat:>8} avg  |  {calls:>4} chamadas  |  {cost}")

    # Tool summary
    tool_sum = tel.get_tool_summary(execution_id)
    by_tool = tool_sum.get("by_tool", [])
    if by_tool:
        print(f"\n  {BOLD}{GREEN}Uso de Ferramentas{RESET}")
        for row in by_tool:
            tool = row.get("tool_name", "?")
            calls = row.get("total_calls", 0)
            ok = row.get("successful", 0)
            avg_ms = f"{row.get('avg_duration_ms', 0):.0f}ms" if row.get('avg_duration_ms') else "N/A"
            pct = f"{ok/calls*100:.0f}%" if calls else "0%"
            print(f"    {DIM}•{RESET} {tool:<30} {calls:>4} calls  |  {pct:>6} OK  |  {avg_ms:>8} avg")

    # Hardware peaks
    hw = tel.get_hardware_peaks(execution_id)
    if hw:
        print(f"\n  {BOLD}{YELLOW}Picos de Hardware{RESET}")
        temp = hw.get("max_temp_c")
        cpu = hw.get("max_cpu_pct")
        mem = hw.get("max_mem_pct")
        throttle = hw.get("throttle_incidents", 0)
        if temp:
            print(f"    {DIM}•{RESET} Temp máxima CPU:    {temp:.1f}°C")
        if cpu:
            print(f"    {DIM}•{RESET} CPU máxima:        {cpu:.1f}%")
        if mem:
            print(f"    {DIM}•{RESET} Memória máxima:    {mem:.1f}%")
        if throttle:
            print(f"    {DIM}•{RESET} {RED}Throttling incidents: {throttle}{RESET}")

    # Métricas derivadas
    derived = tel.get_derived_metrics(execution_id)
    if derived:
        print(f"\n  {BOLD}Métricas Derivadas{RESET}")
        for k, v in derived.items():
            val = f"{v:.2f}" if isinstance(v, float) else str(v)
            print(f"    {DIM}•{RESET} {k:<40} {val}")

    _sep2 = "─" * 80
    print(f"\n{DIM}{_sep2}{RESET}")
    print(f"  {DIM}Use --export {execution_id} para exportar em CSV.{RESET}\n")


def show_session_logs(session_id: str) -> None:
    """Agrega e exibe os logs de todos os agentes de uma sessão em ordem cronológica.

    Args:
        session_id: ID (slug) da sessão.
    """
    from src.output_manager import OutputManager
    import json
    
    om = OutputManager()
    logs_dir = om.get_logs_dir(session_id)
    
    if not logs_dir.exists():
        print(f"\n  {RED}❌ Erro: Diretório de logs não encontrado para a sessão {session_id}{RESET}\n")
        return
        
    all_logs = []
    for log_file in logs_dir.glob("*.log"):
        agent_id = log_file.stem
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        entry["_agent"] = agent_id
                        all_logs.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"  {YELLOW}⚠ Aviso: Erro ao ler log {log_file.name}: {e}{RESET}")

    if not all_logs:
        print(f"\n  {DIM}Nenhum log estruturado encontrado na sessão {session_id}.{RESET}\n")
        return

    # Ordena por timestamp
    all_logs.sort(key=lambda x: x.get("timestamp", ""))

    print(f"\n{BOLD}  📋 Logs Agregados — Sessão: {DIM}{session_id}{RESET}")
    print(f"{BOLD}{'─' * 100}{RESET}")
    
    for entry in all_logs:
        ts = entry.get("timestamp", "")[11:19] # HH:MM:SS
        agent = entry.get("_agent", "unknown")
        level = entry.get("level", "INFO")
        msg = entry.get("message", "")
        
        color = DIM
        if level == "ERROR": color = RED
        elif level == "WARNING": color = YELLOW
        elif level == "INFO": color = GREEN
        
        agent_color = CYAN if agent == "orchestrator" else MAGENTA
        
        print(f"  {DIM}{ts}{RESET} | {agent_color}{agent:<12}{RESET} | {color}{level:<7}{RESET} | {msg}")

    print(f"{BOLD}{'─' * 100}{RESET}\n")


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

    # Subcomando: --metrics <execution_id>
    if args.metrics:
        from src.db import get_pool
        pool = get_pool()
        pool.open()
        try:
            show_metrics(args.metrics)
        finally:
            pool.close()
        sys.exit(0)

    # Subcomando: --export <execution_id>
    if args.export:
        from scripts.export_metrics import export_all
        from src.db import get_pool
        pool = get_pool()
        pool.open()
        try:
            export_all(args.export, Path(args.export_dir))
        finally:
            pool.close()
        sys.exit(0)

    # Subcomando: --log <session_id>
    if args.log:
        show_session_logs(args.log)
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
