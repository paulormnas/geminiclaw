"""Grade sintética: completa2 (sistema) × refutação com prior menor (lado negativo apenas)."""

import csv
import dataclasses
import statistics
import sys

import scripts.verdict_lab.simulation as sim
from scripts.verdict_lab.variants import lab_verdict as _orig
from scripts.verdict_lab.variants import load_variants

PRIORS = {
    "completa2": None,
    "completa2+ref_prior_0_5": 0.5,
    "completa2+ref_prior_0_25": 0.25,
    "completa2+prior_0_5": None,
}


def asym(attempts, criterion, variant, **kw):
    r = _orig(attempts, criterion, variant, **kw)
    p_ref = PRIORS.get(variant.nome)
    if p_ref is None:
        return r
    p = variant.params.prior
    wp, wn = r.alpha - p, r.beta - p
    if wn <= wp:
        return r
    a, b = p_ref + wp, p_ref + wn
    v = r.f * ((wp + wn) / (a + b)) * (2 * a / (a + b) - 1)
    return dataclasses.replace(r, veredito=v, confianca=abs(v))


sim.lab_verdict = asym
vs = {v.nome: v for v in load_variants()}
base = vs["completa2"]
variants = [
    (base, None),
    (dataclasses.replace(base, nome="completa2+ref_prior_0_5"), None),
    (dataclasses.replace(base, nome="completa2+ref_prior_0_25"), None),
    (vs["completa2+prior_0_5"], None),
]
grid = dict(sim.DEFAULT_GRID)
grid["p_falha_abordagem"] = [0.0]
rows = sim.run_simulation(
    sim.grid_points(grid),
    variants,
    semente=20261021,
    repeticoes=40,
    max_tentativas=20,
    limiares=[0.3],
    orcamentos=[3, 5, 10],
)
with open(sys.argv[1], "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
    w.writeheader()
    w.writerows(rows)
# resumo: média sobre a grade, limiar 0,3


def media(nome, b, tipo, chave):
    return statistics.mean(
        r[chave]
        for r in rows
        if r["variante"] == nome
        and r["tabela"] == "orcamento"
        and r["limiar"] == 0.3
        and r["orcamento"] == b
        and r["tipo"] == tipo
    )


print("variante orcamento " + " ".join(f"{t}_{k}" for t in sim.TIPOS for k in ("validadas", "refutadas")))
for v, _ in variants:
    for b in (3, 5, 10, 20):
        cols = " ".join(f"{media(v.nome, b, t, k):.3f}" for t in sim.TIPOS for k in ("validadas", "refutadas"))
        print(f"{v.nome} {b} {cols}")
