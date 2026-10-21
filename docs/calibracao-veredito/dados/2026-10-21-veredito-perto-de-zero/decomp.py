import sys
from pathlib import Path

from scripts.verdict_lab.replay import replay_file
from src.knowledge.verdict import VerdictParams, compute_verdict

P = VerdictParams.from_config()
print(
    "params:",
    {
        k: getattr(P, k)
        for k in (
            "prior",
            "q_validated_complete",
            "q_validated_incomplete",
            "q_divergent",
            "lambda_ambiguous",
            "m_floor_no_baseline",
            "require_target",
            "d_variation",
            "d_variation_no_gain",
            "d_new_seed",
            "gamma",
        )
    },
)
for g in sorted(Path(sys.argv[1]).expanduser().rglob("grafo_projeto.json")):
    if "medicao" in g.parts:
        continue
    resumo, hs = replay_file(g)
    print(f"\n=== {g.parent.relative_to(Path(sys.argv[1]).expanduser())}  hipóteses={len(hs)}")
    for h in hs:
        r = compute_verdict(h.attempts, h.criterion, P)
        print(
            f" H {h.hipotese_id[-6:]} crit={h.criterion} V={r.veredito:+.3f} a={r.alpha:.2f} b={r.beta:.2f}"
            f" f={r.f:.2f} cert={r.certeza:.2f} sup={r.suporte:.2f}"
            f" n={r.n_tentativas} ev={r.n_evidencias} amb={r.n_ambiguas}"
        )
        for a, d in zip(sorted(h.attempts, key=lambda a: a.timestamp), r.detalhes):
            vld = str(a.validation or a.failure_signature)
            print(
                f"    {d.classificacao:13s} val={a.value!s:>8.8s} base={a.baseline!s:>6.6s} vld={vld:22.22s}"
                f" q={d.q:.2f} m={d.m:.2f} d={d.d:.2f} b={d.b:.2f} w={d.w:.3f} {d.tipo or ''}"
            )
