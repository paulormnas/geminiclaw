"""Simulação offline: variantes do veredito sobre as tentativas reais dos grafos arquivados (sem LLM)."""

import dataclasses
import json
from pathlib import Path

from scripts.verdict_lab.replay import replay_file
from src.knowledge.verdict import VerdictParams, compute_verdict

BASE = VerdictParams.from_config()
ROOTS = [
    Path(p).expanduser()
    for p in (
        "~/bench/piloto_v18_8_parcial",
        "~/bench/verificacao_v18_8",
        "~/bench/verificacao_v18_8b",
        "~/bench/piloto_v18_8_sem_credito",
    )
]


def recover_values(grafo: Path):
    """exp_id -> (valor, status_validacao) do Resultado ligado à Metrica, para experimentos em falha."""
    g = json.loads(grafo.read_text())
    nos = {n["id"]: n for n in g["nos"]}
    mede = {a["origem"]: a["destino"] for a in g["arestas"] if a["tipo"] == "MEDE"}
    out = {}
    for a in g["arestas"]:
        if a["tipo"] != "PRODUZIU":
            continue
        e, r = nos.get(a["origem"]), nos.get(a["destino"])
        if not e or not r or e["label"] != "Experimento" or e["propriedades"].get("status") != "falha":
            continue
        if r["id"] in mede and nos.get(mede[r["id"]], {}).get("label") == "Metrica":
            v = r["propriedades"].get("valor")
            if isinstance(v, (int, float)):
                out[e["id"]] = float(v)
    return out


def transform(attempts, rec, *, falha_vira_resultado, divergente_vira_validado):
    new = []
    for a in attempts:
        if (
            falha_vira_resultado
            and a.outcome_kind == "falha"
            and a.failure_signature == "criterio_nao_atendido"
            and a.attempt_id in rec
        ):
            a = dataclasses.replace(
                a,
                outcome_kind="resultado",
                value=rec[a.attempt_id],
                validation="validado",
                failure_cause=None,
                failure_signature=None,
                contract_complete=True,
            )
        if divergente_vira_validado and a.outcome_kind == "resultado" and a.validation == "divergente_documentado":
            a = dataclasses.replace(a, validation="validado")
        new.append(a)
    return new


def form(r, params, kind):
    if kind == "atual":
        return r.veredito
    if kind == "direcao":  # (α−β)/(α+β): sem o fator certeza (o prior já encolhe)
        return r.f * (r.alpha - r.beta) / (r.alpha + r.beta)
    raise ValueError(kind)


VARIANTS = [
    ("V0 atual", {}, {}, "atual"),
    ("V1 +falha c/ valor vira resultado", {"falha_vira_resultado": True}, {}, "atual"),
    ("V2 +divergente vale validado", {"falha_vira_resultado": True, "divergente_vira_validado": True}, {}, "atual"),
    ("V3 V2 + prior 0,5", {"falha_vira_resultado": True, "divergente_vira_validado": True}, {"prior": 0.5}, "atual"),
    ("V4 V2 + prior 0,25", {"falha_vira_resultado": True, "divergente_vira_validado": True}, {"prior": 0.25}, "atual"),
    ("V5 V2 + forma (α−β)/(α+β)", {"falha_vira_resultado": True, "divergente_vira_validado": True}, {}, "direcao"),
    ("V6 só prior 0,25", {}, {"prior": 0.25}, "atual"),
    ("V7 só forma (α−β)/(α+β)", {}, {}, "direcao"),
]

hyps = []
for root in ROOTS:
    for g in sorted(root.rglob("grafo_projeto.json")):
        if "medicao" in g.parts:
            continue
        try:
            _, hs = replay_file(g)
        except Exception as e:
            print("skip", g, e)
            continue
        rec = recover_values(g)
        verdade = (
            json.loads((g.parent / "verdade" / "verdade.json").read_text())
            if (g.parent / "verdade" / "verdade.json").is_file()
            else {}
        )
        regime = verdade.get("regime", "?")
        for h in hs:
            hyps.append((f"{root.name[-12:]}/{g.parent.parent.parent.name[:6]}/{regime}", h, rec, regime))

print(f"{len(hyps)} hipóteses testadas")
hdr = f"{'exploração':32s} {'H':6s} n " + " ".join(f"{v[0][:3]:>6s}" for v in VARIANTS)
print(hdr)
for tag, h, rec, regime in hyps:
    row = []
    for name, tk, pk, kind in VARIANTS:
        params = dataclasses.replace(BASE, **pk)
        at = transform(
            h.attempts,
            rec,
            falha_vira_resultado=tk.get("falha_vira_resultado", False),
            divergente_vira_validado=tk.get("divergente_vira_validado", False),
        )
        r = compute_verdict(at, h.criterion, params)
        row.append(form(r, params, kind))
    print(f"{tag:32s} {h.hipotese_id[-6:]} {len(h.attempts):2d} " + " ".join(f"{v:+6.3f}" for v in row))
print()
for name, *_ in VARIANTS:
    print(name)

print("\nSensibilidade sintética: k evidências concordantes de peso cheio (w=1) e nada contra")
print(f"{'k':>2s} " + " ".join(f"{v[0][:3]:>6s}" for v in VARIANTS if v[1] == {} or True))
for k in (1, 2, 3, 4, 6):
    out = []
    for name, tk, pk, kind in VARIANTS:
        p = dataclasses.replace(BASE, **pk)
        a, b = p.prior + k, p.prior
        cert = (a + b - 2 * p.prior) / (a + b)
        sup = a / (a + b)
        out.append(cert * (2 * sup - 1) if kind == "atual" else (a - b) / (a + b))
    print(f"{k:2d} " + " ".join(f"{v:+6.3f}" for v in out))
