"""Medição das explorações controladas com o veredito real (design §6; ADR 025, etapa 3).

Lê, de cada exploração arquivada, o ``exploracao.json``, o ``grafo_projeto.json`` e o ``verdade/verdade.json``,
reaplica o veredito do sistema às tentativas de cada hipótese (``replay``), confere a equivalência com a variante
``completa2`` do laboratório, calcula as medidas do design §6.2 e compara as taxas com a previsão da simulação do
laboratório (§6.3). Nenhum parâmetro do veredito é ajustado com estes dados.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.verdict_lab import output
from scripts.verdict_lab.controlled import stats
from scripts.verdict_lab.replay import ARCHIVE_NAME, ReplayedHypothesis, ReplayError, replay_file
from scripts.verdict_lab.simulation import SimPoint, run_simulation
from scripts.verdict_lab.variants import Variant, current_variant, lab_verdict, load_variants
from src.knowledge.verdict import Attempt, Criterion, VerdictParams, compute_verdict

LIMIAR = 0.3
TOL_EQUIVALENCIA = 1e-12
TOL_GRAVADO = 1e-6  # o sistema grava o veredito arredondado a seis casas
VARIANTE_REFERENCIA = "completa2"
TIPO_DA_SIMULACAO = {"P": "verdadeira", "T": "falsa", "N": "sem_efeito"}
REGIMES_PREVISTOS = ("P", "T", "N")
TODAS = "(todas)"

VALIDADA, REFUTADA, INDECISA = "validada", "refutada", "indecisa"


class MeasureError(ValueError):
    """Entrada inconsistente ou divergência de equivalência; a mensagem cita o arquivo ou a hipótese."""


@dataclass
class HipoteseMedida:
    """Uma hipótese testada de uma exploração, com o veredito do sistema e as variantes do laboratório."""

    id: str
    estado: str
    veredito_gravado: float | None
    veredito_sistema: float
    veredito_completa2: float
    veredito_atual: float
    n_tentativas: int
    variacoes: int
    variacoes_uteis: int
    tentativas_ate_limiar: int | None
    plantada: bool
    tentativas: list[Attempt] = field(repr=False, default_factory=list)
    criterion: Criterion | None = field(repr=False, default=None)


@dataclass
class ExploracaoMedida:
    """Uma exploração arquivada."""

    combinacao: str
    regime: str
    repeticao: int
    pasta: Path
    fim: str
    censurada: bool
    custo_usd: float
    chamadas: int
    tokens: int
    nao_testadas: int
    hipoteses: list[HipoteseMedida]
    verdade: dict[str, Any]

    def tem(self, estado: str) -> bool:
        return any(h.estado == estado for h in self.hipoteses)


def estado_do(veredito: float) -> str:
    """``validada`` (≥ 0,3), ``refutada`` (≤ −0,3) ou ``indecisa``."""
    if veredito >= LIMIAR:
        return VALIDADA
    if veredito <= -LIMIAR:
        return REFUTADA
    return INDECISA


def _ate_limiar(tentativas: list[Attempt], criterion: Criterion, params: VerdictParams) -> int | None:
    ordenadas = sorted(tentativas, key=lambda a: a.timestamp)
    for n in range(1, len(ordenadas) + 1):
        if compute_verdict(ordenadas[:n], criterion, params).veredito >= LIMIAR:
            return n
    return None


def _medir_hipotese(
    h: ReplayedHypothesis, params: VerdictParams, completa2: Variant, atual: Variant, assinatura: str | None
) -> HipoteseMedida:
    sistema = compute_verdict(h.attempts, h.criterion, params)
    ref = lab_verdict(h.attempts, h.criterion, completa2)
    if abs(sistema.veredito - ref.veredito) > TOL_EQUIVALENCIA:
        raise MeasureError(
            f"{h.arquivo}: hipótese {h.hipotese_id}: o veredito do sistema ({sistema.veredito!r}) diverge do da "
            f"variante {completa2.nome} ({ref.veredito!r}) por mais de {TOL_EQUIVALENCIA:g}; "
            "isto é defeito, não resultado."
        )
    if h.veredito_gravado is not None and abs(h.veredito_gravado - sistema.veredito) > TOL_GRAVADO:
        raise MeasureError(
            f"{h.arquivo}: hipótese {h.hipotese_id}: veredito gravado {h.veredito_gravado} difere do recalculado "
            f"{sistema.veredito:.6f} (parâmetros VERDICT_* da medição diferem dos da rodada?)."
        )
    veredito = h.veredito_gravado if h.veredito_gravado is not None else sistema.veredito
    variacoes = [d for d in sistema.detalhes if d.tipo == "variacao"]
    return HipoteseMedida(
        id=h.hipotese_id,
        estado=estado_do(veredito),
        veredito_gravado=h.veredito_gravado,
        veredito_sistema=sistema.veredito,
        veredito_completa2=ref.veredito,
        veredito_atual=lab_verdict(h.attempts, h.criterion, atual).veredito,
        n_tentativas=len(h.attempts),
        variacoes=len(variacoes),
        variacoes_uteis=sum(1 for d in variacoes if d.util),
        tentativas_ate_limiar=_ate_limiar(h.attempts, h.criterion, params),
        plantada=bool(assinatura) and any(a.failure_signature == assinatura for a in h.attempts),
        tentativas=list(h.attempts),
        criterion=h.criterion,
    )


def _ler_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MeasureError(f"{path}: não foi possível ler ({exc}).") from exc
    if not isinstance(data, dict):
        raise MeasureError(f"{path}: esperado um objeto JSON.")
    return data


def carregar_exploracao(
    pasta: Path, params: VerdictParams, completa2: Variant, atual: Variant
) -> ExploracaoMedida:
    """Mede uma exploração arquivada em ``pasta`` (``<combinação>/<regime>/r<r>/``)."""
    exp = _ler_json(pasta / "exploracao.json")
    verdade_path = pasta / "verdade" / "verdade.json"
    if not verdade_path.is_file():
        raise MeasureError(f"{verdade_path}: verdade.json ausente.")
    verdade = _ler_json(verdade_path)
    regime = str(exp.get("regime") or "")
    if regime != verdade.get("regime"):
        raise MeasureError(f"{pasta}: regime do exploracao.json ({regime!r}) difere do verdade.json.")
    censurada = bool(exp.get("censurada"))
    grafo = pasta / ARCHIVE_NAME
    if not grafo.is_file():
        raise MeasureError(f"{grafo}: grafo ausente.")
    try:
        resumo, hs = replay_file(grafo)
    except ReplayError as exc:
        raise MeasureError(str(exc)) from exc
    if resumo.erro and not censurada:
        raise MeasureError(f"{grafo}: exploração não censurada sem grafo ({resumo.erro}).")
    assinatura = (verdade.get("abordagem_plantada") or {}).get("assinatura_falha")
    return ExploracaoMedida(
        combinacao=str(exp.get("combinacao") or ""),
        regime=regime,
        repeticao=int(exp.get("repeticao") or 0),
        pasta=pasta,
        fim=str(exp.get("fim") or ""),
        censurada=censurada,
        custo_usd=float(exp.get("custo_total_usd") or 0.0),
        chamadas=int(exp.get("chamadas_total") or 0),
        tokens=int(exp.get("tokens_total") or 0),
        nao_testadas=resumo.nao_testadas,
        hipoteses=[_medir_hipotese(h, params, completa2, atual, assinatura) for h in hs],
        verdade=verdade,
    )


def carregar_rodada(rodada: Path, params: VerdictParams | None = None) -> list[ExploracaoMedida]:
    """Todas as explorações sob ``rodada``, em ordem estável (combinação, regime, repetição)."""
    if not rodada.is_dir():
        raise MeasureError(f"{rodada}: diretório inexistente.")
    params = params or VerdictParams.from_config()
    variantes = {v.nome: v for v in load_variants()}
    if VARIANTE_REFERENCIA not in variantes:
        raise MeasureError(f"variante {VARIANTE_REFERENCIA!r} ausente de variantes.json.")
    completa2, atual = variantes[VARIANTE_REFERENCIA], current_variant()
    pastas = sorted(p.parent for p in rodada.rglob("exploracao.json") if "medicao" not in p.parts)
    if not pastas:
        raise MeasureError(f"{rodada}: nenhum exploracao.json encontrado.")
    return sorted(
        (carregar_exploracao(p, params, completa2, atual) for p in pastas),
        key=lambda e: (e.combinacao, e.regime, e.repeticao),
    )


# ---------------------------------------------------------------------------
# Medidas (design §6.2)
# ---------------------------------------------------------------------------


def _taxa_de(expls: list[ExploracaoMedida], predicado: Any) -> stats.Taxa:
    return stats.taxa(sum(1 for e in expls if predicado(e)), len(expls))


def medir_grupo(expls: list[ExploracaoMedida]) -> dict[str, Any]:
    """Medidas de um conjunto de explorações do mesmo regime (e da mesma combinação, ou de todas)."""
    validas = [e for e in expls if not e.censurada]
    hs = [h for e in validas for h in e.hipoteses]
    com_validada = _taxa_de(validas, lambda e: e.tem(VALIDADA))
    discordante = _taxa_de(validas, lambda e: e.tem(REFUTADA) and not e.tem(VALIDADA))
    indecisa = _taxa_de(validas, lambda e: not e.tem(VALIDADA) and not e.tem(REFUTADA))
    plantadas = [h for h in hs if h.plantada]
    custo = sum(e.custo_usd for e in expls)
    chamadas = sum(e.chamadas for e in expls)
    n_validadas = com_validada.k
    return {
        "n_exploracoes": len(expls),
        "n_validas": len(validas),
        "n_censuradas": len(expls) - len(validas),
        "censuradas_por_fim": {
            fim: sum(1 for e in expls if e.censurada and e.fim == fim)
            for fim in sorted({e.fim for e in expls if e.censurada})
        },
        "com_hipotese_validada": com_validada,
        "refutacao_discordante": discordante,
        "indecisao": indecisa,
        "hipoteses": {
            "total": len(hs),
            VALIDADA: sum(1 for h in hs if h.estado == VALIDADA),
            REFUTADA: sum(1 for h in hs if h.estado == REFUTADA),
            INDECISA: sum(1 for h in hs if h.estado == INDECISA),
            "nao_testadas": sum(e.nao_testadas for e in validas),
        },
        "variacoes_uteis": stats.resumo([float(h.variacoes_uteis) for h in hs]),
        "variacoes_total": stats.resumo([float(h.variacoes) for h in hs]),
        "tentativas_ate_limiar": stats.resumo([float(h.tentativas_ate_limiar) for h in hs if h.tentativas_ate_limiar]),
        "abordagem_plantada": {
            "hipoteses": len(plantadas),
            VALIDADA: sum(1 for h in plantadas if h.estado == VALIDADA),
            REFUTADA: sum(1 for h in plantadas if h.estado == REFUTADA),
            INDECISA: sum(1 for h in plantadas if h.estado == INDECISA),
        },
        "custo_usd": custo,
        "chamadas": chamadas,
        "custo_por_validacao_usd": custo / n_validadas if n_validadas else None,
        "chamadas_por_validacao": chamadas / n_validadas if n_validadas else None,
        "validadas_atual": _taxa_de(validas, lambda e: any(h.veredito_atual >= LIMIAR for h in e.hipoteses)),
        "validadas_completa2": _taxa_de(validas, lambda e: any(h.veredito_completa2 >= LIMIAR for h in e.hipoteses)),
    }


def agrupar(expls: list[ExploracaoMedida]) -> dict[tuple[str, str], list[ExploracaoMedida]]:
    """Explorações por (combinação, regime), mais o grupo ``(todas)`` de cada regime."""
    grupos: dict[tuple[str, str], list[ExploracaoMedida]] = {}
    for e in expls:
        grupos.setdefault((e.combinacao, e.regime), []).append(e)
        grupos.setdefault((TODAS, e.regime), []).append(e)
    return dict(sorted(grupos.items()))


def equivalencia(expls: list[ExploracaoMedida]) -> dict[str, Any]:
    """Resumo da conferência sistema × ``completa2`` (o carregamento já falhou se algo divergiu)."""
    hs = [h for e in expls for h in e.hipoteses]
    gravadas = [h for h in hs if h.veredito_gravado is not None]
    return {
        "hipoteses": len(hs),
        "com_veredito_gravado": len(gravadas),
        "maior_diferenca_completa2": max((abs(h.veredito_sistema - h.veredito_completa2) for h in hs), default=0.0),
        "maior_diferenca_gravado": max(
            (abs(h.veredito_sistema - (h.veredito_gravado or 0.0)) for h in gravadas), default=0.0
        ),
        "estado_diverge_atual": sum(1 for h in hs if estado_do(h.veredito_atual) != estado_do(h.veredito_completa2)),
    }


# ---------------------------------------------------------------------------
# Previsão pela simulação (design §6.3, itens 2 e 3)
# ---------------------------------------------------------------------------


def estimar_parametros(hs: list[HipoteseMedida]) -> dict[str, Any]:
    """Parâmetros da simulação a partir das hipóteses observadas; ``motivo`` quando não é possível estimá-los."""
    if not hs:
        return {"motivo": "sem hipóteses testadas nas explorações P e N"}
    resultados = [[a for a in h.tentativas if a.outcome_kind == "resultado" and a.value is not None] for h in hs]
    graus = soma_quadrados = 0.0
    por_config: list[dict[str, list[float]]] = []
    for rs in resultados:
        configs: dict[str, list[float]] = {}
        for a in rs:
            configs.setdefault(a.config_hash, []).append(float(a.value))  # type: ignore[arg-type]
        por_config.append(configs)
        for valores in configs.values():
            if len(valores) >= 2:
                graus += len(valores) - 1
                soma_quadrados += statistics.variance(valores) * (len(valores) - 1)
    if graus == 0:
        return {"motivo": "nenhuma configuração repetida: o desvio entre repetições (sigma) não é estimável"}
    sigma = math.sqrt(soma_quadrados / graus)
    excessos: list[float] = []
    for configs in por_config:
        medias = [statistics.fmean(v) for v in configs.values()]
        if len(medias) >= 2:
            ruido = statistics.fmean(sigma**2 / len(v) for v in configs.values())
            excessos.append(statistics.variance(medias) - ruido)
    if not excessos:
        return {"motivo": "nenhuma hipótese com duas configurações: a dispersão (tau) não é estimável"}
    tau = math.sqrt(max(0.0, statistics.fmean(excessos)))
    n_resultados = sum(len(rs) for rs in resultados)
    n_configs = sum(len(c) for c in por_config)
    n_hs = len(hs)
    p_variacao = (n_configs - n_hs) / (n_resultados - n_hs) if n_resultados > n_hs else None
    if p_variacao is None:
        return {"motivo": "hipóteses com um único resultado: a probabilidade de variar não é estimável"}
    n_tentativas = sum(h.n_tentativas for h in hs)
    n_falhas = n_tentativas - n_resultados
    return {
        "sigma": sigma,
        "tau": tau,
        "p_variacao": min(1.0, max(0.0, p_variacao)),
        "p_falha": n_falhas / n_tentativas,
        "tentativas_por_hipotese": max(1, round(statistics.median(h.n_tentativas for h in hs))),
        "nos": max(1, len({a.node_id for h in hs for a in h.tentativas})),
        "n_hipoteses": n_hs,
    }


def _transformar(p: float | None, hipoteses: int) -> float | None:
    """Taxa por hipótese → taxa por exploração com ``hipoteses`` hipóteses independentes."""
    return None if p is None else 1 - (1 - p) ** hipoteses


def prever(
    combinacao: str, regime: str, parametros: dict[str, Any], observadas: list[ExploracaoMedida], *,
    semente: int, repeticoes: int,
) -> dict[str, Any]:
    """Taxa prevista pela simulação do laboratório para o regime, com o intervalo, em nível de exploração."""
    validas = [e for e in observadas if not e.censurada]
    hs = [h for e in validas for h in e.hipoteses]
    if "motivo" in parametros:
        return {"motivo": parametros["motivo"]}
    if not validas or not hs or hs[0].criterion is None:
        return {"motivo": f"sem explorações não censuradas com hipótese no regime {regime}"}
    verdade = validas[0].verdade
    efeito = abs(float(verdade["teto"]) - float(verdade["alvo"])) if regime in ("P", "T") else 0.0
    ponto = SimPoint(
        sigma=parametros["sigma"], tau=parametros["tau"], efeito=efeito, p_variacao=parametros["p_variacao"],
        p_falha=parametros["p_falha"], nos=parametros["nos"],
    )
    tentativas = parametros["tentativas_por_hipotese"]
    linhas = run_simulation(
        [ponto], [(load_variantes()[VARIANTE_REFERENCIA], None)], semente=semente, repeticoes=repeticoes,
        max_tentativas=tentativas, limiares=[LIMIAR], orcamentos=[tentativas], criterion=hs[0].criterion,
    )
    tipo = TIPO_DA_SIMULACAO[regime]
    linha = next(r for r in linhas if r["tabela"] == "curva" and r["limiar"] == LIMIAR and r["tipo"] == tipo)
    por_hipotese = stats.taxa(round(linha["validadas"] * linha["n"]), linha["n"])
    n_hip = max(1, round(statistics.median(len(e.hipoteses) for e in validas)))
    return {
        "tipo": tipo,
        "hipoteses_por_exploracao": n_hip,
        "por_hipotese": por_hipotese,
        "prevista": _transformar(por_hipotese.valor, n_hip),
        "baixo": _transformar(por_hipotese.baixo, n_hip),
        "alto": _transformar(por_hipotese.alto, n_hip),
        "repeticoes": repeticoes,
        "efeito": efeito,
    }


def load_variantes() -> dict[str, Variant]:
    return {v.nome: v for v in load_variants()}


def comparar(
    grupos: dict[tuple[str, str], list[ExploracaoMedida]], *, semente: int, repeticoes: int
) -> list[dict[str, Any]]:
    """Por combinação e regime P, T e N: taxa observada, prevista e a classificação compatível/incompatível."""
    combinacoes = sorted({c for c, _ in grupos if c != TODAS})
    linhas: list[dict[str, Any]] = []
    for combo in combinacoes:
        base = [
            h for r in ("P", "N") for e in grupos.get((combo, r), []) if not e.censurada for h in e.hipoteses
        ]
        parametros = estimar_parametros(base)
        for regime in REGIMES_PREVISTOS:
            obs = grupos.get((combo, regime))
            if not obs:
                continue
            medidas = medir_grupo(obs)
            taxa_obs: stats.Taxa = medidas["com_hipotese_validada"]
            previsao = prever(combo, regime, parametros, obs, semente=semente, repeticoes=repeticoes)
            linha: dict[str, Any] = {
                "combinacao": combo, "regime": regime,
                "medida": "poder" if regime == "P" else "falsa_validacao", "observada": taxa_obs,
            }
            if "motivo" in previsao:
                linha.update(classificacao="sem_previsao", motivo=previsao["motivo"])
            else:
                intervalo = stats.Taxa(0, 0, previsao["prevista"], previsao["baixo"], previsao["alto"], "simulacao")
                linha.update(
                    prevista=previsao["prevista"], baixo=previsao["baixo"], alto=previsao["alto"],
                    hipoteses_por_exploracao=previsao["hipoteses_por_exploracao"], parametros=parametros,
                    classificacao="compativel" if intervalo.contem(taxa_obs.valor) else "incompativel",
                )
            linhas.append(linha)
    return linhas


# ---------------------------------------------------------------------------
# Saídas
# ---------------------------------------------------------------------------


def _taxa_csv(t: stats.Taxa) -> dict[str, Any]:
    return {"k": t.k, "n": t.n, "taxa": t.valor, "baixo": t.baixo, "alto": t.alto}


def linhas_csv(expls: list[ExploracaoMedida]) -> list[dict[str, Any]]:
    """Uma linha por exploração e uma por hipótese (``nivel``)."""
    linhas: list[dict[str, Any]] = []
    for e in expls:
        base = {"combinacao": e.combinacao, "regime": e.regime, "repeticao": e.repeticao}
        linhas.append({
            "nivel": "exploracao", **base, "fim": e.fim, "censurada": e.censurada, "custo_usd": e.custo_usd,
            "chamadas": e.chamadas, "tokens": e.tokens, "hipoteses": len(e.hipoteses),
            "validadas": sum(1 for h in e.hipoteses if h.estado == VALIDADA),
            "refutadas": sum(1 for h in e.hipoteses if h.estado == REFUTADA), "nao_testadas": e.nao_testadas,
        })
        for h in e.hipoteses:
            linhas.append({
                "nivel": "hipotese", **base, "hipotese": h.id, "estado": h.estado, "veredito": h.veredito_sistema,
                "veredito_completa2": h.veredito_completa2, "veredito_atual": h.veredito_atual,
                "tentativas": h.n_tentativas, "variacoes": h.variacoes, "variacoes_uteis": h.variacoes_uteis,
                "tentativas_ate_limiar": h.tentativas_ate_limiar, "abordagem_plantada": h.plantada,
            })
    return linhas


def _pct(t: stats.Taxa) -> str:
    return t.rotulo


def relatorio(expls: list[ExploracaoMedida], comparacao: list[dict[str, Any]], manifesto: dict[str, Any]) -> str:
    """``relatorio.md`` (pt-BR): tabelas por regime, equivalência e comparação com a previsão."""
    grupos = agrupar(expls)
    eq = equivalencia(expls)
    censuradas = sum(1 for e in expls if e.censurada)
    partes = [
        "# Medição das explorações controladas",
        "",
        f"Commit `{manifesto['commit']}`, {manifesto['data_utc']}. {len(expls)} explorações, "
        f"{censuradas} censuradas (contadas à parte; ficam fora das taxas).",
        "",
        "## Taxas por regime e combinação (explorações não censuradas)",
        "",
    ]
    linhas = []
    for (combo, regime), g in grupos.items():
        m = medir_grupo(g)
        nome = {"P": "poder", "F": "poder (F restante)"}.get(regime, "falsa validação")
        linhas.append([
            combo, regime, f"{m['n_validas']}/{m['n_exploracoes']}", nome, _pct(m["com_hipotese_validada"]),
            _pct(m["refutacao_discordante"]), _pct(m["indecisao"]),
        ])
    partes += [output.md_table(
        ["Combinação", "Regime", "Válidas/total", "Medida", "Com hipótese validada", "Refutação discordante",
         "Indecisão"], linhas), ""]
    partes += ["## Hipóteses, variações e custo", ""]
    linhas = []
    for (combo, regime), g in grupos.items():
        m = medir_grupo(g)
        h, vu, vt, ta = m["hipoteses"], m["variacoes_uteis"], m["variacoes_total"], m["tentativas_ate_limiar"]
        linhas.append([
            combo, regime, f"{h[VALIDADA]}/{h[REFUTADA]}/{h[INDECISA]}", h["nao_testadas"],
            _triplo(vu), _triplo(vt), _triplo(ta), _fins(m["censuradas_por_fim"]),
            m["custo_por_validacao_usd"], m["chamadas_por_validacao"],
        ])
    partes += [output.md_table(
        ["Combinação", "Regime", "Validadas/refutadas/indecisas", "Não testadas", "Variações úteis (med; p10; p90)",
         "Variações (med; p10; p90)", "Tentativas até 0,3", "Censura por fim", "US$ por validação",
         "Chamadas por validação"],
        linhas), ""]
    partes += [
        "## Equivalência com o laboratório",
        "",
        f"{eq['hipoteses']} hipóteses reaplicadas; maior diferença entre o sistema e `{VARIANTE_REFERENCIA}`: "
        f"{eq['maior_diferenca_completa2']:.2e} (limite {TOL_EQUIVALENCIA:g}); maior diferença contra o veredito "
        "gravado "
        f"({eq['com_veredito_gravado']} hipóteses): {eq['maior_diferenca_gravado']:.2e} (arredondamento a 6 casas). "
        f"A variante `atual` (ADR 015) concluiria um estado diferente em {eq['estado_diverge_atual']} hipóteses.",
        "",
    ]
    linhas = []
    for (combo, regime), g in grupos.items():
        m = medir_grupo(g)
        linhas.append([combo, regime, _pct(m["validadas_completa2"]), _pct(m["validadas_atual"])])
    partes += [
        output.md_table(["Combinação", "Regime", "Com validada (completa2)", "Com validada (atual)"], linhas),
        "",
    ]
    partes += ["## Observado × previsto pela simulação", ""]
    linhas = []
    for c in comparacao:
        prev = "—" if c.get("prevista") is None else f"{c['prevista']:.3f} [{c['baixo']:.3f}; {c['alto']:.3f}]"
        linhas.append([c["combinacao"], c["regime"], c["medida"], _pct(c["observada"]), prev,
                       c["classificacao"] + (f" ({c['motivo']})" if c.get("motivo") else "")])
    partes += [output.md_table(
        ["Combinação", "Regime", "Medida", "Observada", "Prevista (exploração)", "Leitura"], linhas), ""]
    partes += [
        "## Leitura e limitações",
        "",
        "- \"Compatível\" quando a taxa observada cai no intervalo previsto; \"incompatível\" é relatado com o número, "
        "sem ajuste de nenhum parâmetro `VERDICT_*` (ADR 025 §4.3, passo 6).",
        "- A previsão usa os parâmetros estimados das explorações P e N da combinação (sigma, tau, probabilidades de "
        "variar e de falhar, tentativas por hipótese) e converte a taxa por hipótese em taxa por exploração com a "
        "mediana observada de hipóteses por exploração, supondo hipóteses independentes.",
        "- A simulação decide na primeira travessia de 0,3, com média constante por hipótese (sem evolução entre "
        "variações); o sistema decide pelo veredito ao fim da exploração e as hipóteses reais melhoram ao longo das "
        "variações. Uma incompatibilidade em P pode refletir essa diferença e não o veredito.",
        "- Com poucas explorações por célula, os intervalos são largos: a bateria confirma compatibilidade, "
        "não o teto de 2 %.",
        "",
    ]
    return "\n".join(partes)


def _fins(por_fim: dict[str, int]) -> str:
    return ", ".join(f"{fim}: {n}" for fim, n in por_fim.items()) or "—"


def _triplo(r: dict[str, Any]) -> str:
    if not r["n"]:
        return "—"
    return f"{r['mediana']:.1f}; {r['p10']:.1f}; {r['p90']:.1f}"


def medir(
    rodada: Path, *, saida: Path | None = None, semente: int = 20261019, repeticoes: int = 400,
    sobrescrever: bool = False, params: VerdictParams | None = None, comando: str = "medir",
) -> dict[str, Any]:
    """Mede a rodada e grava ``resultados.csv``, ``relatorio.md`` e ``manifesto.json`` em ``<rodada>/medicao``."""
    expls = carregar_rodada(rodada, params)
    out = output.prepare_output_dir(saida or rodada / "medicao", overwrite=sobrescrever)
    comparacao = comparar(agrupar(expls), semente=semente, repeticoes=repeticoes)
    entradas = [
        p for e in expls
        for p in (e.pasta / "exploracao.json", e.pasta / ARCHIVE_NAME, e.pasta / "verdade" / "verdade.json")
    ]
    manifesto = output.write_manifest(
        out, comando=comando,
        argumentos={"rodada": str(rodada), "semente": semente, "repeticoes_simulacao": repeticoes, "limiar": LIMIAR},
        variantes=[load_variantes()[VARIANTE_REFERENCIA].manifest(), current_variant().manifest()],
        entradas=entradas, sementes={"simulacao": semente},
    )
    output.write_csv(out / output.RESULTS, linhas_csv(expls))
    (out / output.REPORT).write_text(relatorio(expls, comparacao, manifesto), encoding="utf-8")
    return {"saida": out, "exploracoes": expls, "comparacao": comparacao}
