"""Relatórios do terminal: resultado, histórico, métricas e logs de sessão.

Movido de ``src/cli/main.py`` sem alterar o comportamento (v18.7-background-sessions, tarefa 0.9; ADR 024 §5).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from src.logger import get_logger
from src.orchestration.orchestrator import AgentResult, OrchestratorResult
from src.session.manager import SessionManager
from src.utils.terminal import BOLD, CYAN, DIM, GREEN, MAGENTA, RED, RESET, STATUS_ICONS, YELLOW

logger = get_logger(__name__)


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
    from datetime import datetime

    from src.session.history import ExecutionHistory
    
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
        
        print(
            f"  {DIM}{r.id[:8]}{RESET} | {date_str} | [{status_color}{r.status.upper()}{RESET}] | "
            f"⏱  {dur} | {prompt_trunc}"
        )
        
    _sep = "─" * 80
    print(f"{BOLD}{_sep}{RESET}\n")


def quota_stop_message(execution_id: str, quota: dict | None) -> str:
    """Mensagem acionável da parada por cota ou teto de gasto esgotado (v18.7-benchmark-fixes).

    Args:
        execution_id: Sessão fechada.
        quota: ``checkpoint["cota_provedor"]`` (``provedor``, ``modelo``, ``status``), se registrado.
    """
    who = f"{quota['provedor']}, modelo {quota['modelo']}" if quota else "provedor não identificado"
    return (
        f"Sessão fechada por limite_cota_provedor: cota ou teto de gasto esgotado no provedor ({who}). "
        f"Aumente o teto ou troque o provedor e retome com: geminiclaw resume --session {execution_id}"
    )


def _show_operation_metrics(execution_id: str) -> None:
    """Mostra as métricas de operação da sessão (v18.5-operation-metrics §6.5).

    Usa as gravadas no fechamento; se a sessão não fechou normalmente (queda, interrupção) ou não as tem, recalcula
    a partir dos produtores e grava com ``parcial=true``.
    """
    from src.report.operation_metrics import (
        aggregate_operation_metrics,
        default_readers,
        render_operation_metrics_section,
        unlimited_block,
    )

    try:
        manager = SessionManager()
        session = manager.get(execution_id)
    except Exception as exc:  # noqa: BLE001 - bloco opcional da tela
        print(f"\n  {YELLOW}Métricas de operação indisponíveis: banco inacessível ({type(exc).__name__}).{RESET}")
        return
    if session is None:
        print(f"\n  {DIM}Métricas de operação: sessão '{execution_id}' não encontrada.{RESET}")
        return
    payload = dict(session.payload)
    metrics = payload.get("operation_metrics")
    if not metrics or metrics.get("parcial") or session.status not in ("closed", "completed"):
        metrics = aggregate_operation_metrics(
            execution_id,
            parcial=session.status not in ("closed", "completed"),
            readers=default_readers(payload_loader=lambda sid: payload),
            unlimited=unlimited_block(payload.get("budget"), 0),
        )
        try:
            manager.update(execution_id, payload={**payload, "operation_metrics": metrics})
        except Exception as exc:  # noqa: BLE001 - recalculado só para exibição
            logger.warning("Métricas de operação recalculadas não gravadas", extra={"error": type(exc).__name__})
    print(f"\n  {BOLD}{CYAN}Métricas de Operação{RESET}")
    for line in render_operation_metrics_section(metrics, stop_reason=payload.get("motivo_parada")).splitlines():
        if not line.startswith("<!--"):
            print(f"    {line}")
    if payload.get("motivo_parada") == "limite_cota_provedor":
        quota = (payload.get("checkpoint") or {}).get("cota_provedor")
        print(f"\n  {YELLOW}{quota_stop_message(execution_id, quota)}{RESET}")


def show_metrics(execution_id: str) -> None:
    """Exibe métricas de telemetria de uma execução.

    Args:
        execution_id: ID da execução a consultar.
    """
    from src.observability.telemetry import get_telemetry

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

    _show_operation_metrics(execution_id)

    _sep2 = "─" * 80
    print(f"\n{DIM}{_sep2}{RESET}")
    print(f"  {DIM}Use --export {execution_id} para exportar em CSV.{RESET}\n")


def show_session_logs(session_id: str) -> None:
    """Agrega e exibe os logs de todos os agentes de uma sessão em ordem cronológica.

    Args:
        session_id: ID (slug) da sessão.
    """
    import json

    from src.artifacts.output_manager import OutputManager
    
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
        if level == "ERROR":
            color = RED
        elif level == "WARNING":
            color = YELLOW
        elif level == "INFO":
            color = GREEN
        
        agent_color = CYAN if agent == "orchestrator" else MAGENTA
        
        print(f"  {DIM}{ts}{RESET} | {agent_color}{agent:<12}{RESET} | {color}{level:<7}{RESET} | {msg}")

    print(f"{BOLD}{'─' * 100}{RESET}\n")
