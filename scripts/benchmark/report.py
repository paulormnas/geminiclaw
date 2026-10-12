"""Gera a tabela markdown do relatório a partir de ``results.json``."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _fmt(stats: dict | None, key: str = "max", suffix: str = "") -> str:
    return "-" if not stats else f"{stats[key]}{suffix}"


def _cost(tokens: dict) -> str:
    if not tokens:
        return "-"
    note = " (+n/d)" if tokens.get("unpriced_models") else ""
    return f"{tokens.get('cost_usd', 0):.4f}{note}"


def render(results: list[dict]) -> str:
    header = ("| Combinação | Status | Tempo (s) | Tokens in | Tokens out | Subtarefas ok | Checklist | Acurácia | "
              "CPU sis. máx (%) | RAM máx (MB) | Temp máx (°C) | Throttling | Custo (USD) | Retentativas |\n"
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    rows = [header]
    for r in results:
        if r["status"] == "skipped":
            rows.append(f"| {r['name']} | pulada ({r.get('reason', '')}) |" + " - |" * 12)
            continue
        res, tok = r["resources"], r.get("tokens", {})
        out, score = r.get("outcome", {}), r.get("score", {})
        acc = score.get("accuracy")
        rows.append(
            f"| {r['name']} | {r['status']} | {r['wall_seconds']} | {tok.get('prompt_tokens', '-')} | "
            f"{tok.get('completion_tokens', '-')} | {out.get('subtasks_ok', '-')}/{out.get('subtasks', '-')} | "
            f"{score.get('score', '-')}/{score.get('max_score', '-')} | {'-' if acc is None else f'{acc:.3f}'} | "
            f"{_fmt(res['sys_cpu_pct'])} | {_fmt(res['mem_used_mb'])} | {_fmt(res['temp_c'])} | "
            f"{', '.join(res['throttled']) or 'não'} | {_cost(tok)} | "
            f"{r.get('db', {}).get('connection_retries', '-')} |"
        )
    return "\n".join(rows)


def render_interactions(results: list[dict]) -> str:
    """Tokens por agente, mensagens, vereditos de validação/revisão e perguntas ao pesquisador."""
    blocks = []
    for r in results:
        data = r.get("db", {}).get("interactions") or {}
        if r.get("status") == "skipped" or not data or "error" in data:
            continue
        agents = ", ".join(f"{a['agent']} {a['share_pct']}% ({a['calls']} chamadas)" for a in data["tokens_by_agent"])
        plans, reviews = data["plan_validations"], data["subtask_reviews"]
        lines = [
            f"### {r['name']}",
            f"- Tokens por agente: {agents or '-'}",
            f"- Mensagens entre agentes: {data['messages']} (eventos: {data['event_counts']})",
            f"- Validação de plano: {plans['approved']}/{plans['total']} aprovadas",
            f"- Revisão de subtarefa: {reviews['approved']}/{reviews['total']} aprovadas",
        ]
        for issues in (plans["rejections"] + reviews["rejections"])[:4]:
            lines.append(f"  - reprovação: {'; '.join(str(i) for i in issues)[:240]}")
        for q in data["ask_researcher"][:4]:
            lines.append(f"- Pergunta ao pesquisador: {str(q['question'])[:200]} (motivo: {str(q['why'])[:120]})")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_knowledge(results: list[dict]) -> str:
    """Memória de conhecimento por combinação: vetores (Qdrant), grafo do projeto e linhas gravadas no Postgres."""
    header = (
        "| Combinação | Vetores novos (Qdrant) | Nós do projeto | Arestas do projeto | Nós por rótulo | "
        "Execuções registradas | Registros de egresso | Auditoria do grafo |\n|---|---|---|---|---|---|---|---|"
    )
    rows = [header]
    for r in results:
        if r.get("status") == "skipped" or "footprint_delta" not in r:
            continue
        delta, graph = r["footprint_delta"], r.get("project_graph") or {}
        tables = delta.get("tabelas", {})
        vectors = delta.get("qdrant", {})
        detail = ", ".join(f"{k}: {v:+d}" for k, v in vectors.items())
        vectors_cell = f"{sum(vectors.values())} ({detail})" if vectors else "0"
        labels = ", ".join(f"{k} {v}" for k, v in (graph.get("nos_por_rotulo") or {}).items()) or "-"
        rows.append(
            f"| {r['name']} | {vectors_cell} | {graph.get('total_nos', '-')} | {graph.get('total_arestas', '-')} | "
            f"{labels} | {tables.get('execution_records', 0)} | {tables.get('egress_log', 0)} | "
            f"{tables.get('knowledge_audit', 0)} |"
        )
    return "\n".join(rows)


def render_operation(results: list[dict]) -> str:
    """Métricas de operação (v18.5-operation-metrics) por combinação: egresso, proveniência, verificação e custo."""
    header = (
        "| Combinação | Egresso (bytes) | Chamadas de busca | Cadeia de execuções | Números res/calc/src | "
        "Não verificados | Afirmações (suportada/total) | Planos reprovados | Custo (USD) | CPU média (%) |\n"
        "|---|---|---|---|---|---|---|---|---|---|"
    )
    rows = [header]
    for r in results:
        metrics = r.get("operation_metrics")
        if r.get("status") == "skipped" or not metrics:
            continue

        def get(group: str, key: str, default: str = "-") -> object:
            values = metrics.get(group) or {}
            return default if values.get("estado") != "disponivel" or key not in values else values[key]

        origins = get("proveniencia", "numeros_por_origem", None)
        claims = get("verificacao", "afirmacoes_por_status", None)
        chain = get("proveniencia", "cadeia", None)
        node = (metrics.get("custo_recursos") or {}).get("no") or {}
        claims_cell = f"{claims.get('suportada', 0)}/{sum(claims.values())}" if claims else "-"
        rows.append(
            f"| {r['name']} | {get('egresso', 'bytes_total')} | {get('egresso', 'consultas_busca')} | "
            f"{(chain or {}).get('resultado', '-')} | "
            f"{'/'.join(str(origins[k]) for k in ('res', 'calc', 'src')) if origins else '-'} | "
            f"{get('proveniencia', 'numeros_nao_verificados')} | "
            f"{claims_cell} | "
            f"{get('verificacao', 'ciclos_rejeicao_plano')} | {get('custo_recursos', 'custo_usd_total')} | "
            f"{node.get('cpu_pct_medio', '-')} |"
        )
    return "\n".join(rows)


def _pct(value: float | None) -> str:
    return "n/d" if value is None else f"{value * 100:.0f}%"


def render_communication(results: list[dict]) -> str:
    """Tabela de comunicação por combinação: revisor contra a verdade, resolução, laços e juiz."""
    header = (
        "| Combinação | Revisões | Falso reprovado | Falso aprovado | Indeterminadas | Resolução (c/ cauda) | "
        "Maior laço (Validator/revisor) | Planos reparados | Juiz (selo) |\n"
        "|---|---|---|---|---|---|---|---|---|"
    )
    rows = [header]
    for r in results:
        ev = r.get("comm_eval")
        if not ev or "error" in ev:
            continue
        conf = ev["reviewer"]["confusion"]
        res, loops = ev["resolution"], ev["resolution"]["loops"]
        repairs = ev["planner_repairs"]
        judge = ev.get("ask_researcher")
        if judge is None:
            judge_cell = "-"
        elif "error" in judge:
            judge_cell = f"erro: {judge['error'][:60]}"
        else:
            judge_cell = f"{judge.get('mean_scores', {})} ({judge.get('scores_label', 'não calibrado')})"
        kappa = (judge or {}).get("calibration", {}).get("kappa")
        if kappa:
            judge_cell += f" kappa={kappa}"
        rows.append(
            f"| {r['name']} | {ev['reviewer']['reviews']} | {_pct(conf['false_reject_rate'])} | "
            f"{_pct(conf['false_accept_rate'])} | {_pct(conf['indeterminate_share'])} | "
            f"{_pct(res['subtask']['resolution_rate_with_tail'])} | "
            f"{loops['validator']['max_length']}/{loops['reviewer']['max_length']} | "
            f"{repairs['with_repair']}/{repairs['plans']} | {judge_cell} |"
        )
    return "\n".join(rows)


if __name__ == "__main__":
    loaded = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(render(loaded))
    print()
    print(render_interactions(loaded))
    if any(r.get("footprint_delta") for r in loaded):
        print()
        print(render_knowledge(loaded))
    if any(r.get("operation_metrics") for r in loaded):
        print()
        print(render_operation(loaded))
    if any(r.get("comm_eval") for r in loaded):
        print()
        print(render_communication(loaded))
