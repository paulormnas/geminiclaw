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


def build_env(base: dict[str, str], roles: dict[str, str]) -> dict[str, str]:
    """Aplica ``{"*": "prov/modelo", "DEVELOPER": ...}`` sobre as variáveis de papel."""
    env = dict(base)
    default = roles.get("*")
    assignments = {role: roles.get(role, default) for role in ROLES}
    for role, spec in assignments.items():
        if spec is None:
            continue
        provider, _, model = spec.partition("/")
        env[f"{role}_PROVIDER"], env[f"{role}_MODEL"] = provider, model
    if default:
        provider, _, model = default.partition("/")
        env["LLM_PROVIDER"], env["LLM_MODEL"], env["DEFAULT_MODEL"] = provider, model, model
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
        "cost_usd": sum(r.get("total_cost_usd") or 0 for r in rows),
    }


def run_combination(combo: dict, task: str, env_base: dict[str, str], timeout: int, output_dir: Path) -> dict:
    env = build_env(env_base, combo["roles"])
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
    }
    session = newest_session(output_dir, started_wall - 1)
    if session is not None:
        outcome = session_outcome(session)
        result.update(session=session.name, outcome=outcome, score=score_session(session),
                      tokens=sum_tokens(outcome.get("token_usage", {})))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()

    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    task = Path(matrix["task_file"]).expanduser().read_text(encoding="utf-8")
    env_base = {**os.environ, **{k: v for k, v in dotenv_values(".env").items() if v is not None}}
    output_dir = Path(env_base.get("OUTPUT_BASE_DIR", "outputs"))
    results = json.loads(args.results.read_text()) if args.results.exists() else []
    done = {r["name"] for r in results}

    for combo in matrix["combinations"]:
        if (args.only and combo["name"] not in args.only) or combo["name"] in done:
            continue
        required = combo.get("requires")
        if required and not env_base.get(required):
            results.append(
                {"name": combo["name"], "roles": combo["roles"], "status": "skipped", "reason": f"{required} ausente"}
            )
        else:
            print(f"[benchmark] {combo['name']} ...", flush=True)
            results.append(run_combination(combo, task, env_base, matrix["timeout_seconds"], output_dir))
        args.results.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[benchmark] {combo['name']}: {results[-1]['status']}", flush=True)


if __name__ == "__main__":
    main()
