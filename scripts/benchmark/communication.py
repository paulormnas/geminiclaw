"""Avaliação pós-execução da comunicação entre agentes (``v16-agent-communication-eval``).

Lê o que a sessão deixou (eventos do banco e pasta da sessão) e calcula: verdade determinística
por subtarefa, matriz de confusão do revisor, taxa de resolução e laços de reprovação, reparos do
planejador e, opcionalmente, notas de um juiz LLM sobre as perguntas de ``ask_researcher``
(``scripts/benchmark/comm_judge.py``). Nada roda dentro da sessão e nada é escrito nela.

Uso::

    uv run python -m scripts.benchmark.communication evaluate <session_id> --out <arquivo.json>
    uv run python -m scripts.benchmark.communication calibration-sheet <session_id>... --out <.jsonl>
    uv run python -m scripts.benchmark.communication calibrate --judgments <.json> --labels <.jsonl>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.agents.validator_agent import (
    _evaluate_metric_criteria,
    _find_metrics_file,
    _metric_criteria,
    issue_signature,
)
from src.artifact_match import resolve_artifacts
from src.config import COMM_EVAL_CALIBRATION_SIZE, COMM_EVAL_LOOP_MIN_LENGTH

APPROVED_REVIEW = ("pass", "divergent_but_documented")
Verdict = Literal["fulfilled", "unfulfilled", "indeterminate"]


@dataclass(frozen=True)
class TruthCheck:
    """Uma verificação determinística da verdade de uma subtarefa."""

    kind: Literal["artifact", "metric", "exit_code"]
    subject: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class SubtaskTruth:
    """Verdade determinística de uma tentativa de subtarefa."""

    task_name: str
    attempt: int
    verdict: Verdict
    checks: list[TruthCheck] = field(default_factory=list)
    detail: str = ""


# --------------------------------------------------------------------------------------------
# Leitura de eventos
# --------------------------------------------------------------------------------------------

def fetch_session_data(session_id: str) -> dict[str, Any]:
    """Lê do banco os eventos e os modelos por papel da sessão (somente leitura).

    Returns:
        ``{"events": [...], "models_by_role": {papel: "provedor/modelo"}}``; os eventos ficam
        ordenados por tempo e trazem ``ts`` em segundos desde a época.

    Raises:
        RuntimeError: Se o banco estiver indisponível (a avaliação não inventa dados).
    """
    from src.db import get_connection

    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT event_type, agent_id, target_agent_id, task_name, payload_json, timestamp "
                "FROM agent_events WHERE execution_id = %s ORDER BY timestamp",
                (session_id,),
            ).fetchall()
            model_rows = conn.execute(
                "SELECT agent_id, llm_provider, llm_model, count(*) AS n FROM token_usage "
                "WHERE execution_id = %s GROUP BY agent_id, llm_provider, llm_model ORDER BY n DESC",
                (session_id,),
            ).fetchall()
    except Exception as exc:
        raise RuntimeError(f"Banco indisponível para avaliar a sessão {session_id}: {exc}") from exc

    events = []
    for r in rows:
        raw = r["payload_json"]
        payload = json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else (raw or {})
        events.append({
            "event_type": r["event_type"], "agent_id": r["agent_id"], "target_agent_id": r["target_agent_id"],
            "task_name": r["task_name"], "ts": r["timestamp"].timestamp(),
            "payload": payload if isinstance(payload, dict) else {},
        })
    models: dict[str, str] = {}
    for r in model_rows:
        models.setdefault(r["agent_id"], f"{r['llm_provider']}/{r['llm_model']}")
    return {"events": events, "models_by_role": models}


def load_plan(session_dir: Path) -> dict[str, dict[str, Any]]:
    """Lê ``plan.json`` da sessão e devolve ``{task_name: subtarefa}`` (vazio se ausente)."""
    path = Path(session_dir) / "plan.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {t.get("task_name"): t for t in data if isinstance(t, dict) and t.get("task_name")}


# --------------------------------------------------------------------------------------------
# Verdade determinística
# --------------------------------------------------------------------------------------------

def compute_truth(
    task: dict[str, Any],
    attempt: int,
    review_ts: float | None,
    session_dir: Path,
    sandbox_events: list[dict[str, Any]],
) -> SubtaskTruth:
    """Classifica uma tentativa como ``fulfilled``, ``unfulfilled`` ou ``indeterminate``.

    Usa só código: artefatos esperados (comparador tolerante), critérios com métrica nomeada contra
    ``metrics.json`` e o código de saída do último ``sandbox_run`` da subtarefa. O código de saída
    sozinho nunca decide; com artefatos e métricas ok mas execução com erro, o veredito é
    ``indeterminate``.

    Args:
        task: Subtarefa do plano (``task_name``, ``expected_artifacts``, ``validation_criteria``...).
        attempt: Número da tentativa (do evento de revisão).
        review_ts: Instante do evento de revisão; artefatos mais novos indicam sobrescrita.
        session_dir: Pasta da sessão.
        sandbox_events: Eventos ``sandbox_run`` da subtarefa, em ordem de tempo.
    """
    name = str(task.get("task_name") or "")
    session_dir = Path(session_dir)
    checks: list[TruthCheck] = []

    expected = [e for e in (task.get("expected_artifacts") or []) if isinstance(e, str)]
    mismatched_files: list[Path] = []
    if expected:
        for res in resolve_artifacts(expected, session_dir, name, "tolerant"):
            checks.append(TruthCheck("artifact", res.expected, bool(res.matched),
                                     res.tier if res.matched else "ausente em disco"))
            mismatched_files.extend(res.matched)

    criteria = task.get("validation_criteria") or []
    metric_criteria = _metric_criteria(criteria if isinstance(criteria, list) else [])
    if metric_criteria:
        metrics_file = _find_metrics_file(session_dir, name, list(task.get("depends_on") or []))
        if metrics_file is None:
            checks.extend(TruthCheck("metric", c.text, False, "metrics.json ausente") for c in metric_criteria)
        else:
            try:
                metrics = json.loads(metrics_file.read_text(encoding="utf-8")).get("metrics", {})
            except (json.JSONDecodeError, OSError):
                metrics = {}
            for crit, (ok, detail) in zip(metric_criteria, _evaluate_metric_criteria(metric_criteria, metrics)):
                checks.append(TruthCheck("metric", crit.text, ok, detail))

    decisive = [c for c in checks if c.kind in ("artifact", "metric")]
    if not decisive:
        return SubtaskTruth(name, attempt, "indeterminate", checks, "sem artefato nem métrica aplicável")

    if review_ts is not None:
        for rel in mismatched_files:
            try:
                if (session_dir / rel).stat().st_mtime > review_ts:
                    return SubtaskTruth(name, attempt, "indeterminate", checks, "artefatos sobrescritos")
            except OSError:
                continue

    if any(not c.ok for c in decisive):
        return SubtaskTruth(name, attempt, "unfulfilled", checks)

    runs = [e for e in sandbox_events if review_ts is None or e["ts"] <= review_ts]
    if runs:
        last = runs[-1]["payload"]
        ok = last.get("exit_code") == 0 and not last.get("timed_out")
        checks.append(TruthCheck("exit_code", "sandbox", ok, f"exit_code={last.get('exit_code')}"))
        if not ok:
            return SubtaskTruth(name, attempt, "indeterminate", checks, "execução com erro, artefatos presentes")
    return SubtaskTruth(name, attempt, "fulfilled", checks)


# --------------------------------------------------------------------------------------------
# Revisor contra a verdade
# --------------------------------------------------------------------------------------------

def reviewer_confusion(pairs: list[tuple[bool, Verdict]]) -> dict[str, Any]:
    """Matriz de confusão do revisor.

    Args:
        pairs: ``(revisor aprovou, verdade)`` por revisão.

    Returns:
        Contagens (``hit``, ``false_reject``, ``false_accept``, ``indeterminate``) e as taxas;
        taxa com denominador zero é ``None``, nunca zero.
    """
    c = Counter()
    for approved, truth in pairs:
        if truth == "indeterminate":
            c["indeterminate"] += 1
        elif approved == (truth == "fulfilled"):
            c["hit"] += 1
        elif approved:
            c["false_accept"] += 1
        else:
            c["false_reject"] += 1
    fulfilled = sum(1 for _, t in pairs if t == "fulfilled")
    unfulfilled = sum(1 for _, t in pairs if t == "unfulfilled")
    rejected = sum(1 for a, t in pairs if not a and t != "indeterminate")
    correct_rejects = sum(1 for a, t in pairs if not a and t == "unfulfilled")

    def rate(num: int, den: int) -> float | None:
        return None if den == 0 else round(num / den, 4)

    return {
        "hit": c["hit"], "false_reject": c["false_reject"], "false_accept": c["false_accept"],
        "indeterminate": c["indeterminate"],
        "false_reject_rate": rate(c["false_reject"], fulfilled),
        "false_accept_rate": rate(c["false_accept"], unfulfilled),
        "reject_precision": rate(correct_rejects, rejected),
        "indeterminate_share": rate(c["indeterminate"], len(pairs)),
    }


# --------------------------------------------------------------------------------------------
# Resolução e laços
# --------------------------------------------------------------------------------------------

def _rejection_runs(sequence: list[dict[str, Any]]) -> list[tuple[list[dict[str, Any]], bool]]:
    """Corridas de reprovações consecutivas; o booleano diz se terminaram em aprovação."""
    runs: list[tuple[list[dict[str, Any]], bool]] = []
    current: list[dict[str, Any]] = []
    for item in sequence:
        if item["approved"]:
            if current:
                runs.append((current, True))
                current = []
        else:
            current.append(item)
    if current:
        runs.append((current, False))
    return runs


def resolution_stats(sequences: dict[Any, list[dict[str, Any]]]) -> dict[str, Any]:
    """Taxa de resolução das reprovações por alvo.

    Uma reprovação é *resolvida* se a corrida de reprovações consecutivas do alvo termina em
    aprovação; corrida no fim da sequência é ``unresolved_tail`` e fica fora do denominador.
    ``first_retry_rate`` é a fração das corridas resolvidas já na primeira nova tentativa.
    """
    resolved = unresolved_tail = 0
    lengths: list[int] = []
    for sequence in sequences.values():
        for run, closed in _rejection_runs(sequence):
            if closed:
                resolved += len(run)
                lengths.append(len(run))
            else:
                unresolved_tail += len(run)

    def rate(num: int, den: int) -> float | None:
        return None if den == 0 else round(num / den, 4)

    return {
        "rejections": resolved + unresolved_tail,
        "resolved": resolved,
        "unresolved_tail": unresolved_tail,
        # Spec: a cauda fica fora do denominador (então a taxa é 1,0 sempre que há corrida fechada);
        # a taxa com a cauda é a medida informativa.
        "resolution_rate": rate(resolved, resolved),
        "resolution_rate_with_tail": rate(resolved, resolved + unresolved_tail),
        "attempts_to_resolve_mean": None if not lengths else round(sum(lengths) / len(lengths), 2),
        "attempts_to_resolve_max": max(lengths) if lengths else None,
        "first_retry_rate": rate(sum(1 for n in lengths if n == 1), len(lengths)),
    }


def loop_stats(sequences: dict[Any, list[dict[str, Any]]], min_length: int | None = None) -> dict[str, Any]:
    """Laços: ``min_length`` ou mais reprovações consecutivas do mesmo alvo com a mesma assinatura."""
    min_length = COMM_EVAL_LOOP_MIN_LENGTH if min_length is None else min_length
    loops: list[int] = []
    rejections = 0
    in_loop = 0
    for sequence in sequences.values():
        streak: list[dict[str, Any]] = []
        for item in sequence + [{"approved": True, "signature": None}]:  # sentinela fecha a última corrida
            if not item["approved"]:
                rejections += 1
                if streak and item["signature"] and item["signature"] == streak[-1]["signature"]:
                    streak.append(item)
                else:
                    _close_streak(streak, min_length, loops)
                    streak = [item]
            else:
                _close_streak(streak, min_length, loops)
                streak = []
    in_loop = sum(loops)
    return {
        "loops": len(loops),
        "max_length": max(loops) if loops else 0,
        "rejections_in_loop_share": None if rejections == 0 else round(in_loop / rejections, 4),
    }


def _close_streak(streak: list[dict[str, Any]], min_length: int, loops: list[int]) -> None:
    if len(streak) >= min_length and streak[0]["signature"]:
        loops.append(len(streak))


def _signature(payload: dict[str, Any]) -> str | None:
    if payload.get("signature"):
        return str(payload["signature"])
    issues = payload.get("issues") or ([payload.get("reason")] if payload.get("reason") else [])
    return issue_signature([str(i) for i in issues]) if issues else None


def build_sequences(events: list[dict[str, Any]]) -> tuple[dict[Any, list[dict]], dict[Any, list[dict]]]:
    """Sequências por alvo: plano (``plan_validation``) e subtarefa (``subtask_review``)."""
    plan: dict[Any, list[dict]] = {}
    subtask: dict[Any, list[dict]] = {}
    for e in sorted(events, key=lambda x: x["ts"]):
        p = e["payload"]
        if e["event_type"] == "plan_validation":
            plan.setdefault("plan", []).append({"approved": bool(p.get("approved")), "signature": _signature(p)})
        elif e["event_type"] == "subtask_review":
            approved = bool(p.get("approved", p.get("status") in APPROVED_REVIEW))
            subtask.setdefault(e.get("task_name") or "?", []).append(
                {"approved": approved, "signature": _signature(p)}
            )
    return plan, subtask


def planner_repairs(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Quantos planos receberam reparo do normalizador, e por tipo."""
    plans = sum(1 for e in events if e["event_type"] == "plan_validation")
    normalized = [e for e in events if e["event_type"] == "plan_normalized"]
    kinds = Counter(r.get("kind") for e in normalized for r in e["payload"].get("repairs", []))
    return {"plans": plans, "with_repair": len(normalized), "by_kind": dict(kinds)}


# --------------------------------------------------------------------------------------------
# Avaliação de uma sessão
# --------------------------------------------------------------------------------------------

def evaluate_events(
    events: list[dict[str, Any]],
    plan: dict[str, dict[str, Any]],
    session_dir: Path,
    models_by_role: dict[str, str],
) -> dict[str, Any]:
    """Avalia comunicação a partir de eventos, plano e pasta da sessão (sem LLM, sem escrita)."""
    events = sorted(events, key=lambda e: e["ts"])
    sandbox_by_task: dict[str, list[dict]] = {}
    for e in events:
        if e["event_type"] == "sandbox_run":
            sandbox_by_task.setdefault(e.get("task_name") or "", []).append(e)

    pairs: list[tuple[bool, Verdict]] = []
    mismatches: list[dict[str, Any]] = []
    for e in events:
        if e["event_type"] != "subtask_review":
            continue
        name = e.get("task_name") or ""
        p = e["payload"]
        approved = bool(p.get("approved", p.get("status") in APPROVED_REVIEW))
        truth = compute_truth(plan.get(name, {"task_name": name}), int(p.get("attempt") or 1), e["ts"],
                              Path(session_dir), sandbox_by_task.get(name, []))
        pairs.append((approved, truth.verdict))
        if truth.verdict != "indeterminate" and approved != (truth.verdict == "fulfilled"):
            mismatches.append({
                "task_name": name, "attempt": truth.attempt, "reviewer_approved": approved,
                "truth": truth.verdict, "signature": _signature(p),
                "criteria": [c.subject for c in truth.checks if not c.ok],
            })

    plan_seq, subtask_seq = build_sequences(events)
    return {
        "reviewer": {"model": models_by_role.get("reviewer"), "confusion": reviewer_confusion(pairs),
                     "reviews": len(pairs), "mismatches": mismatches},
        "resolution": {"plan": resolution_stats(plan_seq), "subtask": resolution_stats(subtask_seq),
                       "loops": {"validator": loop_stats(plan_seq), "reviewer": loop_stats(subtask_seq)}},
        "planner_repairs": {"model": models_by_role.get("researcher"), **planner_repairs(events)},
    }


def evaluate_session(session_id: str, session_dir: Path, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Avalia uma sessão (lê o banco se ``data`` não for dado) e devolve o resultado serializável."""
    data = data or fetch_session_data(session_id)
    result = evaluate_events(data["events"], load_plan(session_dir), session_dir, data["models_by_role"])
    return {"session_id": session_id, **result, "models_by_role": data["models_by_role"]}


def write_result(result: dict[str, Any], out: Path, session_dir: Path | None = None) -> None:
    """Grava o resultado; recusa gravar dentro da pasta da sessão avaliada (design, §1)."""
    out = Path(out).resolve()
    if session_dir is not None and Path(session_dir).resolve() in (out, *out.parents):
        raise ValueError("O resultado da avaliação não pode ser gravado dentro da pasta da sessão avaliada.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evaluate", help="avalia uma sessão (sem juiz LLM, a menos que --judge)")
    ev.add_argument("session_id")
    ev.add_argument("--output-dir", type=Path, default=Path("outputs"))
    ev.add_argument("--out", type=Path, required=True)
    ev.add_argument("--judge", action="store_true", help="avalia as perguntas de ask_researcher com o juiz LLM")
    sheet = sub.add_parser("calibration-sheet", help="gera a planilha de calibração humana")
    sheet.add_argument("session_ids", nargs="+")
    sheet.add_argument("--out", type=Path, required=True)
    sheet.add_argument("--seed", type=int, default=20261005)
    cal = sub.add_parser("calibrate", help="calcula o kappa entre o juiz e os rótulos humanos")
    cal.add_argument("--judgments", type=Path, required=True)
    cal.add_argument("--labels", type=Path, required=True)
    cal.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    from scripts.benchmark import comm_judge

    if args.command == "evaluate":
        session_dir = args.output_dir / args.session_id
        data = fetch_session_data(args.session_id)
        result = evaluate_session(args.session_id, session_dir, data)
        if args.judge:
            result["ask_researcher"] = comm_judge.judge_session(args.session_id, data, load_plan(session_dir))
        write_result(result, args.out, session_dir)
        print(json.dumps({"out": str(args.out)}))
        return 0
    if args.command == "calibration-sheet":
        events = []
        for sid in args.session_ids:
            data = fetch_session_data(sid)
            events.extend(comm_judge.ask_events(sid, data))
        sample = comm_judge.calibration_sample(events, COMM_EVAL_CALIBRATION_SIZE, args.seed)
        comm_judge.write_sheet(sample, args.out)
        print(json.dumps({"events": len(sample), "out": str(args.out)}))
        return 0
    result = comm_judge.calibrate(args.judgments, args.labels)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
