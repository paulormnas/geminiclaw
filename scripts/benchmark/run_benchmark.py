"""Executa uma matriz de combinações de modelos contra a tarefa do ``run.sh`` e mede tudo.

Uso (no Raspberry Pi, na raiz do repositório)::

    uv run python -m scripts.benchmark.run_benchmark scripts/benchmark/matrix_baixo_custo.json \
        --results ~/bench/results.json [--only NOME ...]

Cada combinação vira um subprocesso ``main.py --mode auto`` com as variáveis de papel
sobrescritas. Mede tempo de parede, tokens (de ``session_metadata.json``), checklist de acurácia
e picos de CPU/memória/temperatura via :class:`ResourceSampler`. Combinações cuja chave de API
(campo ``requires``) não está no ambiente são registradas como ``skipped``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

from scripts.benchmark.resources import ResourceSampler
from scripts.benchmark.scoring import score_session, session_outcome

ROLES = ("RESEARCHER", "VALIDATOR", "DEVELOPER", "BASE", "SUMMARIZER", "REVIEWER")


def build_env(base: dict[str, str], roles: dict[str, str], extra: dict[str, str] | None = None) -> dict[str, str]:
    """Aplica ``{"*": "prov/modelo", "DEVELOPER": ...}`` como pins ``{PAPEL}_MODEL=provedor/modelo``.

    O benchmark mede combinações explícitas de modelos pagos, então o ambiente da combinação usa
    ``LLM_DATA_POLICY=third_party_allowed`` (ADR 017). O modo de roteamento é ``flexible`` para
    preservar o fallback do Google no 429 (``GOOGLE_FALLBACK_MODEL`` da matriz), que o modo
    ``strict`` desligaria; o modelo realmente usado continua nos totais por provedor/modelo da
    telemetria e o mapa resolvido, no payload da sessão. As variáveis
    removidas (``LLM_PROVIDER``, ``LLM_MODEL``, ``DEFAULT_MODEL``, ``{PAPEL}_PROVIDER``) são
    retiradas do ambiente herdado. ``extra`` (ex.: ``ANTHROPIC_EFFORT``, teto de custo da
    combinação) é aplicado por último.
    """
    env = dict(base)
    for name in ("LLM_PROVIDER", "LLM_MODEL", "DEFAULT_MODEL", "AGENT_MODEL"):
        env.pop(name, None)
    for role in ROLES:
        env.pop(f"{role}_PROVIDER", None)
    default = roles.get("*")
    assignments = {role: roles.get(role, default) for role in ROLES}
    for role, spec in assignments.items():
        if spec is None:
            env.pop(f"{role}_MODEL", None)
            continue
        if "/" not in spec:
            raise ValueError(f"Combinação com '{role}': '{spec}' sem provedor; use provedor/modelo.")
        env[f"{role}_MODEL"] = spec
    env["LLM_DATA_POLICY"] = "third_party_allowed"
    env["LLM_ROUTING"] = "flexible"
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


def newest_session(output_dir: Path, since: float) -> Path | None:
    if not output_dir.is_dir():
        return None
    candidates = [p for p in output_dir.iterdir() if p.is_dir() and p.stat().st_mtime >= since]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def sum_tokens(token_usage: dict) -> dict:
    rows = token_usage.get("by_provider_model", []) if token_usage else []
    return {
        "calls": sum(r.get("calls") or 0 for r in rows),
        "prompt_tokens": sum(r.get("total_prompt_tokens") or 0 for r in rows),
        "completion_tokens": sum(r.get("total_completion_tokens") or 0 for r in rows),
        "total_tokens": sum(r.get("total_tokens") or 0 for r in rows),
        "cost_usd": round(sum(r.get("total_cost_usd") or 0 for r in rows), 6),
        # Custo por provedor (base do teto de orçamento) e modelos sem preço conhecido (custo n/d).
        "cost_by_provider": _cost_by_provider(rows),
        "unpriced_models": sorted(
            f"{r.get('llm_provider')}/{r.get('llm_model')}" for r in rows if r.get("total_cost_usd") is None
        ),
    }


def _cost_by_provider(rows: list[dict]) -> dict[str, float]:
    costs: dict[str, float] = {}
    for row in rows:
        name = row.get("llm_provider", "unknown")
        costs[name] = round(costs.get(name, 0.0) + (row.get("total_cost_usd") or 0), 6)
    return costs


def db_token_usage(session_id: str) -> dict:
    """Resumo de tokens do Postgres, para sessões que abortaram sem gravar ``session_metadata.json``."""
    from src.telemetry import get_telemetry

    return get_telemetry().get_token_summary(session_id)


def db_metrics(session_id: str) -> dict:
    """Métricas de telemetria do banco: retentativas de conexão/limite e métricas derivadas."""
    try:
        from src.telemetry import get_telemetry

        telemetry = get_telemetry()
        from scripts.benchmark.interactions import collect_session

        return {
            "interactions": collect_session(session_id),
            "connection_retries": telemetry.get_connection_retry_count(session_id),
            "derived": telemetry.get_derived_metrics(session_id),
            "tools": telemetry.get_tool_summary(session_id),
        }
    except Exception as exc:  # telemetria indisponível não invalida a medição
        return {"error": str(exc)}


def _save_log(name: str, log: str) -> str:
    """Grava a saída completa da execução (perguntas ao pesquisador, erros) ao lado dos resultados."""
    path = Path(os.environ.get("BENCHMARK_LOG_DIR", "benchmark_logs")) / f"{name}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(log, encoding="utf-8")
    return str(path)


def run_combination(
    combo: dict, task: str, env_base: dict[str, str], timeout: int, output_dir: Path, extra_env: dict | None = None
) -> dict:
    env = build_env(env_base, combo["roles"], {**(extra_env or {}), **combo.get("env", {})})
    started_wall = time.time()
    start = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--mode", "auto", task],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    sampler = ResourceSampler(root_pid=proc.pid, interval=1.0)
    sampler.start()
    timed_out = False
    try:
        log, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        log, _ = proc.communicate()
    elapsed = time.monotonic() - start
    sampler.stop()
    sampler.join(timeout=5)

    result = {
        "name": combo["name"], "roles": combo["roles"], "status": "timeout" if timed_out else f"exit {proc.returncode}",
        "wall_seconds": round(elapsed, 1), "resources": sampler.summary(), "log_tail": (log or "")[-1500:],
        "log_file": _save_log(combo["name"], log or ""),
    }
    session = newest_session(output_dir, started_wall - 1)
    if session is not None:
        outcome = session_outcome(session)
        usage = outcome.get("token_usage") or db_token_usage(session.name)  # sessão abortada: sem metadata
        result.update(session=session.name, outcome=outcome, score=score_session(session),
                      tokens=sum_tokens(usage), db=db_metrics(session.name))
    return result


def recompute_tokens(results_path: Path, output_dir: Path | None = None) -> None:
    """Preenche ``tokens`` pelo banco nas combinações sem contagem (sessão abortada) e repontua o checklist."""
    results = json.loads(results_path.read_text(encoding="utf-8"))
    for item in results:
        if output_dir and item.get("session") and (output_dir / item["session"]).is_dir():
            item["score"] = score_session(output_dir / item["session"])
        if item.get("session") and not item.get("tokens", {}).get("calls"):
            item["tokens"] = sum_tokens(db_token_usage(item["session"]))
            print(f"[benchmark] tokens recalculados do banco: {item['name']} -> {item['tokens']['total_tokens']}")
    results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--recompute", action="store_true", help="refaz os tokens do banco e sai (sem rodar nada)")
    args = parser.parse_args()
    if args.recompute:
        recompute_tokens(args.results, Path(dotenv_values('.env').get('OUTPUT_BASE_DIR') or 'outputs'))
        return

    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    task = Path(matrix["task_file"]).expanduser().read_text(encoding="utf-8")
    env_base = {**os.environ, **{k: v for k, v in dotenv_values(".env").items() if v is not None}}
    output_dir = Path(env_base.get("OUTPUT_BASE_DIR", "outputs"))
    results = json.loads(args.results.read_text()) if args.results.exists() else []
    done = {r["name"] for r in results}
    budget = matrix.get("budget_usd", {})  # teto de gasto acumulado por provedor
    spent: dict[str, float] = {}
    for r in results:
        for provider, cost in r.get("tokens", {}).get("cost_by_provider", {}).items():
            spent[provider] = spent.get(provider, 0.0) + cost

    for combo in matrix["combinations"]:
        if (args.only and combo["name"] not in args.only) or combo["name"] in done:
            continue
        required = combo.get("requires")
        providers = {spec.partition("/")[0] for spec in combo["roles"].values()}
        over = next((p for p in providers if p in budget and spent.get(p, 0.0) >= budget[p]), None)
        if required and not env_base.get(required):
            skip = f"{required} ausente"
        elif over:
            skip = f"orçamento de {over} esgotado (${spent[over]:.2f} de ${budget[over]:.2f})"
        else:
            skip = None
        if skip:
            results.append({"name": combo["name"], "roles": combo["roles"], "status": "skipped", "reason": skip})
        else:
            print(f"[benchmark] {combo['name']} ...", flush=True)
            results.append(
                run_combination(combo, task, env_base, matrix["timeout_seconds"], output_dir, matrix.get("env"))
            )
            for provider, cost in results[-1].get("tokens", {}).get("cost_by_provider", {}).items():
                spent[provider] = spent.get(provider, 0.0) + cost
        args.results.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"[benchmark] {combo['name']}: {results[-1]['status']}", flush=True)

    from scripts.benchmark.interactions import knowledge_footprint

    knowledge_path = args.results.with_name(args.results.stem + "-knowledge.json")
    knowledge_path.write_text(json.dumps(knowledge_footprint(), indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
