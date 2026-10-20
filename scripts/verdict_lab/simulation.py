"""Simulação com resposta conhecida (design §5 de ``v18.8-verdict-lab``).

Gera sequências de tentativas para hipóteses ``verdadeira`` (média real acima do alvo por ``efeito``),
``falsa`` (abaixo do alvo por ``efeito``) e ``sem_efeito`` (média real igual ao alvo) e mede, por variante,
o que acontece quando o sistema decide na primeira vez em que ``|veredito|`` alcança o limiar.
Determinística: a mesma semente dá a mesma saída.
"""

from __future__ import annotations

import dataclasses
import itertools
import random
import statistics
from dataclasses import dataclass
from typing import Any, Iterable

from scripts.verdict_lab.scenarios import ABSOLUTO
from scripts.verdict_lab.variants import Variant, lab_verdict
from src.knowledge.verdict import Attempt, Criterion

TIPOS = ("verdadeira", "falsa", "sem_efeito")
TIPO_ABORDAGEM = "abordagem_falha"
ASSINATURA_ABORDAGEM = "MemoryError"
CURVA_LIMIARES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
CRUZAMENTOS = (0.1, 0.3, 0.5)

DEFAULT_GRID: dict[str, list[Any]] = {
    "sigma": [0.005, 0.01, 0.02],
    "tau": [0.0, 0.01],
    "efeito": [0.01, 0.02],
    "p_variacao": [0.5, 1.0],
    "p_falha": [0.0, 0.3],
    "nos": [1, 2],
    "p_infra": [0.2],
    "p_outro_no": [0.5],
    "granularidade": [None],
    "p_falha_abordagem": [0.0],
}


@dataclass(frozen=True)
class SimPoint:
    """Um ponto da grade da simulação."""

    sigma: float
    tau: float
    efeito: float
    p_variacao: float
    p_falha: float
    nos: int
    p_infra: float = 0.2
    p_outro_no: float = 0.5
    granularidade: float | None = None
    p_falha_abordagem: float = 0.0

    def label(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def grid_points(grid: dict[str, list[Any]]) -> list[SimPoint]:
    """Produto cartesiano da grade, em ordem estável."""
    keys = [f.name for f in dataclasses.fields(SimPoint)]
    unknown = set(grid) - set(keys)
    if unknown:
        raise ValueError(f"grade da simulação: chaves desconhecidas {sorted(unknown)}.")
    merged = {k: grid.get(k, DEFAULT_GRID[k]) for k in keys}
    return [SimPoint(**dict(zip(keys, combo))) for combo in itertools.product(*(merged[k] for k in keys))]


def _mean(tipo: str, point: SimPoint, criterion: Criterion) -> float:
    alvo = criterion.alvo
    assert alvo is not None
    sign = 1 if criterion.sentido == "maior_melhor" else -1
    return {"verdadeira": alvo + sign * point.efeito, "falsa": alvo - sign * point.efeito, "sem_efeito": alvo}[tipo]


def generate_sequence(
    rng: random.Random, tipo: str, point: SimPoint, max_tentativas: int, criterion: Criterion = ABSOLUTO
) -> list[Attempt]:
    """Uma sequência de tentativas de um agente simulado para uma hipótese do tipo pedido."""
    mu = None if tipo == TIPO_ABORDAGEM else _mean(tipo, point, criterion)
    configs: list[tuple[str, float]] = []
    attempts: list[Attempt] = []
    for step in range(max_tentativas):
        base = {
            "attempt_id": f"t{step + 1:03d}",
            "timestamp": f"2026-01-01T{step // 60:02d}:{step % 60:02d}:00+00:00",
            "seed": step + 1,
            "dataset_ids": ("d1",),
        }
        if tipo == TIPO_ABORDAGEM or (point.p_falha_abordagem and rng.random() < point.p_falha_abordagem):
            # Falha de abordagem com a mesma assinatura: a abordagem não funciona (tipo ``abordagem_falha``) ou o
            # Developer é incapaz de executá-la (``p_falha_abordagem`` nas demais hipóteses).
            if not configs or rng.random() < point.p_variacao:
                configs.append((f"c{len(configs) + 1}", 0.0))
                config_hash = configs[-1][0]
            else:
                config_hash = configs[rng.randrange(len(configs))][0]
            attempts.append(
                Attempt(
                    outcome_kind="falha",
                    failure_cause="abordagem",
                    failure_signature=ASSINATURA_ABORDAGEM,
                    node_id="n1",
                    session_id="s-n1",
                    config_hash=config_hash,
                    **base,
                )
            )
            continue
        if point.p_falha and rng.random() < point.p_falha:
            cause = "infraestrutura" if rng.random() < point.p_infra else "ambigua"
            attempts.append(
                Attempt(
                    outcome_kind="falha",
                    failure_cause=cause,
                    node_id="n1",
                    session_id="s-n1",
                    config_hash="sem_config",
                    **base,
                )
            )
            continue
        node = "n1"
        if not configs or rng.random() < point.p_variacao:
            config = (f"c{len(configs) + 1}", rng.gauss(0.0, point.tau) if point.tau else 0.0)
            configs.append(config)
        else:
            config = configs[rng.randrange(len(configs))]
            if point.nos > 1 and rng.random() < point.p_outro_no:
                node = f"n{rng.randrange(2, point.nos + 1)}"
        value = mu + config[1]  # type: ignore[operator] + (rng.gauss(0.0, point.sigma) if point.sigma else 0.0)
        if point.granularidade:
            value = min(1.0, max(0.0, round(value / point.granularidade) * point.granularidade))
        attempts.append(
            Attempt(
                outcome_kind="resultado",
                value=value,
                baseline=None,
                validation="validado",
                contract_complete=True,
                node_id=node,
                session_id=f"s-{node}",
                config_hash=config[0],
                **base,
            )
        )
    return attempts


def verdict_path(attempts: list[Attempt], criterion: Criterion, variant: Variant) -> list[float]:
    """Veredito depois de cada tentativa (prefixos 1..n)."""
    return [lab_verdict(attempts[: n + 1], criterion, variant).veredito for n in range(len(attempts))]


def first_crossing(path: list[float], limiar: float) -> tuple[int | None, int]:
    """``(n da primeira travessia, sinal)``; ``(None, 0)`` sem travessia."""
    for n, v in enumerate(path, start=1):
        if v >= limiar:
            return n, 1
        if v <= -limiar:
            return n, -1
    return None, 0


def expand_variants(
    variants: list[Variant], expandir: Iterable[str], epsilons: list[str], d_replica: list[float], delta: float
) -> list[tuple[Variant, str | None]]:
    """Variantes da simulação: as pedidas mais, para as de ``expandir``, versões por ``epsilon`` e por ``d_replica_no``.

    Returns:
        Pares ``(variante, epsilon simbólico)``; ``epsilon = "sigma"`` é resolvido por ponto da grade.
    """
    expandir = set(expandir)
    out: list[tuple[Variant, str | None]] = []
    for v in variants:
        out.append((v, None))
        if v.nome not in expandir:
            continue
        st = v.estrutura
        eps_list = epsilons if st.variacao_util == "melhora_o_melhor" else []
        rep_list = d_replica if st.independencia == "por_tipo" else []
        for eps in eps_list:
            changes = {} if eps == "sigma" else {"variacao_util_epsilon": delta if eps == "delta" else float(eps)}
            nv = dataclasses.replace(v, nome=f"{v.nome}@eps={eps}", estrutura=dataclasses.replace(st, **changes))
            out.append((nv, "sigma" if eps == "sigma" else None))
        for rep in rep_list:
            nv = dataclasses.replace(
                v, nome=f"{v.nome}@d_replica={rep}", estrutura=dataclasses.replace(st, d_replica_no=rep)
            )
            out.append((nv, None))
    return out


def estimate_calls(n_points: int, repeticoes: int, n_variants: int, max_tentativas: int) -> int:
    """Número de cálculos do veredito (um por prefixo de cada sequência, por variante)."""
    return n_points * repeticoes * len(TIPOS) * n_variants * max_tentativas


def _percentile(values: list[int], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def run_simulation(
    points: list[SimPoint],
    variants: list[tuple[Variant, str | None]],
    *,
    semente: int,
    repeticoes: int,
    max_tentativas: int,
    limiares: list[float],
    orcamentos: list[int],
    criterion: Criterion = ABSOLUTO,
) -> list[dict[str, Any]]:
    """Executa a grade e devolve as linhas agregadas (tabelas ``orcamento``, ``curva`` e ``cruzamento``)."""
    rows: list[dict[str, Any]] = []
    budgets = sorted({b for b in orcamentos if 1 <= b <= max_tentativas} | {max_tentativas})
    curve = sorted(set(CURVA_LIMIARES) | set(limiares))
    for pi, point in enumerate(points):
        sequences = {
            tipo: [
                generate_sequence(random.Random(f"{semente}:{pi}:{rep}:{tipo}"), tipo, point, max_tentativas, criterion)
                for rep in range(repeticoes)
            ]
            for tipo in TIPOS
        }
        for variant, eps in variants:
            if eps == "sigma":
                variant = dataclasses.replace(
                    variant, estrutura=dataclasses.replace(variant.estrutura, variacao_util_epsilon=point.sigma)
                )
            paths = {tipo: [verdict_path(seq, criterion, variant) for seq in seqs] for tipo, seqs in sequences.items()}
            base = {"ponto": pi, **point.label(), "variante": variant.nome}
            for limiar in curve:
                crossings = {t: [first_crossing(p, limiar) for p in ps] for t, ps in paths.items()}
                consumed = sum(n if n is not None else max_tentativas for cs in crossings.values() for n, _ in cs)
                useful = sum(1 for n, s in crossings["verdadeira"] if s == 1)
                for tipo, cs in crossings.items():
                    tables = [("curva", max_tentativas)]
                    if limiar in limiares:
                        tables += [("orcamento", b) for b in budgets]
                    for tabela, budget in tables:
                        total = len(cs)
                        val = sum(1 for n, s in cs if s == 1 and n <= budget)
                        ref = sum(1 for n, s in cs if s == -1 and n <= budget)
                        rows.append(
                            {
                                **base,
                                "tabela": tabela,
                                "limiar": limiar,
                                "tipo": tipo,
                                "orcamento": budget,
                                "n": total,
                                "validadas": val / total,
                                "refutadas": ref / total,
                                "indecisas": (total - val - ref) / total,
                                "custo_por_validacao_util": ((consumed / useful) if useful else None)
                                if tabela == "curva"
                                else None,
                            }
                        )
            for tipo, ps in paths.items():
                for x in CRUZAMENTOS:
                    ns = [n for n, _ in (first_crossing(p, x) for p in ps) if n is not None]
                    rows.append(
                        {
                            **base,
                            "tabela": "cruzamento",
                            "limiar": x,
                            "tipo": tipo,
                            "fracao_cruzou": len(ns) / len(ps),
                            "mediana": statistics.median(ns) if ns else None,
                            "p10": _percentile(ns, 0.1),
                            "p90": _percentile(ns, 0.9),
                        }
                    )
    return rows


def run_abordagem(
    points: list[SimPoint],
    variants: list[Variant],
    *,
    semente: int,
    repeticoes: int,
    max_tentativas: int,
    limiar: float,
    criterion: Criterion = ABSOLUTO,
) -> list[dict[str, Any]]:
    """Falha de abordagem por variante (``approach_failure_q``): conclusão de cada tipo de hipótese.

    Para cada ponto e variante, gera as hipóteses ``verdadeira``, ``falsa``, ``sem_efeito`` (com Developer incapaz
    quando ``p_falha_abordagem`` > 0) e ``abordagem_falha`` (toda tentativa falha com a mesma assinatura) e conta,
    pela primeira travessia de ``±limiar``, quantas terminam validadas, refutadas ou indecisas. As sequências são as
    mesmas para todas as variantes, de modo que a diferença entre linhas vem só do veredito.
    """
    rows: list[dict[str, Any]] = []
    for pi, point in enumerate(points):
        sequences = {
            tipo: [
                generate_sequence(random.Random(f"{semente}:{pi}:{rep}:{tipo}"), tipo, point, max_tentativas, criterion)
                for rep in range(repeticoes)
            ]
            for tipo in (*TIPOS, TIPO_ABORDAGEM)
        }
        for variant in variants:
            for tipo, seqs in sequences.items():
                found = [first_crossing(verdict_path(seq, criterion, variant), limiar) for seq in seqs]
                crossings = [sign for _, sign in found]
                refutacao = [n for n, sign in found if sign == -1 and n is not None]
                total = len(crossings)
                rows.append(
                    {
                        "ponto": pi,
                        **point.label(),
                        "variante": variant.nome,
                        "approach_failure_q": variant.params.approach_failure_q,
                        "tipo": tipo,
                        "limiar": limiar,
                        "n": total,
                        "validadas": sum(1 for s in crossings if s == 1) / total,
                        "refutadas": sum(1 for s in crossings if s == -1) / total,
                        "indecisas": sum(1 for s in crossings if s == 0) / total,
                        "tentativas_ate_refutar_mediana": statistics.median(refutacao) if refutacao else None,
                    }
                )
    return rows
