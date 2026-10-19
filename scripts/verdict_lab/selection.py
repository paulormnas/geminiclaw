"""Seleção de variante pelos dois instrumentos (design §14 de ``v18.8-verdict-lab``; ADR 025 §4.2).

Combina o ``resultados.csv`` da simulação (linhas ``aceite``) com o da grade: para cada variante e limiar com
falsa validação média dentro do teto na simulação, conta os acertos da grade nesse limiar e lista os cenários do
catálogo em que a variante conclui ``funciona`` onde o esperado não é ``funciona`` (falsa validação no catálogo).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from scripts.verdict_lab.output import md_table


class SelectionError(ValueError):
    """Entrada de seleção inválida."""


def _read(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError as exc:
        raise SelectionError(f"{path}: não foi possível ler ({exc}).") from exc


def select(grade_csv: Path, sim_csv: Path, fv_max: float) -> list[dict[str, Any]]:
    """Uma linha por (variante, limiar) com aceite na simulação e presente na grade."""
    grade = [r for r in _read(grade_csv) if r.get("cenario")]
    if not grade:
        raise SelectionError(f"{grade_csv}: sem linhas de cenário (esperado o resultados.csv de `grade`).")
    sim = [r for r in _read(sim_csv) if r.get("tabela") == "aceite"]
    if not sim:
        raise SelectionError(f"{sim_csv}: sem linhas `aceite` (esperado o resultados.csv de `simulacao`).")
    by_key: dict[tuple[str, float], list[dict[str, str]]] = {}
    for r in grade:
        by_key.setdefault((r["variante"], float(r["limiar"])), []).append(r)
    rows: list[dict[str, Any]] = []
    for r in sim:
        key = (r["variante"], float(r["limiar"]))
        scenarios = by_key.get(key)
        if scenarios is None:
            continue
        fv = float(r["fv_max_tipos"])
        spurious = sorted(
            s["cenario"]
            for s in scenarios
            if s["conclui"] == "funciona"
            and s["esperado"] != "funciona"
            and "funciona" not in s.get("aceitaveis", "").split(";")
        )
        hits = sum(s["acerto"] == "True" for s in scenarios)
        rows.append(
            {
                "tabela": "selecao",
                "variante": r["variante"],
                "limiar": key[1],
                "fv_sim": fv,
                "fv_pior_ponto": float(r["fv_pior_ponto"]),
                "poder_sim": float(r["poder"]),
                "falsa_refutacao_sim": float(r["falsa_refutacao"]),
                "acertos_grade": hits,
                "cenarios": len(scenarios),
                "falsas_validacoes_no_catalogo": len(spurious),
                "cenarios_falsamente_validados": ";".join(spurious),
                "aceita_sim": fv <= fv_max,
                "aceita": fv <= fv_max and not spurious,
                "fv_teto": fv_max,
            }
        )
    return rows


def selection_report(rows: list[dict[str, Any]], fv_max: float, manifest: dict[str, Any]) -> str:
    lines = [
        "# Seleção de variante pelos dois instrumentos",
        "",
        f"Gerado por `scripts.verdict_lab` em {manifest['data_utc']}, commit `{manifest['commit'][:12]}`, comando "
        f"`selecao`. Sem chamada de LLM.",
        "",
        f"Uma variante e um limiar são **aceitos** quando (1) a falsa validação média na simulação não passa de "
        f"{fv_max:.0%} e (2) a variante não conclui `funciona` em nenhum cenário do catálogo cujo esperado não é "
        "`funciona` (por exemplo, volume sem evolução ou recordes por acaso). A simulação não mede o segundo "
        "caso, e a grade não mede o primeiro (ADR 025 §4.2).",
        "",
        "## Aceitos, ordenados por poder",
        "",
    ]
    ok = sorted((r for r in rows if r["aceita"]), key=lambda r: (-r["poder_sim"], r["variante"]))
    lines.append(
        md_table(
            [
                "Variante",
                "Limiar",
                "Falsa validação (sim)",
                "Pior ponto",
                "Poder (sim)",
                "Falsa refutação",
                "Acertos da grade",
            ],
            [
                [
                    r["variante"],
                    f"{r['limiar']:g}",
                    r["fv_sim"],
                    r["fv_pior_ponto"],
                    r["poder_sim"],
                    r["falsa_refutacao_sim"],
                    f"{r['acertos_grade']}/{r['cenarios']}",
                ]
                for r in ok
            ],
        )
        if ok
        else "Nenhum."
    )
    lines += ["", "## Rejeitados pelo catálogo (dentro do teto na simulação)", ""]
    rej = sorted(
        (r for r in rows if r["aceita_sim"] and not r["aceita"]), key=lambda r: (-r["poder_sim"], r["variante"])
    )
    lines.append(
        md_table(
            ["Variante", "Limiar", "Poder (sim)", "Cenários falsamente validados"],
            [[r["variante"], f"{r['limiar']:g}", r["poder_sim"], r["cenarios_falsamente_validados"]] for r in rej],
        )
        if rej
        else "Nenhum."
    )
    lines.append("")
    return "\n".join(lines)
