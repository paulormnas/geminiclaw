"""Gera a tabela markdown do relatório a partir de ``results.json``."""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from scripts.benchmark import footprint, model_versions
from scripts.benchmark.interactions import quota_label


def _fmt(stats: dict | None, key: str = "max", suffix: str = "") -> str:
    return "-" if not stats else f"{stats[key]}{suffix}"


def _cost(tokens: dict) -> str:
    if not tokens:
        return "-"
    note = " (+n/d)" if tokens.get("unpriced_models") else ""
    return f"{tokens.get('cost_usd', 0):.4f}{note}"


def render(results: list[dict]) -> str:
    header = ("| Combinação | Rep. | Status | Tempo (s) | Tokens in | Tokens out | Subtarefas ok | Checklist | "
              "Acurácia | CPU sis. máx (%) | RAM máx (MB) | Temp máx (°C) | Throttling | Custo (USD) | Retentativas |\n"
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    rows = [header]
    for r in results:
        if r["status"] == "skipped":
            rows.append(f"| {r['name']} | {r.get('repeticao', 1)} | pulada ({r.get('reason', '')}) |" + " - |" * 12)
            continue
        if not r.get("resources"):  # reset_error ou seed_error: nada foi medido
            rows.append(f"| {r['name']} | {r.get('repeticao', 1)} | {r['status']} |" + " - |" * 12)
            continue
        res, tok = r["resources"], r.get("tokens", {})
        out = r.get("outcome", {})
        acc = r.get("accuracy_validated")
        checks = r.get("checks_validated")
        checklist = f"{sum(checks.values())}/{len(checks)}" if checks else "-"
        rows.append(
            f"| {r['name']} | {r.get('repeticao', 1)} | {r['status']} | {r['wall_seconds']} | "
            f"{tok.get('prompt_tokens', '-')} | "
            f"{tok.get('completion_tokens', '-')} | {out.get('subtasks_ok', '-')}/{out.get('subtasks', '-')} | "
            f"{checklist} | {'-' if acc is None else f'{acc:.3f}'} | "
            f"{_fmt(res['sys_cpu_pct'])} | {_fmt(res['mem_used_mb'])} | {_fmt(res['temp_c'])} | "
            f"{', '.join(res['throttled']) or 'não'} | {_cost(tok)} | "
            f"{r.get('db', {}).get('connection_retries', '-')} |"
        )
    return "\n".join(rows)


def _stats(values: list[float]) -> str:
    """``média ± desvio [mín, máx]`` (desvio amostral; ``-`` sem valores, sem desvio com uma só)."""
    if not values:
        return "-"
    mean = statistics.fmean(values)
    spread = f" ± {statistics.stdev(values):.3f}" if len(values) > 1 else ""
    return f"{mean:.3f}{spread} [{min(values):.3f}, {max(values):.3f}]"


def render_aggregates(results: list[dict]) -> str:
    """Agregados por combinação entre as repetições (design §6): tempo, custo, acurácia validada, subtarefas, paradas.

    A acurácia ignora repetições sem valor (``null``); a coluna de nulos mostra quantas foram.
    """
    groups: dict[str, list[dict]] = {}
    for r in results:
        if r.get("status") != "skipped":
            groups.setdefault(r["name"], []).append(r)
    header = (
        "| Combinação | Repetições | Tempo (s) | Custo (USD) | Acurácia validada | Acurácia nula | "
        "Subtarefas aprovadas | Motivos de parada |\n|---|---|---|---|---|---|---|---|"
    )
    rows = [header]
    for name, items in groups.items():
        accuracies = [r["accuracy_validated"] for r in items if r.get("accuracy_validated") is not None]
        stops = Counter(str(r.get("stop_reason") or "n/d") for r in items)
        approved = [r["outcome"]["subtasks_ok"] for r in items if r.get("outcome", {}).get("subtasks_ok") is not None]
        costs = [r["tokens"]["cost_usd"] for r in items if r.get("tokens", {}).get("cost_usd") is not None]
        rows.append(
            f"| {name} | {len(items)} | {_stats([r['wall_seconds'] for r in items if 'wall_seconds' in r])} | "
            f"{_stats(costs)} | {_stats(accuracies)} | {len(items) - len(accuracies)} | {_stats(approved)} | "
            f"{', '.join(f'{k}: {v}' for k, v in sorted(stops.items()))} |"
        )
    return "\n".join(rows)


def render_untested_stops(results: list[dict]) -> str:
    """Execuções fechadas por ``hipoteses_nao_testadas``: parada de pesquisa, listada à parte (não é erro)."""
    rows = [
        f"- {r['name']} (repetição {r.get('repeticao', 1)})"
        for r in results
        if r.get("status") != "skipped" and r.get("stop_reason") == "hipoteses_nao_testadas"
    ]
    return "\n".join(rows)


def render_rejected_plans_stops(results: list[dict]) -> str:
    """Execuções fechadas por ``planos_rejeitados`` (política `parar` da bateria): parada de pesquisa, não erro."""
    return "\n".join(
        f"- {r['name']} (repetição {r.get('repeticao', 1)})"
        for r in results
        if r.get("status") != "skipped" and r.get("stop_reason") == "planos_rejeitados"
    )


def render_quota_stops(results: list[dict]) -> str:
    """Execuções fechadas por ``limite_cota_provedor``, com o provedor e o modelo do evento (anomalia identificada)."""
    return "\n".join(
        f"- {r['name']} (repetição {r.get('repeticao', 1)}): {quota_label(r)}"
        for r in results
        if r.get("status") != "skipped" and r.get("stop_reason") == "limite_cota_provedor"
    )


def render_growth(results: list[dict]) -> str:
    """Crescimento das memórias por execução: total (fim menos início) e taxa por minuto (design §3.2)."""
    header = (
        "| Combinação | Rep. | Duração (min) | Nós do grafo | Pontos do Qdrant | agent_events | egress_log | "
        "execution_records | Tamanho do banco (MB) |\n|---|---|---|---|---|---|---|---|---|"
    )
    rows = [header]

    def cell(g: dict, key: str) -> str:
        return f"{g[key]['total']:+d} ({g[key]['por_minuto']}/min)"

    for r in results:
        g = footprint.growth(r.get("store_timeline") or [])
        if r.get("status") == "skipped" or g is None:
            continue
        mb = g["db_bytes"]["total"] / 1_000_000
        rows.append(
            f"| {r['name']} | {r.get('repeticao', 1)} | {g['duracao_min']} | {cell(g, 'nos_grafo')} | "
            f"{cell(g, 'pontos_qdrant')} | {cell(g, 'agent_events')} | {cell(g, 'egress_log')} | "
            f"{cell(g, 'execution_records')} | {mb:+.1f} |"
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
        if reviews.get("motivos"):  # só presente quando houve motivo registrado
            lines.append(
                "- Motivos de reprovação de subtarefa: "
                + ", ".join(f"{k}: {v}" for k, v in sorted(reviews["motivos"].items()))
            )
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
        "| Combinação | Egresso total (bytes) | Saídas novas (bytes) | Limite de saídas (bytes) | Chamadas de busca | "
        "Cadeia de execuções | Números res/calc/src | Não verificados | Afirmações (suportada/total) | "
        "Planos reprovados | Custo (USD) | CPU média (%) |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|"
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
        limit_cell = get("egresso", "limite_bytes")
        chain_cell = (chain or {}).get("resultado", "-")
        first_cause = next((name for name, count in ((chain or {}).get("motivos") or {}).items() if count), None)
        if chain_cell == "divergente" and first_cause:
            chain_cell = f"divergente ({first_cause})"
        rows.append(
            f"| {r['name']} | {get('egresso', 'bytes_total')} | {get('egresso', 'bytes_limitados')} | "
            f"{'sem limite' if limit_cell is None else limit_cell} | {get('egresso', 'consultas_busca')} | "
            f"{chain_cell} | "
            f"{'/'.join(str(origins[k]) for k in ('res', 'calc', 'src')) if origins else '-'} | "
            f"{get('proveniencia', 'numeros_nao_verificados')} | "
            f"{claims_cell} | "
            f"{get('verificacao', 'ciclos_rejeicao_plano')} | {get('custo_recursos', 'custo_usd_total')} | "
            f"{node.get('cpu_pct_medio', '-')} |"
        )
    return "\n".join(rows)


def _exploration(r: dict) -> dict | None:
    """Grupo ``exploracao`` disponível do resultado, ou ``None`` (resultado antigo ou grupo indisponível)."""
    group = (r.get("operation_metrics") or {}).get("exploracao")
    return group if isinstance(group, dict) and group.get("estado") == "disponivel" else None


def _mean(values: list[float]) -> str:
    return "n/d" if not values else f"{statistics.fmean(values):.3g}"


def render_exploration(results: list[dict]) -> str:
    """Exploração por combinação (ADR 021 §8.4 e "Revisão"): papéis, origem dos testes, ligações e hipóteses do sistema.

    Médias por execução; resultado sem o grupo (anterior à versão 2 das métricas) aparece como ``n/d``. Os testes
    aprovados contam os modelos treinados.
    """
    header = (
        "| Combinação | Execuções | Testes | Preparações | Referências | Modelos treinados (testes aprovados) | "
        "Proporção de testes do sistema | PREPARA derivadas | Hipóteses do sistema abandonadas | "
        "Paradas por hipóteses não testadas |\n|---|---|---|---|---|---|---|---|---|---|"
    )
    groups: dict[str, list[dict]] = {}
    for r in results:
        if r.get("status") != "skipped":
            groups.setdefault(r["name"], []).append(r)
    rows = [header]
    for name, items in groups.items():
        links = [(_exploration(r) or {}).get("ligacao") for r in items]
        links = [link for link in links if isinstance(link, dict) and link.get("estado") == "disponivel"]

        def per_run(key: str, sub: str | None = None) -> list[float]:
            values = []
            for link in links:
                value = link[key].get(sub) if sub else link.get(key)
                if value is not None:
                    values.append(float(value))
            return values

        outcomes = [r.get("outcome") or {} for r in items]
        trained = [o["subtasks_ok"] for o in outcomes if o.get("subtasks_ok") is not None]
        untested = sum(1 for r in items if r.get("stop_reason") == "hipoteses_nao_testadas")
        rows.append(
            f"| {name} | {len(items)} | {_mean(per_run('experimentos_por_papel', 'teste'))} | "
            f"{_mean(per_run('experimentos_por_papel', 'preparacao'))} | "
            f"{_mean(per_run('experimentos_por_papel', 'referencia'))} | {_mean([float(x) for x in trained])} | "
            f"{_mean(per_run('proporcao_testes_sistema'))} | {_mean(per_run('ligacoes_prepara_derivadas'))} | "
            f"{_mean(per_run('hipoteses_sistema_abandonadas'))} | {untested} |"
        )
    return "\n".join(rows)


def render_contract(results: list[dict]) -> str:
    """Tokens estimados do contrato por execução (ADR 022 §6.3): média, desvio, mínimo, máximo e fração da entrada."""
    header = (
        "| Combinação | Execuções | Tokens do contrato por execução | Fração da entrada | Tentativas | "
        "Divergências de hash |\n|---|---|---|---|---|---|"
    )
    groups: dict[str, list[dict]] = {}
    for r in results:
        if r.get("status") != "skipped":
            groups.setdefault(r["name"], []).append(r)
    rows = [header]
    for name, items in groups.items():
        blocks = [((_exploration(r) or {}).get("contrato")) for r in items]
        blocks = [b for b in blocks if isinstance(b, dict) and b.get("estado") == "disponivel"]
        tokens = [float(b["tokens_estimados_total"]) for b in blocks]
        fractions = [float(b["fracao_entrada"]) for b in blocks if b.get("fracao_entrada") is not None]
        rows.append(
            f"| {name} | {len(items)} | {_stats(tokens)} | {_mean(fractions)} | "
            f"{_mean([float(b['tentativas']) for b in blocks])} | {sum(int(b['divergencias']) for b in blocks)} |"
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
        conf = ev["revisao_subtarefa"]["confusion"]
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
            f"| {r['name']} | {ev['revisao_subtarefa']['reviews']} | {_pct(conf['false_reject_rate'])} | "
            f"{_pct(conf['false_accept_rate'])} | {_pct(conf['indeterminate_share'])} | "
            f"{_pct(res['subtask']['resolution_rate_with_tail'])} | "
            f"{loops['validator']['max_length']}/{loops['revisao_subtarefa']['max_length']} | "
            f"{repairs['with_repair']}/{repairs['plans']} | {judge_cell} |"
        )
    return "\n".join(rows)


if __name__ == "__main__":
    loaded = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(render(loaded))
    print()
    print(render_interactions(loaded))
    print()
    print("### Modelos e versões")
    print(model_versions.render_models(loaded))
    for warning in model_versions.version_warnings(loaded):
        print(warning)
    if any(r.get("repeticao", 1) > 1 for r in loaded):
        print()
        print(render_aggregates(loaded))
    if render_untested_stops(loaded):
        print()
        print("### Paradas por hipóteses não testadas (parada de pesquisa, não erro)")
        print(render_untested_stops(loaded))
    if render_rejected_plans_stops(loaded):
        print()
        print("### Paradas por planos rejeitados (classe própria, não é erro)")
        print(render_rejected_plans_stops(loaded))
    if render_quota_stops(loaded):
        print()
        print("### Paradas por cota ou teto de gasto do provedor (anomalia: aumente o teto ou troque o provedor)")
        print(render_quota_stops(loaded))
    if any(r.get("store_timeline") for r in loaded):
        print()
        print(render_growth(loaded))
    if any(r.get("footprint_delta") for r in loaded):
        print()
        print(render_knowledge(loaded))
    if any(r.get("operation_metrics") for r in loaded):
        print()
        print(render_operation(loaded))
    if any(r.get("operation_metrics") for r in loaded):
        print()
        print("### Exploração (ADR 021 §8.4)")
        print(render_exploration(loaded))
        print()
        print("### Contrato da subtarefa (ADR 022 §6.3)")
        print(render_contract(loaded))
    if any(r.get("comm_eval") for r in loaded):
        print()
        print(render_communication(loaded))
