"""Relatórios em Markdown de cada comando do laboratório (tabelas para os relatórios de calibração)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from scripts.verdict_lab.output import md_table
from scripts.verdict_lab.replay import ReplayedHypothesis, ReplayFile, matches_stored
from scripts.verdict_lab.scenarios import ESPERADOS, Scenario

_BANDS = (0.1, 0.3, 0.5)


def _header(title: str, manifest: dict[str, Any]) -> list[str]:
    return [
        f"# {title}",
        "",
        f"Gerado por `scripts.verdict_lab` em {manifest['data_utc']}, commit `{manifest['commit'][:12]}`, "
        f"comando `{manifest['comando']}`. Sem chamada de LLM. Parâmetros e entradas em `manifesto.json`.",
        "",
    ]


def conclusion(veredito: float, limiar: float) -> str:
    if veredito >= limiar:
        return "funciona"
    if veredito <= -limiar:
        return "nao_funciona"
    return "indeciso"


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


def replay_rows(hypotheses: list[ReplayedHypothesis]) -> list[dict[str, Any]]:
    rows = []
    for h in hypotheses:
        for nome, v in h.vereditos.items():
            rows.append(
                {
                    "execucao": h.execucao,
                    "hipotese_id": h.hipotese_id,
                    "tentativas": len(h.attempts),
                    "metrica_reconstruida": h.metrica_reconstruida,
                    "veredito_gravado": h.veredito_gravado,
                    "variante": nome,
                    "veredito": v,
                    "confere_com_gravado": matches_stored(h, nome) if nome == "atual" else "",
                }
            )
    return rows


def replay_report(
    files: list[ReplayFile], hypotheses: list[ReplayedHypothesis], variant_names: list[str], manifest: dict[str, Any]
) -> str:
    lines = _header("Repetição do veredito sobre grafos arquivados", manifest)
    total_h = sum(f.hipoteses for f in files)
    errors = [f for f in files if f.erro]
    lines += [
        "## Entradas",
        "",
        f"- Arquivos: {len(files)} ({len(errors)} com erro gravado no lugar do grafo).",
        f"- Hipóteses: {total_h}; com tentativas: {len(hypotheses)}; "
        f"não testadas: {sum(f.nao_testadas for f in files)}.",
        f"- Tentativas das hipóteses testadas: {sum(len(h.attempts) for h in hypotheses)}.",
        f"- Hipóteses com métrica reconstruída pelo nome: {sum(h.metrica_reconstruida for h in hypotheses)}.",
        "",
    ]
    if "atual" in variant_names:
        checks = [matches_stored(h) for h in hypotheses]
        diverge = [h for h, ok in zip(hypotheses, checks) if ok is False]
        lines += [
            "## Conferência com o veredito gravado (variante `atual`)",
            "",
            f"Iguais: {sum(1 for c in checks if c)}; diferentes: {len(diverge)}; sem valor gravado: "
            f"{sum(1 for c in checks if c is None)}.",
            "",
        ]
        if diverge:
            lines.append(
                md_table(
                    ["Execução", "Hipótese", "Gravado", "Recalculado", "Tentativas", "Métrica reconstruída"],
                    [
                        [
                            h.execucao,
                            h.hipotese_id[-6:],
                            h.veredito_gravado,
                            h.vereditos["atual"],
                            len(h.attempts),
                            "sim" if h.metrica_reconstruida else "não",
                        ]
                        for h in diverge
                    ],
                )
            )
            lines.append("")
    lines += ["## Hipóteses por faixa do veredito, por variante", ""]
    rows = []
    for nome in variant_names:
        vs = [abs(h.vereditos[nome]) for h in hypotheses]
        rows.append([nome] + [sum(v >= b for v in vs) for b in _BANDS] + [max(vs) if vs else None])
    lines.append(md_table(["Variante", "≥ 0,1", "≥ 0,3", "≥ 0,5", "Maior |veredito|"], rows))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# grade
# ---------------------------------------------------------------------------


def grid_rows(
    scenarios: list[Scenario], results: dict[tuple[str, str], Any], variant_names: list[str], limiares: list[float]
) -> list[dict[str, Any]]:
    rows = []
    for s in scenarios:
        for nome in variant_names:
            r = results[(s.nome, nome)]
            for limiar in limiares:
                conclui = conclusion(r.veredito, limiar)
                rows.append(
                    {
                        "cenario": s.nome,
                        "familia": s.familia,
                        "esperado": s.esperado,
                        "variante": nome,
                        "limiar": limiar,
                        "veredito": r.veredito,
                        "leitura": r.leitura,
                        "conclui": conclui,
                        "acerto": conclui == s.esperado,
                        "n_evidencias": r.n_evidencias,
                        "f": r.f,
                        "pesos": [round(d.w, 4) for d in r.detalhes],
                    }
                )
    return rows


def grid_report(
    scenarios: list[Scenario],
    results: dict[tuple[str, str], Any],
    variant_names: list[str],
    limiares: list[float],
    properties: list[dict[str, Any]] | None,
    manifest: dict[str, Any],
) -> str:
    lines = _header("Grade sintética do veredito", manifest)
    lines += ["## Acertos contra o esperado, por variante e limiar", ""]
    header = ["Variante"] + [f"Acertos (limiar {lim:g})" for lim in limiares]
    rows = []
    for nome in variant_names:
        row: list[Any] = [nome]
        for lim in limiares:
            ok = sum(conclusion(results[(s.nome, nome)].veredito, lim) == s.esperado for s in scenarios)
            row.append(f"{ok}/{len(scenarios)}")
        rows.append(row)
    lines += [md_table(header, rows), ""]

    main = limiares[0]
    lines += [f"## Acertos por família (limiar {main:g})", ""]
    familias = sorted({s.familia for s in scenarios}, key=lambda f: [x.familia for x in scenarios].index(f))
    rows = []
    for nome in variant_names:
        row = [nome]
        for fam in familias:
            sc = [s for s in scenarios if s.familia == fam]
            row.append(f"{sum(conclusion(results[(s.nome, nome)].veredito, main) == s.esperado for s in sc)}/{len(sc)}")
        rows.append(row)
    lines += [md_table(["Variante"] + familias, rows), ""]

    lines += [f"## Veredito por cenário (o esperado na segunda coluna; limiar {main:g})", ""]
    rows = []
    for s in scenarios:
        rows.append([s.nome, s.esperado] + [results[(s.nome, n)].veredito for n in variant_names])
    lines += [md_table(["Cenário", "Esperado"] + variant_names, rows), ""]

    missed = [
        s
        for s in scenarios
        if not any(conclusion(results[(s.nome, n)].veredito, main) == s.esperado for n in variant_names)
    ]
    lines += [f"## Cenários em que nenhuma variante acerta (limiar {main:g})", ""]
    lines += [f"- `{s.nome}` ({s.descricao}): esperado `{s.esperado}`, porque {s.justificativa}." for s in missed]
    lines += ["" if missed else "Nenhum.", ""]

    lines += ["## Catálogo", ""]
    lines.append(
        md_table(
            ["Cenário", "Família", "Descrição", "Esperado", "Justificativa"],
            [[s.nome, s.familia, s.descricao, s.esperado, s.justificativa] for s in scenarios],
        )
    )
    lines.append("")
    if properties:
        lines += ["## Propriedades", ""]
        lines.append(
            md_table(
                ["Variante", "Propriedade", "Verificados", "Violações", "Exemplo"],
                [[p["variante"], p["propriedade"], p["verificados"], p["violacoes"], p["exemplo"]] for p in properties],
            )
        )
        lines.append("")
    assert set(s.esperado for s in scenarios) <= set(ESPERADOS)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# simulacao
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def simulation_report(
    rows: list[dict[str, Any]],
    variant_names: list[str],
    limiares: list[float],
    max_tentativas: int,
    n_points: int,
    repeticoes: int,
    manifest: dict[str, Any],
) -> str:
    lines = _header("Simulação do veredito com resposta conhecida", manifest)
    lines += [
        f"{n_points} pontos de grade, {repeticoes} repetições por tipo de hipótese e ponto, até {max_tentativas} "
        "tentativas. A decisão é tomada na primeira vez em que |veredito| alcança o limiar. As taxas são médias "
        "sobre os pontos da grade (detalhe por ponto em `resultados.csv`).",
        "",
        "- **Falsa validação:** hipóteses `falsa` ou `sem_efeito` validadas (registradas sem contribuir).",
        "- **Poder:** hipóteses `verdadeira` validadas.",
        "- **Custo por validação útil:** tentativas gastas em todas as hipóteses por `verdadeira` validada.",
        "",
    ]
    curve = [r for r in rows if r["tabela"] == "curva"]
    agg: dict[tuple[str, float, str], list[dict[str, Any]]] = defaultdict(list)
    for r in curve:
        agg[(r["variante"], r["limiar"], r["tipo"])].append(r)

    def rate(nome: str, lim: float, tipo: str, key: str) -> float | None:
        return _mean([r[key] for r in agg.get((nome, lim, tipo), [])])

    for lim in limiares:
        lines += [f"## Resumo por variante (limiar {lim:g}, orçamento {max_tentativas})", ""]
        rows_md = []
        for nome in variant_names:
            rows_md.append(
                [
                    nome,
                    rate(nome, lim, "sem_efeito", "validadas"),
                    rate(nome, lim, "falsa", "validadas"),
                    rate(nome, lim, "verdadeira", "validadas"),
                    rate(nome, lim, "verdadeira", "refutadas"),
                    rate(nome, lim, "verdadeira", "indecisas"),
                    rate(nome, lim, "falsa", "refutadas"),
                    _mean([r["custo_por_validacao_util"] for r in agg.get((nome, lim, "verdadeira"), [])]),
                ]
            )
        lines += [
            md_table(
                [
                    "Variante",
                    "Falsa validação (sem efeito)",
                    "Falsa validação (falsa)",
                    "Poder",
                    "Falsa refutação",
                    "Indecisão (verdadeira)",
                    "Refutação correta",
                    "Custo por validação útil",
                ],
                rows_md,
            ),
            "",
        ]

    lims = sorted({r["limiar"] for r in curve})
    lines += ["## Curva de compromisso: falsa validação (sem efeito) / poder, por limiar", ""]
    rows_md = []
    for nome in variant_names:
        row: list[Any] = [nome]
        for lim in lims:
            fv, pw = rate(nome, lim, "sem_efeito", "validadas"), rate(nome, lim, "verdadeira", "validadas")
            row.append("—" if fv is None else f"{fv:.2f} / {pw:.2f}")
        rows_md.append(row)
    lines += [md_table(["Variante"] + [f"{x:g}" for x in lims], rows_md), ""]

    main = limiares[0]
    sigmas = sorted({r["sigma"] for r in curve})
    lines += [
        f"## Falsa validação (sem efeito) por ruído `sigma` e por variação sempre (`p_variacao = 1`), limiar {main:g}",
        "",
    ]
    rows_md = []
    for nome in variant_names:
        row = [nome]
        for sg in sigmas:
            sel = [
                r["validadas"]
                for r in curve
                if r["variante"] == nome
                and r["limiar"] == main
                and r["tipo"] == "sem_efeito"
                and r["sigma"] == sg
                and r["p_variacao"] == 1.0
            ]
            row.append(_mean(sel))
        rows_md.append(row)
    lines += [md_table(["Variante"] + [f"sigma {s:g}" for s in sigmas], rows_md), ""]

    cross = [r for r in rows if r["tabela"] == "cruzamento" and r["tipo"] == "verdadeira"]
    lines += ["## Tentativas até cruzar cada faixa (hipóteses verdadeiras; mediana das medianas por ponto)", ""]
    rows_md = []
    for nome in variant_names:
        row = [nome]
        for x in (0.1, 0.3, 0.5):
            sel = [r for r in cross if r["variante"] == nome and r["limiar"] == x]
            frac = _mean([r["fracao_cruzou"] for r in sel])
            med = [r["mediana"] for r in sel if r["mediana"] is not None]
            row.append(
                "—"
                if frac is None
                else f"{frac:.2f} cruzam; mediana {statistics.median(med):g}"
                if med
                else f"{frac:.2f} cruzam"
            )
        rows_md.append(row)
    lines += [md_table(["Variante", "0,1", "0,3", "0,5"], rows_md), ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# sensibilidade
# ---------------------------------------------------------------------------


def sensitivity_report(rows: list[dict[str, Any]], manifest: dict[str, Any], n_scenarios: int) -> str:
    lines = _header("Sensibilidade do veredito aos parâmetros", manifest)
    lines += [f"Efeito = média de |Δ veredito| sobre {n_scenarios} cenários do catálogo.", ""]
    for nome in sorted({r["variante"] for r in rows}, key=[r["variante"] for r in rows].index):
        iso = [r for r in rows if r["variante"] == nome and r["tabela"] == "isolado"]
        best: dict[str, dict[str, Any]] = {}
        for r in iso:
            if r["parametro"] not in best or r["efeito_medio"] > best[r["parametro"]]["efeito_medio"]:
                best[r["parametro"]] = r
        ordered = sorted(best.values(), key=lambda r: r["posicao"])
        lines += [f"## Variante `{nome}`: parâmetros por efeito (variação isolada)", ""]
        lines += [
            md_table(
                ["Posição", "Parâmetro", "Valor base", "Valor de maior efeito", "Efeito médio", "Efeito máximo"],
                [
                    [r["posicao"], r["parametro"], r["valor_base"], r["valor"], r["efeito_medio"], r["efeito_max"]]
                    for r in ordered
                ],
            ),
            "",
        ]
        pairs = [r for r in rows if r["variante"] == nome and r["tabela"] == "par"]
        if pairs:
            lines += [
                "Pares (os quatro de maior efeito, ambos × 0,75 ou × 1,25; "
                "interação = efeito do par − soma dos isolados):",
                "",
            ]
            lines += [
                md_table(
                    ["Par", "Fator", "Efeito médio", "Interação"],
                    [[r["parametro"], r["valor"], r["efeito_medio"], r["interacao"]] for r in pairs],
                ),
                "",
            ]
    return "\n".join(lines)
