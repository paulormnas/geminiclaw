"""Plano e orçamento das explorações (design §5). Sem LLM, sem banco, sem rede.

``plano.json``::

    {"versao": 1, "semente": 12345, "matriz": "scripts/verdict_lab/controlled/matriz_controlada.json",
     "timeout_segundos": 12000,
     "combinacoes": [{"nome": "haiku-dev-sol-juiz", "teto_usd": 4.0, "teto_sessoes": 6, "teto_minutos": 720}],
     "repeticoes": {"P": 1, "T": 1, "N": 1, "F": 1}}

O piloto entra como lista de ``exploracao.json`` (o que o orquestrador grava); o gasto esperado é a média do que o
piloto mediu por (combinação, regime), e o máximo é ``explorações × teto``
(vale sem piloto, porque o laço impõe o teto).
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

from scripts.verdict_lab.controlled.explorer import Teto
from scripts.verdict_lab.controlled.regimes import REGIMES

SEM_DADOS = "sem dados"


class PlanError(ValueError):
    """Plano inválido (mensagem com o caminho da chave)."""


def carregar_plano(path: Path) -> dict[str, Any]:
    """Lê e valida ``plano.json``.

    Raises:
        PlanError: Chave ausente, regime desconhecido, combinação repetida ou valor fora do intervalo.
    """
    try:
        plano = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PlanError(f"{path}: não foi possível ler o plano ({exc}).") from exc
    if not isinstance(plano, dict) or plano.get("versao") != 1:
        raise PlanError(f"{path}: 'versao' deve ser 1.")
    for chave in ("semente", "matriz", "combinacoes", "repeticoes"):
        if chave not in plano:
            raise PlanError(f"{path}: chave '{chave}' ausente.")
    reps = plano["repeticoes"]
    if not isinstance(reps, dict) or not reps:
        raise PlanError(f"{path}: 'repeticoes' deve mapear regimes a números.")
    for regime, n in reps.items():
        if regime not in REGIMES:
            raise PlanError(f"{path}: regime desconhecido em 'repeticoes': {regime!r}.")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            raise PlanError(f"{path}: repeticoes[{regime}] deve ser um inteiro >= 0.")
    nomes: set[str] = set()
    for i, combo in enumerate(plano["combinacoes"]):
        if not isinstance(combo, dict) or "nome" not in combo:
            raise PlanError(f"{path}: combinacoes[{i}] sem 'nome'.")
        if combo["nome"] in nomes:
            raise PlanError(f"{path}: combinação repetida: {combo['nome']!r}.")
        nomes.add(combo["nome"])
        try:
            teto_da(combo)
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanError(f"{path}: combinacoes[{i}] ({combo['nome']}): teto inválido ({exc}).") from exc
    return plano


def teto_da(combo: dict[str, Any]) -> Teto:
    return Teto(usd=float(combo["teto_usd"]), sessoes=int(combo["teto_sessoes"]), minutos=float(combo["teto_minutos"]))


def _p90(valores: list[float]) -> float:
    """Percentil 90 por posto mais próximo (sem interpolação: reproduzível e legível)."""
    ordenados = sorted(valores)
    return ordenados[max(math.ceil(0.9 * len(ordenados)) - 1, 0)]


def _estatistica(valores: list[float]) -> dict[str, float] | None:
    return {"media": statistics.fmean(valores), "p90": _p90(valores)} if valores else None


def calcular(plano: dict[str, Any], piloto: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Tabela do orçamento por combinação e regime, com totais (design §5.1)."""
    por_chave: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in piloto or []:
        por_chave.setdefault((item["combinacao"], item["regime"]), []).append(item)
    linhas: list[dict[str, Any]] = []
    for combo in plano["combinacoes"]:
        teto = teto_da(combo)
        for regime, n in plano["repeticoes"].items():
            medidas = por_chave.get((combo["nome"], regime), [])
            custo = _estatistica([m["custo_total_usd"] for m in medidas])
            tokens = _estatistica([float(m["tokens_total"]) for m in medidas])
            chamadas = _estatistica([float(m["chamadas_total"]) for m in medidas])
            agentes: dict[str, float] = {}
            for m in medidas:
                for seg in m.get("sessoes", []):
                    for agente, uso in (seg.get("uso_por_agente") or {}).items():
                        agentes[agente] = agentes.get(agente, 0.0) + float(uso.get("chamadas", 0))
            linhas.append({
                "combinacao": combo["nome"],
                "regime": regime,
                "exploracoes": n,
                "teto": {"usd": teto.usd, "sessoes": teto.sessoes, "minutos": teto.minutos},
                "medidas_do_piloto": len(medidas),
                "chamadas": chamadas,
                "chamadas_por_agente_media": (
                    {a: v / len(medidas) for a, v in sorted(agentes.items())} if medidas else None
                ),
                "tokens": tokens,
                "usd": custo,
                "gasto_esperado_usd": n * custo["media"] if custo else None,
                "gasto_maximo_usd": n * teto.usd,
            })
    totais: dict[str, dict[str, Any]] = {}
    for linha in linhas:
        alvo = totais.setdefault(
            linha["combinacao"], {"exploracoes": 0, "esperado": 0.0, "maximo": 0.0, "completo": True}
        )
        alvo["exploracoes"] += linha["exploracoes"]
        alvo["maximo"] += linha["gasto_maximo_usd"]
        if linha["gasto_esperado_usd"] is None:
            if linha["exploracoes"] > 0:
                alvo["completo"] = False
        else:
            alvo["esperado"] += linha["gasto_esperado_usd"]
    geral = {
        "exploracoes": sum(t["exploracoes"] for t in totais.values()),
        "maximo": sum(t["maximo"] for t in totais.values()),
        "esperado": (
            sum(t["esperado"] for t in totais.values()) if all(t["completo"] for t in totais.values()) else None
        ),
    }
    return {"versao": 1, "linhas": linhas, "totais_por_combinacao": totais, "total_geral": geral}


def _fmt(valor: float | None, casas: int = 2) -> str:
    return SEM_DADOS if valor is None else f"{valor:.{casas}f}"


def markdown(orcamento: dict[str, Any]) -> str:
    """Tabela em português do orçamento (cabeçalho para o pesquisador aprovar antes de rodar)."""
    saida = [
        "| Combinação | Regime | Explorações | Teto US$ | Chamadas média (p90) | Tokens média (p90) | US$ média (p90) "
        "| Esperado US$ | Máximo US$ |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for ln in orcamento["linhas"]:
        def par(estat: dict[str, float] | None, casas: int = 0) -> str:
            return SEM_DADOS if estat is None else f"{estat['media']:.{casas}f} ({estat['p90']:.{casas}f})"

        saida.append(
            f"| {ln['combinacao']} | {ln['regime']} | {ln['exploracoes']} | {ln['teto']['usd']:.2f} "
            f"| {par(ln['chamadas'])} | {par(ln['tokens'])} | {par(ln['usd'], 2)} "
            f"| {_fmt(ln['gasto_esperado_usd'])} | {ln['gasto_maximo_usd']:.2f} |"
        )
    saida.append("")
    for nome, tot in orcamento["totais_por_combinacao"].items():
        esperado = _fmt(tot["esperado"]) if tot["completo"] else SEM_DADOS
        saida.append(
            f"- **{nome}**: {tot['exploracoes']} explorações; esperado US$ {esperado}; máximo US$ {tot['maximo']:.2f}"
        )
    geral = orcamento["total_geral"]
    saida.append(
        f"- **Total**: {geral['exploracoes']} explorações; esperado US$ {_fmt(geral['esperado'])}; "
        f"**máximo US$ {geral['maximo']:.2f}**"
    )
    return "\n".join(saida) + "\n"
