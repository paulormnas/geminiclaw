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


if __name__ == "__main__":
    print(render(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))))
