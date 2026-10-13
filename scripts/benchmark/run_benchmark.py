"""Executa uma matriz de combinações de modelos contra a tarefa do ``run.sh`` e mede tudo.

Uso (no Raspberry Pi, na raiz do repositório)::

    uv run python -m scripts.benchmark.run_benchmark scripts/benchmark/matrix_baixo_custo.json \
        --results ~/bench/results.json [--only NOME ...] [--repeat N] \
        [--reset-stores --confirm-target BANCO@HOST [--no-pre-reset-dump]]

Isolamento (v18.6-benchmark-harness): com ``BENCHMARK_DATABASE_URL`` (e ``BENCHMARK_QDRANT_URL``) o runner e os
subprocessos usam o banco de benchmark. ``--reset-stores`` (operação destrutiva; exige ``--confirm-target`` igual a
``banco@host`` do alvo, a marca ``BENCHMARK_DB_MARKER`` no nome e banco diferente do de ``DATABASE_URL``)
grava o arquivo de segurança e recria o banco e as coleções do sistema do Qdrant antes de **cada** execução.
Sem a flag nada é apagado e cada resultado traz ``isolated: false``. ``--repeat N`` roda cada combinação N
vezes (chave ``(nome, repeticao)``, então uma matriz interrompida é retomada).
Cada repetição é arquivada em ``<results>.d/<combinação>/r<r>/`` (sessão, log, eventos,
grafo do projeto e ``pre_reset/``). Códigos de saída: 2 guarda do reset recusou, 3 anomalia com
``--fail-fast``, 4 reset ou conferência falhou.

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

from scripts.benchmark import footprint
from scripts.benchmark.archive import archive_dir_for, archive_repetition, fetch_events
from scripts.benchmark.reset_stores import (
    EXIT_RESET_FAILED,
    BenchmarkTarget,
    ResetError,
    ResetRefused,
    check_guards,
    reset_stores,
    target_env,
)
from scripts.benchmark.resources import ResourceSampler
from scripts.benchmark.scoring import (
    score_session,
    scoreboard_anomalies,
    session_outcome,
    validated_scoreboard,
)

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


def check_pins(roles: dict[str, str], llm_routing: dict | None) -> list[str]:
    """Confere o mapa resolvido da sessão com os pins da combinação (modo ``flexible``).

    Em ``flexible`` um pin que não vale cai em silêncio na preferência do catálogo; sem esta
    conferência o resultado seria atribuído a um modelo que não rodou.

    Returns:
        Divergências legíveis (vazio = todos os papéis rodaram no modelo pedido).
    """
    if not llm_routing:
        return ["payload llm_routing ausente: não foi possível conferir os pins"]
    default = roles.get("*")
    resolved = llm_routing.get("papeis", {})
    problems = []
    for role in ROLES:
        expected = roles.get(role, default)
        if expected is None:
            continue
        entry = resolved.get(role.lower())
        if entry is None:
            problems.append(f"{role}: sem entrada no mapa resolvido")
        elif entry.get("id") != expected or entry.get("origem") not in ("pin", "pin_legado"):
            problems.append(
                f"{role}: pedido {expected}, rodou {entry.get('id')} (origem={entry.get('origem')})"
            )
    return problems


def db_llm_routing(session_id: str) -> dict | None:
    """``payload["llm_routing"]`` da sessão mestra, ou ``None`` se indisponível."""
    try:
        from src.session import SessionManager

        session = SessionManager().get(session_id)
        payload = getattr(session, "payload", None)
        return payload.get("llm_routing") if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001 — banco indisponível não invalida a medição
        return None


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


def _stop_reason(session_dir: Path) -> str | None:
    """``motivo_parada`` do ``checkpoint.json`` da sessão, ou ``None`` se ausente/ilegível."""
    try:
        return json.loads((session_dir / "checkpoint.json").read_text(encoding="utf-8")).get("motivo_parada")
    except (OSError, ValueError):
        return None


def anomalies(result: dict) -> list[str]:
    """Problemas de infraestrutura/código numa combinação (não a baixa qualidade do modelo): interrompem o benchmark.

    Um modelo que não conclui a tarefa é resultado; processo que cai, estoura o prazo, perde o roteamento pedido,
    não grava a sessão ou deixa um grupo de métricas em erro é defeito a corrigir antes de gastar mais tokens.
    """
    if result.get("status") == "skipped":
        return []
    problems: list[str] = []
    status = str(result.get("status"))
    if status != "exit 0":
        problems.append(f"processo terminou com '{status}'")
    if "Traceback (most recent call last)" in (result.get("log_tail") or ""):
        problems.append("traceback no fim do log")
    stop = result.get("stop_reason")
    if stop and (str(stop).startswith("limite_") or stop in ("erro", "interrompida", "interrompida_pesquisador")):
        problems.append(
            f"sessão fechada por '{stop}' antes de concluir: a comparação entre modelos exige sessões completas "
            "(ajuste o orçamento da matriz)"
        )
    if not result.get("session"):
        problems.append("nenhuma sessão gravada")
    elif (result.get("outcome") or {}).get("subtasks") == 0:
        problems.append("nenhuma subtarefa executada (o pipeline não rodou; ver retiradas_por_motivo e plans/)")
    if result.get("routing_check") and not result["routing_check"].get("ok", True):
        problems.append("roteamento diferente do pedido: " + "; ".join(result["routing_check"]["divergences"]))
    metrics = result.get("operation_metrics")
    if result.get("session") and metrics is None:
        problems.append("operation_metrics ausente na sessão")
    for group, values in (metrics or {}).items():
        if isinstance(values, dict) and values.get("estado") == "erro":
            problems.append(f"grupo de métricas '{group}' em erro: {values.get('mensagem', '')[:160]}")
    if result.get("seed_error"):
        problems.append(f"semeadura do projeto falhou: {result['seed_error']}")
    if result.get("score_error"):
        problems.append(f"placar validado indisponível: {result['score_error']}")
    return problems


def pending_runs(
    combinations: list[dict], results: list[dict], repeat: int, only: list[str] | None = None
) -> list[tuple[dict, int]]:
    """Pares ``(combinação, repetição)`` ainda sem resultado, na ordem da matriz (retomada pela chave do design §6)."""
    done = {(r["name"], r.get("repeticao", 1)) for r in results}
    return [
        (combo, rep)
        for combo in combinations
        if not only or combo["name"] in only
        for rep in range(1, repeat + 1)
        if (combo["name"], rep) not in done
    ]


def compute_scoreboard(project_id: str | None, session: Path, events: list[dict] | None) -> dict:
    """Placar oficial da sessão (grafo e eventos); falha vira ``score_error``, nunca um valor inventado."""
    empty = {"accuracy_validated": None, "accuracy_source": "grafo_validado", "checks_validated": None}
    if not project_id:
        return {**empty, "accuracy_note": "sem projeto semeado"}
    try:
        from scripts.benchmark.communication import load_plan
        from src.knowledge.factory import open_raw_graph_store

        report_path = session / "relatorio_final.md"
        final_report = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
        board = validated_scoreboard(
            open_raw_graph_store(), project_id, session.name, load_plan(session), events or [], final_report
        )
        board.pop("elegiveis", None)
        return board
    except Exception as exc:  # noqa: BLE001 - registrado e tratado como defeito em ``anomalies``
        return {**empty, "accuracy_note": "placar indisponível", "score_error": f"{type(exc).__name__}: {exc}"}


def run_combination(
    combo: dict, task: str, env_base: dict[str, str], timeout: int, output_dir: Path, extra_env: dict | None = None,
    *, repeticao: int = 1, results_path: Path | None = None, target: BenchmarkTarget | None = None,
    reset: bool = False, dump: bool = True, store_sample_seconds: float = footprint.DEFAULT_STORE_SAMPLE_SECONDS,
) -> dict:
    """Uma execução (combinação x repetição): reset, semeadura, medição, placar e arquivamento (design §1).

    Raises:
        ResetError: O reset ou a conferência pós-reset falhou (o runner termina com código 4).
    """
    env = build_env(env_base, combo["roles"], {**(extra_env or {}), **combo.get("env", {})})
    archive_dir = archive_dir_for(results_path, combo["name"], repeticao) if results_path else None
    reset_report = None
    if reset and target is not None and archive_dir is not None:
        _close_local_pools()  # DROP DATABASE ... FORCE derruba conexões; fecha as do runner antes
        reset_report = reset_stores(target, archive_dir=archive_dir, dump=dump, base_env=env_base).to_dict()
    project_args: list[str] = []
    project_id = None
    seed_error = None
    if not combo.get("sem_projeto"):
        try:  # um projeto com Problema confirmado por combinação (a sessão em modo auto exige)
            from scripts.benchmark.seed_project import seed_project

            project_id = seed_project(combo["name"])
            project_args = ["--project", project_id]
        except Exception as exc:  # noqa: BLE001 - registrado; a combinação não roda sem projeto
            seed_error = f"{type(exc).__name__}: {exc}"
    base_result = {"name": combo["name"], "roles": combo["roles"], "repeticao": repeticao,
                   "isolated": bool(reset_report), "reset": reset_report}
    before = footprint.snapshot()
    started_wall = time.time()
    start = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--mode", "auto", *project_args, task],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    ) if seed_error is None else None
    if proc is None:
        return {**base_result, "status": "seed_error", "seed_error": seed_error,
                "wall_seconds": 0.0, "resources": {}, "log_tail": ""}
    sampler = ResourceSampler(root_pid=proc.pid, interval=1.0)
    sampler.start()
    store_sampler = footprint.StoreSampler(
        lambda: footprint.collect_store_sample(
            env["DATABASE_URL"], env.get("QDRANT_URL", "http://localhost:6333"),
            env.get("KNOWLEDGE_GRAPH_NAME", "knowledge"),
        ),
        store_sample_seconds,
    )
    store_sampler.start()
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
    timeline = store_sampler.stop()

    result = {
        **base_result, "status": "timeout" if timed_out else f"exit {proc.returncode}",
        "wall_seconds": round(elapsed, 1), "resources": sampler.summary(), "log_tail": (log or "")[-1500:],
        "log_file": _save_log(f"{combo['name']}-r{repeticao}", log or ""), "store_timeline": timeline,
    }
    result["project_id"] = project_id
    result["footprint_delta"] = footprint.delta(before, footprint.snapshot())
    if project_id:
        result["project_graph"] = footprint.project_graph(project_id)
    session = newest_session(output_dir, started_wall - 1)
    events = None
    if session is not None:
        result["stop_reason"] = _stop_reason(session)
        result["operation_metrics"] = footprint.session_operation_metrics(session.name)
        result["embedding_events"] = footprint.embedding_events(session.name)
        outcome = session_outcome(session)
        usage = outcome.get("token_usage") or db_token_usage(session.name)  # sessão abortada: sem metadata
        text_score = score_session(session)
        events = fetch_events(session.name)
        board = compute_scoreboard(project_id, session, events)
        result.update(session=session.name, outcome=outcome, score=text_score,
                      checks_texto=text_score["checks_texto"],
                      acuracia_declarada_texto=text_score["acuracia_declarada_texto"],
                      tokens=sum_tokens(usage), db=db_metrics(session.name), **board)
        result["anomalias_placar"] = scoreboard_anomalies(board)
        divergences = check_pins(combo["roles"], db_llm_routing(session.name))
        result["routing_check"] = {"ok": not divergences, "divergences": divergences}
        for line in divergences:
            print(f"[benchmark] AVISO {combo['name']}: {line}")
        for mark in result["anomalias_placar"]:
            print(f"[benchmark] CONFERIR {combo['name']} r{repeticao}: {mark}")
    if archive_dir is not None:
        archived = archive_repetition(
            archive_dir, session_dir=session, log=log or "", events=events,
            project_graph=footprint.project_graph_full(project_id) if project_id else None,
        )
        result["archive_dir"] = str(archived)
    return result


def _close_local_pools() -> None:
    try:
        from src.db import close_pool

        close_pool()
    except Exception:  # noqa: BLE001 - sem pool aberto não há o que fechar
        pass


def recompute_tokens(results_path: Path, output_dir: Path | None = None) -> None:
    """Preenche ``tokens`` pelo banco nas combinações sem contagem (sessão abortada) e repontua o checklist."""
    results = json.loads(results_path.read_text(encoding="utf-8"))
    for item in results:
        if output_dir and item.get("session") and (output_dir / item["session"]).is_dir():
            item["score"] = score_session(output_dir / item["session"])
            item["checks_texto"] = item["score"]["checks_texto"]
            item["acuracia_declarada_texto"] = item["score"]["acuracia_declarada_texto"]
        if item.get("session") and not item.get("tokens", {}).get("calls"):
            item["tokens"] = sum_tokens(db_token_usage(item["session"]))
            print(f"[benchmark] tokens recalculados do banco: {item['name']} -> {item['tokens']['total_tokens']}")
    results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def evaluate_communication(results_path: Path, output_dir: Path, with_judge: bool) -> None:
    """Avalia a comunicação das sessões de ``results.json`` (pós-execução) e grava o bloco ``comm_eval``."""
    from scripts.benchmark import comm_judge
    from scripts.benchmark.communication import (
        evaluate_session,
        fetch_session_data,
        load_plan,
        write_result,
    )

    results = json.loads(results_path.read_text(encoding="utf-8"))
    for r in results:
        session = r.get("session")
        if not session:
            continue
        session_dir = output_dir / session
        try:
            data = fetch_session_data(session)
            result = evaluate_session(session, session_dir, data)
            if with_judge:
                result["ask_researcher"] = comm_judge.judge_session(session, data, load_plan(session_dir), session_dir)
        except Exception as exc:  # uma sessão sem dados não derruba as demais
            r["comm_eval"] = {"error": str(exc)}
            continue
        detail = results_path.with_name(f"{results_path.stem}-comm-{session}.json")
        write_result(result, detail, session_dir)
        r["comm_eval"] = result
    results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--recompute", action="store_true", help="refaz os tokens do banco e sai (sem rodar nada)")
    parser.add_argument("--fail-fast", action="store_true",
                        help="interrompe (código 3) na primeira combinação com defeito de infraestrutura/código")
    parser.add_argument("--repeat", type=int, default=1, help="repetições por combinação (padrão 1)")
    parser.add_argument("--reset-stores", action="store_true",
                        help="OPERAÇÃO DESTRUTIVA: recria o banco e as coleções de benchmark antes de cada execução")
    parser.add_argument("--confirm-target", default=None,
                        help="banco@host de BENCHMARK_DATABASE_URL, repetido para confirmar o reset")
    parser.add_argument("--no-pre-reset-dump", action="store_true",
                        help="não grava o pg_dump e os snapshots antes do reset")
    parser.add_argument("--eval-comm", action="store_true",
                        help="avalia a comunicação entre agentes das sessões já executadas, depois da execução")
    parser.add_argument("--eval-judge", action="store_true",
                        help="com --eval-comm, inclui o juiz LLM das perguntas de ask_researcher")
    args = parser.parse_args()
    if args.recompute:
        recompute_tokens(args.results, Path(dotenv_values('.env').get('OUTPUT_BASE_DIR') or 'outputs'))
        return

    if args.eval_comm:
        evaluate_communication(args.results, Path(dotenv_values(".env").get("OUTPUT_BASE_DIR") or "outputs"),
                               args.eval_judge)
        return

    if args.repeat < 1:
        parser.error("--repeat deve ser >= 1")
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    task = Path(matrix["task_file"]).expanduser().read_text(encoding="utf-8")
    env_base = {**os.environ, **{k: v for k, v in dotenv_values(".env").items() if v is not None}}
    target = None
    try:
        if env_base.get("BENCHMARK_DATABASE_URL") or args.reset_stores:
            target = BenchmarkTarget.from_env(env_base)  # DATABASE_URL ainda é o de desenvolvimento aqui
        if args.reset_stores:
            check_guards(target, reset_requested=True, confirm_target=args.confirm_target)
    except ResetRefused as exc:
        print(f"[benchmark] RESET RECUSADO: {exc}", file=sys.stderr, flush=True)
        sys.exit(2)
    if target is not None:
        env_base = target_env(target, env_base)
        # O próprio runner (semeadura, pegada, placar) também fala com o banco de benchmark.
        for key in ("DATABASE_URL", "QDRANT_URL", "KNOWLEDGE_READER_DATABASE_URL"):
            if env_base.get(key):
                os.environ[key] = env_base[key]
        print(f"[benchmark] alvo: {target.label} ({target.safe_url}); Qdrant {target.qdrant_url}", flush=True)
    if not args.reset_stores:
        print("[benchmark] AVISO: sem --reset-stores as execuções não estão isoladas (isolated: false); "
              "o que uma grava, a próxima encontra.", flush=True)
    sample_seconds = float(env_base.get("BENCHMARK_STORE_SAMPLE_SECONDS") or footprint.DEFAULT_STORE_SAMPLE_SECONDS)
    output_dir = Path(env_base.get("OUTPUT_BASE_DIR", "outputs"))
    results = json.loads(args.results.read_text()) if args.results.exists() else []
    budget = matrix.get("budget_usd", {})  # teto de gasto acumulado por provedor
    spent: dict[str, float] = {}
    for r in results:
        for provider, cost in r.get("tokens", {}).get("cost_by_provider", {}).items():
            spent[provider] = spent.get(provider, 0.0) + cost

    for combo, repeticao in pending_runs(matrix["combinations"], results, args.repeat, args.only):
        required = combo.get("requires")
        providers = {spec.partition("/")[0] for spec in combo["roles"].values()}
        over = next((p for p in providers if p in budget and spent.get(p, 0.0) >= budget[p]), None)
        if required and not env_base.get(required):
            skip = f"{required} ausente"
        elif over:
            skip = f"orçamento de {over} esgotado (${spent[over]:.2f} de ${budget[over]:.2f})"
        else:
            skip = None
        label = f"{combo['name']} r{repeticao}"
        if skip:
            results.append({"name": combo["name"], "repeticao": repeticao, "roles": combo["roles"],
                            "status": "skipped", "reason": skip})
        else:
            print(f"[benchmark] {label} ...", flush=True)
            try:
                results.append(run_combination(
                    combo, task, env_base, matrix["timeout_seconds"], output_dir, matrix.get("env"),
                    repeticao=repeticao, results_path=args.results, target=target, reset=args.reset_stores,
                    dump=not args.no_pre_reset_dump, store_sample_seconds=sample_seconds,
                ))
            except ResetError as exc:
                results.append({"name": combo["name"], "repeticao": repeticao, "roles": combo["roles"],
                                "status": "reset_error", "reset_error": str(exc)})
                args.results.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str),
                                        encoding="utf-8")
                print(f"[benchmark] INTERROMPIDO em {label}: reset falhou: {exc}", file=sys.stderr, flush=True)
                sys.exit(EXIT_RESET_FAILED)
            for provider, cost in results[-1].get("tokens", {}).get("cost_by_provider", {}).items():
                spent[provider] = spent.get(provider, 0.0) + cost
        args.results.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"[benchmark] {label}: {results[-1]['status']}", flush=True)
        problems = anomalies(results[-1])
        if problems and args.fail_fast:
            print(f"[benchmark] INTERROMPIDO em {label}: " + " | ".join(problems), flush=True)
            sys.exit(3)

    from scripts.benchmark.interactions import knowledge_footprint

    knowledge_path = args.results.with_name(args.results.stem + "-knowledge.json")
    knowledge_path.write_text(json.dumps(knowledge_footprint(), indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
