"""Linha de comando do laboratório do veredito: ``uv run python -m scripts.verdict_lab <comando> --saida <dir>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.verdict_lab import output, reports
from scripts.verdict_lab.properties import measure_properties
from scripts.verdict_lab.replay import ReplayError, replay
from scripts.verdict_lab.scenarios import DELTA, catalog
from scripts.verdict_lab.sensitivity import run_sensitivity
from scripts.verdict_lab.simulation import (
    DEFAULT_GRID,
    estimate_calls,
    expand_variants,
    grid_points,
    run_simulation,
)
from scripts.verdict_lab.variants import (
    DEFAULT_VARIANTS_PATH,
    VariantError,
    lab_verdict,
    load_variants,
    select_variants,
)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m scripts.verdict_lab", description=__doc__)
    sub = p.add_subparsers(dest="comando", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--saida", type=Path, required=True, help="diretório de saída (criado)")
        sp.add_argument("--sobrescrever", action="store_true", help="substitui um resultado anterior no diretório")
        sp.add_argument(
            "--variantes", type=Path, default=None, help=f"arquivo de variantes (padrão {DEFAULT_VARIANTS_PATH.name})"
        )
        sp.add_argument("--variante", action="append", default=None, help="restringe às variantes com este nome")

    r = sub.add_parser("replay", help="recalcula o veredito de grafos arquivados")
    r.add_argument("entradas", nargs="+", type=Path, help="arquivos grafo_projeto.json ou diretórios")
    common(r)

    g = sub.add_parser("grade", help="aplica as variantes ao catálogo de cenários")
    g.add_argument("--limiar", type=float, nargs="+", default=[0.3])
    g.add_argument("--propriedades", action="store_true", help="mede as propriedades por variante")
    g.add_argument("--familia", action="append", default=None, help="restringe às famílias indicadas")
    common(g)

    s = sub.add_parser("simulacao", help="simulação com resposta conhecida")
    s.add_argument("--semente", type=int, default=20261018)
    s.add_argument("--repeticoes", type=int, default=40)
    s.add_argument("--max-tentativas", type=int, default=20)
    s.add_argument("--limiar", type=float, nargs="+", default=[0.3])
    s.add_argument("--fv-max", type=float, default=0.02, help="teto de falsa validação do critério de aceite")
    s.add_argument("--orcamento", type=int, nargs="+", default=[3, 5, 10])
    s.add_argument("--grade", type=Path, default=None, help="JSON com listas por parâmetro da simulação")
    s.add_argument(
        "--expandir",
        nargs="*",
        default=["completa2"],
        help="variantes que ganham as versões por epsilon e d_replica_no",
    )
    s.add_argument("--epsilons", nargs="*", default=["0", "delta", "sigma"])
    s.add_argument("--d-replica", type=float, nargs="*", default=[0.3, 0.5, 0.7, 0.9])
    for key in DEFAULT_GRID:
        s.add_argument(f"--{key.replace('_', '-')}", type=_grid_value, nargs="+", default=None)
    common(s)

    e = sub.add_parser("sensibilidade", help="variação isolada e em pares dos parâmetros")
    common(e)
    return p


def _grid_value(text: str) -> Any:
    if text.lower() in ("none", "nenhuma"):
        return None
    if "/" in text:
        a, b = text.split("/", 1)
        return float(a) / float(b)
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


def _variants(args: argparse.Namespace):
    return select_variants(load_variants(args.variantes), args.variante)


def _inputs(args: argparse.Namespace) -> list[Path]:
    return [args.variantes or DEFAULT_VARIANTS_PATH]


def _cmd_replay(args: argparse.Namespace, out: Path) -> None:
    variants = _variants(args)
    files, hypotheses = replay(args.entradas, variants)
    names = [v.nome for v in variants]
    manifest = output.write_manifest(
        out,
        comando="replay",
        argumentos={"entradas": [str(p) for p in args.entradas]},
        variantes=[v.manifest() for v in variants],
        entradas=_inputs(args) + [Path(f.arquivo) for f in files],
    )
    output.write_csv(out / output.RESULTS, reports.replay_rows(hypotheses))
    (out / output.REPORT).write_text(reports.replay_report(files, hypotheses, names, manifest), encoding="utf-8")
    print(f"{len(files)} arquivos, {len(hypotheses)} hipóteses com tentativas -> {out}")


def _cmd_grade(args: argparse.Namespace, out: Path) -> None:
    variants = _variants(args)
    scenarios = [s for s in catalog() if not args.familia or s.familia in args.familia]
    results = {(s.nome, v.nome): lab_verdict(list(s.attempts), s.criterion, v) for s in scenarios for v in variants}
    names = [v.nome for v in variants]
    props = measure_properties(variants, scenarios) if args.propriedades else None
    manifest = output.write_manifest(
        out,
        comando="grade",
        argumentos={"limiar": args.limiar, "propriedades": args.propriedades, "familia": args.familia},
        variantes=[v.manifest() for v in variants],
        entradas=_inputs(args),
    )
    output.write_csv(
        out / output.RESULTS,
        reports.grid_rows(scenarios, results, names, args.limiar)
        + ([{"tabela": "propriedade", **p} for p in props] if props else []),
    )
    (out / output.REPORT).write_text(
        reports.grid_report(scenarios, results, names, args.limiar, props, manifest), encoding="utf-8"
    )
    print(f"{len(scenarios)} cenários x {len(variants)} variantes -> {out}")


def _cmd_simulacao(args: argparse.Namespace, out: Path) -> None:
    grid: dict[str, list[Any]] = {}
    inputs = _inputs(args)
    if args.grade:
        try:
            raw = json.loads(args.grade.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VariantError(f"{args.grade}: não foi possível ler a grade ({exc}).") from exc
        if not isinstance(raw, dict) or not all(isinstance(v, list) for v in raw.values()):
            raise VariantError(f"{args.grade}: esperado um objeto com uma lista por parâmetro.")
        grid.update(raw)
        inputs.append(args.grade)
    for key in DEFAULT_GRID:
        value = getattr(args, key)
        if value is not None:
            grid[key] = value
    points = grid_points(grid)
    variants = expand_variants(_variants(args), args.expandir, args.epsilons, args.d_replica, DELTA)
    calls = estimate_calls(len(points), args.repeticoes, len(variants), args.max_tentativas)
    print(
        f"{len(points)} pontos x {args.repeticoes} repetições x 3 tipos x {len(variants)} variantes x "
        f"{args.max_tentativas} tentativas: cerca de {calls:,} cálculos do veredito".replace(",", "."),
        flush=True,
    )
    rows = run_simulation(
        points,
        variants,
        semente=args.semente,
        repeticoes=args.repeticoes,
        max_tentativas=args.max_tentativas,
        limiares=args.limiar,
        orcamentos=args.orcamento,
    )
    names = [v.nome for v, _ in variants]
    manifest = output.write_manifest(
        out,
        comando="simulacao",
        argumentos={
            "repeticoes": args.repeticoes,
            "max_tentativas": args.max_tentativas,
            "limiar": args.limiar,
            "orcamento": args.orcamento,
            "grade": {k: grid.get(k, DEFAULT_GRID[k]) for k in DEFAULT_GRID},
            "expandir": args.expandir,
            "epsilons": args.epsilons,
            "d_replica": args.d_replica,
        },
        variantes=[v.manifest() | {"epsilon_por_ponto": eps} for v, eps in variants],
        entradas=inputs,
        sementes={"semente": args.semente},
    )
    rows = rows + reports.acceptance_rows(rows, names, args.fv_max)
    output.write_csv(out / output.RESULTS, rows)
    (out / output.REPORT).write_text(
        reports.simulation_report(
            rows, names, args.limiar, args.max_tentativas, len(points), args.repeticoes, manifest
        ),
        encoding="utf-8",
    )
    print(f"{len(rows)} linhas -> {out}")


def _cmd_sensibilidade(args: argparse.Namespace, out: Path) -> None:
    variants = _variants(args)
    scenarios = catalog()
    rows = [row for v in variants for row in run_sensitivity(v, scenarios)]
    manifest = output.write_manifest(
        out, comando="sensibilidade", argumentos={}, variantes=[v.manifest() for v in variants], entradas=_inputs(args)
    )
    output.write_csv(out / output.RESULTS, rows)
    (out / output.REPORT).write_text(reports.sensitivity_report(rows, manifest, len(scenarios)), encoding="utf-8")
    print(f"{len(variants)} variantes -> {out}")


_COMMANDS = {
    "replay": _cmd_replay,
    "grade": _cmd_grade,
    "simulacao": _cmd_simulacao,
    "sensibilidade": _cmd_sensibilidade,
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        out = output.prepare_output_dir(args.saida, overwrite=args.sobrescrever)
        _COMMANDS[args.comando](args, out)
    except (VariantError, ReplayError, output.OutputError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
