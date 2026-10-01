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


if __name__ == "__main__":
    loaded = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(render(loaded))
    print()
    print(render_interactions(loaded))
