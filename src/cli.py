"""Interface de linha de comando do assistente digital de pesquisa (ADR 010).

Ponto de entrada para o pesquisador interagir com o framework.
Suporta execução direta com prompt ou modo interativo (REPL).
"""

import argparse
import asyncio
import signal
import sys
import os
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, Any

if TYPE_CHECKING:
    from src.llm.session import SessionRouting
    from src.project_session import ProjectBinder

# Adiciona a raiz do projeto ao sys.path para permitir imports de 'src'
# quando o script é executado diretamente (ex: python3 src/cli.py)
root_path = str(Path(__file__).parent.parent)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from src.logger import get_logger
from src.config import (
    AGENT_TIMEOUT_SECONDS,
    APP_NAME,
    SessionMode,
    SESSION_DEFAULT_MODE,
    INPUT_CONTEXT_DIR,
    CONTEXT_TOKEN_WARNING_THRESHOLD,
    OUTPUT_BASE_DIR,
)
from src.session import SessionManager
from src.infrastructure import ensure_infrastructure
from src.orchestrator import Orchestrator, OrchestratorResult, AgentResult
from src.context_loader import ContextLoader, ContextBundle
from src.usage import UsageBudget
from src.utils.terminal import (
    RESET, BOLD, DIM, GREEN, RED, YELLOW, CYAN, MAGENTA,
    STATUS_ICONS, BANNER, VERSION
)

logger = get_logger(__name__)

EXIT_COMMANDS = {"exit", "quit", "sair"}

# Roadmap V15.6 / Spec G10 — texto de ajuda completo exibido em --help / -h / sem argumentos
_BANNER_TITLE = f"{APP_NAME} — Assistente Digital de Pesquisa Científica"
FULL_HELP_TEXT = f"""{CYAN}{BOLD}
╔══════════════════════════════════════════════════════════════╗
║{_BANNER_TITLE:^62}║
╚══════════════════════════════════════════════════════════════╝
{RESET}
{BOLD}USO:{RESET}
  geminiclaw [opções] "<tarefa>"
  geminiclaw sessions
  geminiclaw stop [--session <id>]
  geminiclaw resume --session <id>
  geminiclaw convert --session <id> --format latex|html|docx
  geminiclaw clear-context
  geminiclaw history
  geminiclaw embeddings reindex [--collection <nome>] [--yes]
  geminiclaw project new --titulo <t> --objetivo <o> [--dominio <termo>]|list [--status <s>]|show <id>|use <id>
  geminiclaw --project <id> "<tarefa>"
  geminiclaw vocab pending|approve <id>|reject <id> [--motivo <texto>]|map <id> --para <id>
  geminiclaw knowledge stats|reindex [--yes]|sync [--session <id>]
  geminiclaw --metrics <execution_id>

{BOLD}MODOS DE OPERAÇÃO (--mode):{RESET}
  {GREEN}assisted{RESET}   Padrão. Consulta o pesquisador apenas quando o contexto
              está genuinamente ausente. Divergências são investigadas
              autonomamente antes de qualquer consulta.

  {YELLOW}semi{RESET}       Nunca bloqueia. Faz suposições razoáveis, documenta
              todas as decisões e continua. Ideal para execuções
              longas sem supervisão ativa.

  {RED}auto{RESET}       Totalmente autônomo. Consulta a web para resolver
              incertezas técnicas. Use apenas sem pesquisador disponível.

{BOLD}CONTEXTO DE ENTRADA:{RESET}
  Deposite arquivos em input_context/ antes de executar:
    context.md   → objetivo, hipóteses, instruções
    artigo.pdf   → artigos de referência
    dados.csv    → datasets
    imagem.tif   → imagens para análise
  Use 'geminiclaw clear-context' para limpar input_context/ entre sessões.

{BOLD}EXEMPLOS:{RESET}
  geminiclaw "Reproduza a Tabela 3 do artigo"
  geminiclaw --mode semi "Análise exploratória do dataset"
  geminiclaw --mode auto "Execute sem interrupção"
  geminiclaw sessions
  geminiclaw stop --session 20260922_iris
  geminiclaw convert --session 20260922_iris --format latex

{BOLD}RELATÓRIO:{RESET}
  Sempre gerado em outputs/<session>/relatorio_final.md.
  Use 'geminiclaw convert' para gerar também em LaTeX, DOCX ou HTML.
"""


def print_full_help() -> None:
    """Exibe o texto de ajuda completo (banner + modos + exemplos)."""
    print(FULL_HELP_TEXT)


def build_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos da CLI.

    Returns:
        Parser configurado com todos os argumentos suportados.
    """
    parser = argparse.ArgumentParser(
        prog="geminiclaw",
        description=f"{APP_NAME} — assistente digital de pesquisa científica.",
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
        default=None,
        metavar="PROVEDOR/MODELO",
        help=(
            "Pin de modelo do papel researcher no formato provedor/modelo (ex.: ollama/qwen3:8b); "
            "sujeito à política LLM_DATA_POLICY e à disponibilidade. Sem ele, o catálogo decide."
        ),
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
    parser.add_argument(
        "--session",
        type=str,
        metavar="SESSION_ID",
        default=None,
        help="ID da sessão alvo para operações direcionadas (ex: stop --session <id>).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=[m.value for m in SessionMode],
        default=None,
        help=(
            "Nível de autonomia da sessão: assisted (padrão), semi ou auto "
            f"(padrão configurável via SESSION_DEFAULT_MODE, atualmente '{SESSION_DEFAULT_MODE}')."
        ),
    )
    parser.add_argument(
        "--project",
        type=str,
        metavar="PROJETO_ID",
        default=None,
        help=(
            "Projeto de pesquisa da sessão (ver `geminiclaw project list`). Sem ele, usa o projeto "
            "padrão (`project use`) ou cria um projeto a partir do prompt."
        ),
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["latex", "html", "docx"],
        default=None,
        help="Formato de saída para 'geminiclaw convert --session <id> --format <fmt>'.",
    )
    # Roadmap V18 / Spec usage-limits — orçamento de uso da sessão (overrides de config).
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        metavar="N",
        help="Limite de tokens da sessão, todos os agentes inclusos (padrão: SESSION_MAX_TOKENS).",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        metavar="N",
        help="Limite de tempo de relógio da sessão, em minutos (padrão: SESSION_MAX_MINUTES).",
    )
    parser.add_argument(
        "--max-task-retries",
        type=int,
        default=None,
        metavar="N",
        help="Limite de retentativas da mesma tarefa (padrão: SESSION_MAX_TASK_RETRIES).",
    )
    parser.add_argument(
        "--max-connection-retries",
        type=int,
        default=None,
        metavar="N",
        help="Limite de retentativas de conexão da sessão (padrão: SESSION_MAX_CONNECTION_RETRIES).",
    )
    return parser


def build_usage_budget(args: "argparse.Namespace") -> UsageBudget:
    """Constrói o `UsageBudget` efetivo da sessão a partir dos argumentos da CLI.

    Args:
        args: Argumentos parseados por `build_parser()`.

    Returns:
        `UsageBudget` com os defaults de `src/config.py`, sobrescritos pelas
        opções ``--max-tokens``, ``--max-minutes``, ``--max-task-retries`` e
        ``--max-connection-retries`` quando fornecidas.
    """
    return UsageBudget.from_config(
        max_tokens=getattr(args, "max_tokens", None),
        max_minutes=getattr(args, "max_minutes", None),
        max_task_retries=getattr(args, "max_task_retries", None),
        max_connection_retries=getattr(args, "max_connection_retries", None),
    )


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


def load_context_with_confirmation(context_dir: str | None = None) -> ContextBundle | None:
    """Carrega `input_context/` e confirma com o pesquisador se o volume for grande
    (Roadmap V15.5 / Spec G9).

    Args:
        context_dir: Diretório de contexto a carregar (usa o padrão de config se omitido).

    Returns:
        O `ContextBundle` carregado, ou None se o pesquisador optou por não continuar.
    """
    bundle = ContextLoader(context_dir).load()

    if bundle.total_files == 0:
        print(f"  {DIM}📂 Nenhum contexto encontrado em input_context/.{RESET}")
        return bundle

    print(
        f"  {GREEN}📂 Contexto carregado:{RESET} {bundle.total_files} arquivo(s) "
        f"({bundle.total_tokens_estimated} tokens estimados)"
    )

    if bundle.total_tokens_estimated > CONTEXT_TOKEN_WARNING_THRESHOLD:
        print(
            f"  {YELLOW}⚠ Contexto muito grande (~{bundle.total_tokens_estimated} tokens).{RESET} "
            f"Recomendado: remover arquivos menos relevantes ou usar chunking."
        )
        answer = input("  Continuar? [s/N] ").strip().lower()
        if answer not in ("s", "sim", "y", "yes"):
            print(f"  {DIM}Execução cancelada pelo pesquisador.{RESET}")
            return None

    return bundle


def print_context_lifecycle_message(session_id: str, bundle: ContextBundle) -> None:
    """Exibe a instrução de gestão do ciclo de vida do contexto ao final da sessão
    (Roadmap V15.5 / Spec G9).
    """
    if bundle.total_files == 0:
        return
    print(
        f"\n  {DIM}Contexto salvo em outputs/{session_id}/input_snapshot/. "
        f"Execute 'geminiclaw clear-context' para limpar input_context/ para a próxima sessão.{RESET}"
    )


def clear_context(context_dir: str | None = None) -> None:
    """Limpa `input_context/` após confirmação do pesquisador (Roadmap V15.5 / Spec G9)."""
    target_dir = Path(context_dir or INPUT_CONTEXT_DIR)
    if not target_dir.is_dir():
        print(f"\n  {DIM}input_context/ não existe — nada para limpar.{RESET}\n")
        return

    files = [p for p in target_dir.iterdir() if p.is_file() and p.name != "README.md"]
    dirs = [p for p in target_dir.iterdir() if p.is_dir()]
    if not files and not dirs:
        print(f"\n  {DIM}input_context/ já está vazio.{RESET}\n")
        return

    print(f"\n  {YELLOW}⚠ Isso removerá {len(files) + len(dirs)} item(ns) de input_context/ (README.md é preservado).{RESET}")
    answer = input("  Confirmar limpeza? [s/N] ").strip().lower()
    if answer not in ("s", "sim", "y", "yes"):
        print(f"  {DIM}Operação cancelada.{RESET}\n")
        return

    import shutil
    for p in files:
        p.unlink()
    for d in dirs:
        shutil.rmtree(d)

    print(f"  {GREEN}✅ input_context/ limpo com sucesso.{RESET}\n")


async def resume_session(orchestrator: Orchestrator, session_id: str) -> None:
    """Retoma uma sessão suspensa (Roadmap V15.3 / Spec G5).

    Limitação conhecida: o framework não faz checkpoint do estado de execução do DAG,
    então "retomar" reinicia o ciclo de planejamento a partir do prompt original —
    não é uma resumição exata do ponto de suspensão. Artefatos já gerados antes da
    suspensão permanecem em `outputs/<session_id>/` e são reconhecidos e reaproveitados
    pelo Developer Agent (WorkspaceManifest), reduzindo retrabalho na prática.

    Args:
        orchestrator: Instância do orquestrador.
        session_id: ID da sessão suspensa a retomar.
    """
    session = orchestrator.session_manager.get(session_id)
    if session is None:
        print(f"\n  {RED}❌ Sessão '{session_id}' não encontrada.{RESET}\n")
        return
    if session.status != "suspended":
        print(f"\n  {YELLOW}⚠ Sessão '{session_id}' não está suspensa (status: {session.status}).{RESET}\n")
        return

    original_prompt = session.payload.get("prompt")
    if not original_prompt:
        print(f"\n  {RED}❌ Sessão '{session_id}' não tem um prompt original registrado — não é possível retomar.{RESET}\n")
        return

    mode = session.payload.get("mode", SESSION_DEFAULT_MODE)
    print(
        f"\n  {DIM}Retomando a partir do prompt original em um novo ciclo de planejamento "
        f"(modo: {mode}). Artefatos da sessão suspensa permanecem em outputs/{session_id}/ "
        f"e são reaproveitados automaticamente quando reconhecidos pelo Developer Agent.{RESET}\n"
    )

    context_bundle = load_context_with_confirmation()
    if context_bundle is None:
        return

    await execute_prompt(orchestrator, original_prompt, mode=mode, context_bundle=context_bundle)


def convert_report(session_id: str, format: str) -> None:
    """Converte o relatório final de uma sessão para outro formato (Roadmap V15.4 / Spec G8).

    Args:
        session_id: ID da sessão cujo `relatorio_final.md` será convertido.
        format: Formato de saída (``latex`` | ``html`` | ``docx``).
    """
    from src.report.base_converter import ReportConverterFactory

    session_dir = Path(OUTPUT_BASE_DIR) / session_id
    markdown_path = session_dir / "relatorio_final.md"
    if not markdown_path.exists():
        print(f"\n  {RED}❌ Sessão '{session_id}' não encontrada em /outputs/ (ou sem relatorio_final.md).{RESET}\n")
        return

    try:
        converter = ReportConverterFactory.create(format)
    except ValueError as e:
        print(f"\n  {RED}❌ {e}{RESET}\n")
        return

    extension = {"latex": "tex", "html": "html", "docx": "docx"}[format.lower().strip()]
    output_path = session_dir / f"relatorio_final.{extension}"
    try:
        converter.convert(markdown_path, output_path)
    except Exception as e:
        print(f"\n  {RED}❌ Falha ao converter relatório: {e}{RESET}\n")
        logger.error("Falha ao converter relatório", extra={"session_id": session_id, "format": format, "error": str(e)})
        return

    print(f"\n  {GREEN}✅ Relatório convertido: {output_path}{RESET}\n")


def run_embeddings_reindex(collection: str | None, auto_confirm: bool) -> None:
    """Executa `geminiclaw embeddings reindex` (Roadmap V16 / ADR 011 §3).

    Revetoriza as coleções do Qdrant com o provedor de embeddings local
    atualmente configurado. É uma operação sobre dados persistidos: apaga os
    vetores existentes de cada ponto reescrito. Por isso, pede confirmação
    interativa a menos que `--yes` seja informado (AGENTS.md §1 regra 5).

    Args:
        collection: Nome da coleção a reindexar, ou None para reindexar todas
            as coleções reindexáveis (`geminiclaw_knowledge`,
            `geminiclaw_documents`).
        auto_confirm: Se True, pula a confirmação interativa.
    """
    from src.embeddings.reindex import (
        REINDEXABLE_COLLECTIONS,
        CollectionNotFoundError,
        CollectionReindexer,
    )

    if collection is not None and collection not in REINDEXABLE_COLLECTIONS:
        print(
            f"\n  {RED}❌ Coleção '{collection}' não é reindexável. "
            f"Coleções suportadas: {', '.join(REINDEXABLE_COLLECTIONS)}.{RESET}\n"
        )
        sys.exit(1)

    targets = [collection] if collection else list(REINDEXABLE_COLLECTIONS)

    print(f"\n  {CYAN}Verificando pontos desatualizados...{RESET}")
    reindexers: dict[str, CollectionReindexer] = {}
    outdated_counts: dict[str, int] = {}
    for name in targets:
        reindexer = CollectionReindexer(name)
        try:
            outdated_counts[name] = reindexer.count_outdated()
            reindexers[name] = reindexer
        except CollectionNotFoundError:
            print(f"  {YELLOW}⚠ Coleção '{name}' não existe no Qdrant configurado — ignorada.{RESET}")

    if not reindexers:
        print(f"\n  {YELLOW}Nenhuma coleção reindexável encontrada no Qdrant configurado.{RESET}\n")
        return

    total_outdated = sum(outdated_counts.values())
    print(f"\n  {BOLD}Resumo:{RESET}")
    for name, count in outdated_counts.items():
        print(f"    {name}: {count} ponto(s) desatualizado(s)")

    if total_outdated == 0:
        print(f"\n  {GREEN}✅ Todas as coleções já estão vetorizadas com o modelo atual.{RESET}\n")
        return

    print(
        f"\n  {YELLOW}⚠ Esta operação reescreve vetores persistidos no Qdrant e é IRREVERSÍVEL "
        f"para os pontos afetados.{RESET}"
    )
    if not auto_confirm:
        answer = input(f"  Confirma a reindexação de {total_outdated} ponto(s)? [s/N] ").strip().lower()
        if answer not in ("s", "sim", "y", "yes"):
            print(f"\n  {YELLOW}Reindexação cancelada pelo usuário.{RESET}\n")
            return

    for name, reindexer in reindexers.items():
        print(f"\n  {CYAN}Reindexando '{name}'...{RESET}")
        report = reindexer.run()
        print(f"  {GREEN}{report.summary()}{RESET}")
        if report.recreated_collection:
            print(
                f"  {YELLOW}⚠ A dimensão do modelo mudou: '{name}' foi recriada vazia. "
                f"Reingerir a fonte (crawl/documentos) para repovoá-la.{RESET}"
            )
    print()


def print_session_banner(
    mode: str,
    context_dir: str = "input_context",
    budget: UsageBudget | None = None,
    llm_routing: "SessionRouting | None" = None,
) -> None:
    """Exibe o banner de inicialização de sessão (Roadmap V15.6 / Spec G10).

    Não bloqueia: apenas informa o pesquisador do estado atual antes de iniciar.

    Args:
        mode: Modo de operação ativo da sessão (SessionMode).
        context_dir: Diretório de contexto de entrada a inspecionar.
        budget: Orçamento de uso efetivo da sessão (Roadmap V18 / Spec
            `usage-limits`). Se omitido, usa os defaults de `src/config.py`
            apenas para exibição (não altera o orçamento real da sessão).
        llm_routing: Mapa resolvido de modelos por papel (ADR 017). Quando informado, o
            banner traz uma linha por papel (``<papel>  <provedor/modelo>  (<trust>)``), a
            política, o modo de roteamento e a versão/hash do catálogo — nunca segredos.
    """
    mode_label = {
        SessionMode.ASSISTED.value: "assistido",
        SessionMode.SEMI.value: "semi-autônomo",
        SessionMode.AUTO.value: "autônomo",
    }.get(mode, mode)

    context_path = Path(context_dir)
    file_count = 0
    file_names: list[str] = []
    if context_path.is_dir():
        file_names = sorted(p.name for p in context_path.iterdir() if p.is_file())
        file_count = len(file_names)

    if file_count == 0:
        context_desc = f"{YELLOW}⚠ Nenhum contexto detectado{RESET}"
    elif file_count <= 3:
        context_desc = f"{file_count} arquivo(s): {', '.join(file_names)}"
    else:
        context_desc = f"{file_count} arquivos"

    print(
        f"\n{DIM}┌──────────────────────────────────────────────────────────────┐{RESET}\n"
        f"{DIM}│{RESET}  {APP_NAME}  │  Modo: {BOLD}{mode_label}{RESET}  │  Contexto: {context_desc}\n"
        f"{DIM}│{RESET}  Pressione Ctrl+C para suspender │  -h para ajuda\n"
        f"{DIM}└──────────────────────────────────────────────────────────────┘{RESET}"
    )

    # Roadmap V18 / Spec usage-limits — orçamento efetivo exibido no início da sessão.
    effective_budget = budget or UsageBudget.from_config()
    print(
        f"  {DIM}Orçamento: {RESET}{effective_budget.max_tokens:,} tokens "
        f"({effective_budget.closing_reserve_pct*100:.0f}% reservados p/ fechamento) │ "
        f"{effective_budget.max_minutes:.0f}min │ "
        f"{effective_budget.max_task_retries} retentativas/tarefa │ "
        f"{effective_budget.max_connection_retries} retentativas de conexão"
    )

    if llm_routing is not None:
        header, *role_lines = llm_routing.banner_lines()
        print(f"  {DIM}{header}{RESET}")
        for line in role_lines:
            print(f"    {line}")

    if mode == SessionMode.AUTO.value:
        print(f"  {YELLOW}⚠ Modo autônomo ativo — sem consulta ao pesquisador{RESET}")
    print()


def show_sessions(docker_client: Any | None = None) -> list[dict[str, Any]]:
    """Lista os containers de sandbox de código ativos do GeminiClaw (Roadmap V14.6).

    Os agentes rodam no processo do orquestrador (ADR 014); o único container é o sandbox.

    Args:
        docker_client: Cliente Docker opcional (para injeção em testes).

    Returns:
        Lista com metadados dos containers ativos encontrados.
    """
    if docker_client is None:
        try:
            import docker
            docker_client = docker.from_env()
        except Exception as e:
            print(f"\n  {RED}❌ Erro ao conectar ao Docker: {e}{RESET}\n")
            return []

    try:
        containers = docker_client.containers.list(
            filters={"label": "project=geminiclaw"}
        )
    except Exception as e:
        print(f"\n  {RED}❌ Erro ao listar containers: {e}{RESET}\n")
        return []

    _sep = "─" * 80
    print(f"\n{BOLD}  📦 Sandboxes de Código Ativos do {APP_NAME}{RESET}")
    print(f"{BOLD}{_sep}{RESET}")

    if not containers:
        print(f"  {DIM}Nenhum sandbox de código ativo encontrado.{RESET}")
        print(f"{BOLD}{_sep}{RESET}\n")
        return []

    header = (
        f"  {BOLD}{'SESSION ID':<24} {'CONTAINER ID':<14} {'TASK':<12} "
        f"{'MODE':<10} {'IMAGE':<24} {'STATUS'}{RESET}"
    )
    print(header)
    print(f"  {DIM}{'─' * 88}{RESET}")

    active_info = []
    for c in containers:
        labels = getattr(c, "labels", {}) or {}
        session_id = labels.get("session_id", "unknown")
        agent_id = labels.get("task_name") or labels.get("agent_id", "unknown")
        session_mode = labels.get("session_mode", "—")
        cid = getattr(c, "short_id", getattr(c, "id", "unknown")[:12])

        image_name = "unknown"
        if hasattr(c, "image"):
            if hasattr(c.image, "tags") and c.image.tags:
                image_name = c.image.tags[0]
            else:
                image_name = str(c.image)

        status = getattr(c, "status", "unknown")
        status_color = GREEN if status == "running" else YELLOW

        print(f"  {CYAN}{session_id:<24}{RESET} {DIM}{cid:<14}{RESET} {agent_id:<12} {session_mode:<10} {image_name:<24} [{status_color}{status}{RESET}]")
        active_info.append({
            "session_id": session_id,
            "container_id": cid,
            "agent_id": agent_id,
            "mode": session_mode,
            "image": image_name,
            "status": status,
        })

    print(f"{BOLD}{_sep}{RESET}\n")
    return active_info


def stop_sessions(
    session_id: str | None = None,
    docker_client: Any | None = None,
) -> int:
    """Encerra os containers de sandbox de código ativos (Roadmap V14.6).

    Args:
        session_id: ID da sessão a encerrar, ou None para encerrar todas as sessões.
        docker_client: Cliente Docker opcional (para injeção em testes).

    Returns:
        Número de containers encerrados.
    """
    if docker_client is None:
        try:
            import docker
            docker_client = docker.from_env()
        except Exception as e:
            print(f"\n  {RED}❌ Erro ao conectar ao Docker: {e}{RESET}\n")
            return 0

    try:
        containers = docker_client.containers.list(
            filters={"label": "project=geminiclaw"}
        )
    except Exception as e:
        print(f"\n  {RED}❌ Erro ao listar containers para encerramento: {e}{RESET}\n")
        return 0

    if session_id:
        targets = [c for c in containers if (getattr(c, "labels", {}) or {}).get("session_id") == session_id]
    else:
        targets = containers

    if not targets:
        if session_id:
            print(f"\n  {DIM}Nenhum container ativo encontrado para a sessão: {session_id}{RESET}\n")
        else:
            print(f"\n  {DIM}Nenhum container ativo do {APP_NAME} encontrado.{RESET}\n")
        return 0

    stopped_count = 0
    print(f"\n  {YELLOW}🛑 Encerrando {len(targets)} container(s)...{RESET}")
    for c in targets:
        cid = getattr(c, "short_id", getattr(c, "id", "unknown")[:12])
        labels = getattr(c, "labels", {}) or {}
        s_id = labels.get("session_id", "unknown")
        try:
            c.stop(timeout=10)
            stopped_count += 1
            print(f"    {GREEN}✔{RESET} Container {BOLD}{cid}{RESET} (sessão: {DIM}{s_id}{RESET}) encerrado.")
        except Exception as e:
            print(f"    {RED}✘{RESET} Erro ao parar container {cid}: {e}")

    print(f"  {GREEN}✅ {stopped_count} container(s) encerrado(s) com sucesso.{RESET}\n")
    return stopped_count



def _create_orchestrator() -> Orchestrator:
    """Verifica a infraestrutura de apoio e retorna o orquestrador.

    Returns:
        O ``Orchestrator``, que executa os agentes no próprio processo.
    """
    ensure_infrastructure()
    return Orchestrator(session_manager=SessionManager())


async def execute_prompt(
    orchestrator: Orchestrator,
    prompt: str,
    mode: str | None = None,
    context_bundle: ContextBundle | None = None,
    budget: UsageBudget | None = None,
    llm_routing: "SessionRouting | None" = None,
    project_binder: "ProjectBinder | None" = None,
) -> bool:
    """Executa um prompt no orquestrador e exibe o resultado.

    Args:
        orchestrator: Instância do orquestrador.
        prompt: Prompt do usuário.
        mode: Nível de autonomia da sessão (SessionMode). Se omitido, usa o padrão.
        context_bundle: Contexto pré-carregado de `input_context/` (Spec G9).
        budget: Orçamento de uso da sessão (Roadmap V18 / Spec `usage-limits`).
            Se omitido, usa os defaults de `src/config.py`.
        llm_routing: Mapa resolvido de modelos por papel (ADR 017); se omitido, o
            orquestrador o resolve antes de qualquer chamada de LLM.
        project_binder: Resolve o projeto da sessão e garante o Problema confirmado pelo
            pesquisador antes de qualquer planejamento (v17-research-project).

    Returns:
        False se a sessão foi recusada antes de começar (projeto/problema); True caso contrário.
    """
    project_kwargs: dict[str, Any] = {}
    if project_binder is not None:
        from src.llm.session import bind_session_routing
        from src.project_session import ProjectFlowError

        try:
            if llm_routing is not None:
                bind_session_routing(llm_routing)  # o rascunho do Problema usa o modelo do papel researcher
            binding = await project_binder.bind(prompt, context_bundle)
        except ProjectFlowError as e:
            print(f"\n  {STATUS_ICONS['error']} {RED}{e}{RESET}\n")
            return False
        if binding.mode == "sem_grafo":
            print(f"\n  {YELLOW}SEM GRAFO: projeto e Problema não aplicados nesta sessão.{RESET}")
            project_kwargs = {"project_mode": "sem_grafo"}
        else:
            project_kwargs = {"project_id": binding.project_id, "project_context": binding.context_block}

    print(f"\n  {STATUS_ICONS['running']} {DIM}Processando...{RESET}\n")

    try:
        result = await orchestrator.handle_request(
            prompt, mode=mode, context_bundle=context_bundle, budget=budget, llm_routing=llm_routing,
            **project_kwargs,
        )
        print(format_result(result))
        if context_bundle and result.session_id:
            print_context_lifecycle_message(result.session_id, context_bundle)
    except Exception as e:
        logger.error("Erro ao processar prompt", extra={"error": str(e)})
        print(f"\n  {STATUS_ICONS['error']} {RED}Erro: {e}{RESET}\n")
    return True


async def interactive_mode(
    orchestrator: Orchestrator,
    mode: str | None = None,
    context_bundle: ContextBundle | None = None,
    budget: UsageBudget | None = None,
    llm_routing: "SessionRouting | None" = None,
    project_binder: "ProjectBinder | None" = None,
) -> None:
    """Executa a CLI em modo interativo (REPL).

    Args:
        orchestrator: Instância do orquestrador.
        mode: Nível de autonomia da sessão (SessionMode). Se omitido, usa o padrão.
        context_bundle: Contexto pré-carregado de `input_context/` (Spec G9), reutilizado
            em todas as interações do REPL.
        budget: Orçamento de uso da sessão (Roadmap V18 / Spec `usage-limits`),
            reutilizado em todas as interações do REPL. Se omitido, usa os
            defaults de `src/config.py`.
        llm_routing: Mapa resolvido de modelos por papel (ADR 017), resolvido uma vez para
            todo o REPL.
        project_binder: Vínculo de projeto, resolvido no primeiro prompt e reutilizado.
    """
    print(BANNER)
    print(f"  {DIM}Modo interativo. Digite 'sair' para encerrar.{RESET}\n")
    print_session_banner(mode or SESSION_DEFAULT_MODE, budget=budget, llm_routing=llm_routing)

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

        if prompt.lower() == "sessions":
            show_sessions()
            continue

        if prompt.lower() == "stop" or prompt.lower().startswith("stop "):
            parts = prompt.split()
            s_id = parts[1] if len(parts) > 1 else None
            stop_sessions(session_id=s_id)
            continue

        if prompt.lower() == "clear-context":
            clear_context()
            continue

        if prompt.lower() == "resume" or prompt.lower().startswith("resume "):
            parts = prompt.split()
            s_id = parts[1] if len(parts) > 1 else None
            if not s_id:
                print(f"\n  {RED}❌ Use: resume <session_id>{RESET}\n")
            else:
                await resume_session(orchestrator, s_id)
            continue

        await execute_prompt(
            orchestrator, prompt, mode=mode, context_bundle=context_bundle, budget=budget,
            llm_routing=llm_routing, project_binder=project_binder,
        )


def _handle_embeddings_command(argv: list[str]) -> None:
    """Trata `geminiclaw embeddings <ação> [opções]` (Roadmap V16 / ADR 011 §3).

    Tratado separadamente do parser principal (que só aceita um único
    argumento posicional de prompt) para suportar a sintaxe de subcomando
    `geminiclaw embeddings reindex --collection <nome> --yes` sem exigir que
    o usuário cite (quote) as duas palavras juntas.

    Args:
        argv: Argumentos após "embeddings" (ex.: ``["reindex", "--yes"]``).
    """
    sub_parser = argparse.ArgumentParser(
        prog="geminiclaw embeddings",
        description="Comandos de gestão de embeddings locais.",
    )
    sub_parsers = sub_parser.add_subparsers(dest="action", required=True)
    reindex_parser = sub_parsers.add_parser(
        "reindex",
        help="Revetoriza coleções do Qdrant com o modelo de embeddings atual.",
    )
    reindex_parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Coleção a reindexar (padrão: todas as coleções reindexáveis).",
    )
    reindex_parser.add_argument(
        "--yes",
        action="store_true",
        help="Pula a confirmação interativa.",
    )
    try:
        sub_args = sub_parser.parse_args(argv)
    except SystemExit as e:
        sys.exit(e.code)

    if sub_args.action == "reindex":
        run_embeddings_reindex(collection=sub_args.collection, auto_confirm=sub_args.yes)


def _handle_vocab_command(argv: list[str], store: Any | None = None) -> int:
    """Trata `geminiclaw vocab pending|approve|reject|map` (v17-controlled-vocabulary).

    Operações tipadas e determinísticas do grafo, com autor ``pesquisador`` e sem LLM.

    Args:
        argv: Argumentos após "vocab".
        store: ``GraphStore`` a usar (padrão: o grafo de produção); injetável em testes.

    Returns:
        Código de saída (0 em sucesso).
    """
    from src.knowledge import vocabulary

    parser = argparse.ArgumentParser(
        prog="geminiclaw vocab",
        description="Decisões do pesquisador sobre candidatos do vocabulário controlado.",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("pending", help="Lista candidatos e sinônimos candidatos.")
    sub.add_parser("approve", help="Aprova um candidato.").add_argument("id")
    reject_p = sub.add_parser("reject", help="Rejeita um candidato (sem apagar).")
    reject_p.add_argument("id")
    reject_p.add_argument("--motivo", default=None, help="Motivo da rejeição.")
    map_p = sub.add_parser("map", help="Funde um candidato em um termo canônico.")
    map_p.add_argument("id")
    map_p.add_argument("--para", required=True, help="ID do termo canônico.")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    try:
        if store is None:
            from src.knowledge.factory import open_graph_store

            store = open_graph_store()
        if args.action == "pending":
            items = vocabulary.list_pending(store)
            if not items:
                print("Nenhum candidato pendente.")
            for item in items:
                extra = f" sinônimos candidatos: {item['sinonimos_candidatos']}" if item["tipo"] == "sinonimo" else ""
                print(f"{item['id']}  {item['label']}  {item['tipo']}  {item['termo']}{extra}")
        elif args.action == "approve":
            from src.human_gate import authorize_from_cli

            if not authorize_from_cli("aprovar_termo_vocabulario", args.id):
                print("Aprovação não autorizada pelo gate (exige a ação do pesquisador na CLI).")
                return 1
            vocabulary.approve_term(store, args.id)
            print(f"Aprovado: {args.id}")
        elif args.action == "reject":
            vocabulary.reject_term(store, args.id, args.motivo)
            print(f"Rejeitado: {args.id}")
        elif args.action == "map":
            vocabulary.map_term(store, args.id, args.para)
            print(f"Mapeado: {args.id} -> {args.para}")
    except (vocabulary.VocabularyError, RuntimeError) as e:
        print(f"\n  {RED}❌ {e}{RESET}\n")
        return 1
    return 0


def main() -> None:
    """Ponto de entrada principal da CLI."""
    # Roadmap V15.6 / Spec G10 — help completo customizado, sem passar pelo argparse padrão
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print_full_help()
        sys.exit(0)

    # Roadmap V16 — 'geminiclaw embeddings <ação>' é um subcomando de verdade
    # (múltiplas palavras sem aspas), tratado antes do parser genérico de
    # prompt (que só aceita um único argumento posicional).
    if len(sys.argv) >= 2 and sys.argv[1] == "embeddings":
        _handle_embeddings_command(sys.argv[2:])
        sys.exit(0)

    if len(sys.argv) >= 2 and sys.argv[1] == "project":
        from src.cli_project import handle_project_command

        sys.exit(handle_project_command(sys.argv[2:]))

    if len(sys.argv) >= 2 and sys.argv[1] == "vocab":
        sys.exit(_handle_vocab_command(sys.argv[2:]))

    # Roadmap V17 — 'geminiclaw knowledge stats|reindex' (índice semântico do grafo).
    if len(sys.argv) >= 2 and sys.argv[1] == "knowledge":
        from src.db import get_pool
        from src.knowledge.semantic_runtime import run_knowledge_command

        pool = get_pool()
        pool.open()
        try:
            code = run_knowledge_command(sys.argv[2:])
        finally:
            pool.close()
        sys.exit(code)

    parser = build_parser()
    args = parser.parse_args()
    mode = args.mode or SESSION_DEFAULT_MODE
    # Roadmap V18 / Spec usage-limits — orçamento efetivo da sessão (config + overrides de CLI).
    try:
        budget = build_usage_budget(args)
    except ValueError as e:
        print(f"\n  {STATUS_ICONS['error']} {RED}Orçamento de uso inválido: {e}{RESET}\n")
        logger.error("Orçamento de uso inválido", extra={"error": str(e)})
        sys.exit(1)

    orchestrator: Orchestrator | None = None

    def _signal_handler(sig: int, frame: object) -> None:
        """Handler para SIGINT (Ctrl+C)."""
        print(f"\n\n  {YELLOW}⚠  Interrupção recebida. Encerrando sandboxes de código...{RESET}")
        # Os agentes rodam no processo; só o sandbox de código pode ter deixado container para trás.
        from src.skills.code.sandbox import cleanup_sandbox_containers

        removed = cleanup_sandbox_containers()
        print(f"  {GREEN}✅ Cleanup concluído ({removed} sandbox(es) removido(s)).{RESET}\n")
        # V11.1.2 — Flush de telemetria antes de encerrar via SIGINT
        try:
            from src.telemetry import get_telemetry
            import asyncio as _asyncio
            _tel = get_telemetry()
            _asyncio.run(_tel.flush())
            logger.info("Flush de telemetria concluído (SIGINT).")
        except Exception as _e:
            logger.error("Erro no flush de telemetria (SIGINT)", extra={"error": str(_e)})
        sys.exit(130)

    signal.signal(signal.SIGINT, _signal_handler)

    if args.prompt:
        p_lower = args.prompt.strip().lower()
        if p_lower == "history":
            show_history()
            sys.exit(0)
        elif p_lower == "sessions":
            show_sessions()
            sys.exit(0)
        elif p_lower == "stop" or p_lower.startswith("stop "):
            target_sess = args.session
            if not target_sess and " " in args.prompt.strip():
                target_sess = args.prompt.strip().split(maxsplit=1)[1]
            stop_sessions(session_id=target_sess)
            sys.exit(0)
        elif p_lower == "clear-context":
            clear_context()
            sys.exit(0)
        elif p_lower == "convert":
            if not args.session or not args.format:
                print(f"\n  {RED}❌ Use: geminiclaw convert --session <id> --format latex|html|docx{RESET}\n")
                sys.exit(1)
            convert_report(args.session, args.format)
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
        orchestrator = _create_orchestrator()
    except RuntimeError as e:
        print(f"\n  {STATUS_ICONS['error']} {RED}Falha na inicialização: {e}{RESET}\n")
        logger.error("Falha ao inicializar CLI", extra={"error": str(e)})
        sys.exit(1)

    # Roadmap V15.3 / Spec G5 — retomar sessão suspensa
    if args.prompt:
        p_lower_resume = args.prompt.strip().lower()
        if p_lower_resume == "resume" or p_lower_resume.startswith("resume "):
            target_sess = args.session
            if not target_sess and " " in args.prompt.strip():
                target_sess = args.prompt.strip().split(maxsplit=1)[1]
            if not target_sess:
                print(f"\n  {RED}❌ Especifique --session <id> (ex: geminiclaw resume --session <id>).{RESET}\n")
                sys.exit(1)
            asyncio.run(resume_session(orchestrator, target_sess))
            sys.exit(0)

    # Roadmap V15.5 / Spec G9 — carrega input_context/ uma única vez por invocação
    context_bundle = load_context_with_confirmation()
    if context_bundle is None:
        sys.exit(1)

    # ADR 017 — resolve o modelo de cada papel uma única vez, antes do banner e de qualquer chamada
    # de LLM; sem modelo elegível, a sessão não começa (mensagem acionável).
    from src.llm.catalog import CatalogError
    from src.llm.routing import RoutingError
    from src.llm.session import build_session_routing

    try:
        llm_routing = asyncio.run(
            build_session_routing(cli_pins={"researcher": args.model} if args.model else None)
        )
    except (RoutingError, CatalogError) as e:
        print(f"\n  {STATUS_ICONS['error']} {RED}Falha na resolução de modelos: {e}{RESET}\n")
        logger.error("Falha ao resolver modelos por papel", extra={"error": str(e)})
        sys.exit(1)

    # v17-research-project — projeto da sessão e Problema confirmado (todos os modos).
    from src.project_session import ProjectBinder

    def _open_store() -> Any:
        from src.knowledge.factory import open_graph_store

        # Início da sessão: reconcilia o índice semântico antes da primeira consulta ao grafo (projeto e Problema).
        return open_graph_store(reconcile=True)

    try:
        researcher_model: str | None = llm_routing.resolution("researcher").id
    except Exception:  # noqa: BLE001 - sem modelo conhecido, a autoria do rascunho fica só com o papel
        researcher_model = None
    project_binder = ProjectBinder(_open_store, project_arg=args.project, researcher_model=researcher_model)

    if args.prompt:
        # Modo direto: executa o prompt e sai
        print_session_banner(mode, budget=budget, llm_routing=llm_routing)
        accepted = asyncio.run(
            execute_prompt(
                orchestrator,
                args.prompt,
                mode=mode,
                context_bundle=context_bundle,
                budget=budget,
                llm_routing=llm_routing,
                project_binder=project_binder,
            )
        )
        if accepted is False:
            sys.exit(1)
        # V11.1.2 — Flush explícito ao encerrar modo não-interativo
        try:
            from src.telemetry import get_telemetry
            asyncio.run(get_telemetry().flush())
        except Exception as _e:
            logger.error("Erro no flush de telemetria final", extra={"error": str(_e)})
    else:
        # Modo interativo (REPL)
        asyncio.run(
            interactive_mode(
                orchestrator, mode=mode, context_bundle=context_bundle, budget=budget,
                llm_routing=llm_routing, project_binder=project_binder,
            )
        )
        # V11.1.2 — Flush explícito ao sair do modo interativo
        try:
            from src.telemetry import get_telemetry
            asyncio.run(get_telemetry().flush())
        except Exception as _e:
            logger.error("Erro no flush de telemetria final (REPL)", extra={"error": str(_e)})


if __name__ == "__main__":
    main()
