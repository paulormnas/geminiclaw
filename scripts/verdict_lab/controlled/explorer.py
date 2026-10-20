"""Laço da exploração: a cadeia de sessões até um fim natural ou o teto de gasto (design §4).

Uma exploração é (combinação, regime, repetição). O laço não conhece processos nem banco: fala com um :class:`Backend`
(iniciar, retomar), que nos testes é simulado e na execução real é :mod:`scripts.verdict_lab.controlled.runner`. Isso
mantém a política de parada (a parte que decide o que entra nas taxas) testável sem LLM.

Fim da exploração (``fim``):

- ``natural``: ``solucao_encontrada``, ``sem_caminhos_promissores`` ou ``saturacao``; nunca se retoma depois deles;
- ``falha``: qualquer outro ``motivo_parada`` (ou nenhum, ou o segmento estourou o prazo);
- ``interrompida_pelo_orcamento``: custo, sessões ou minutos da cadeia atingiram o teto; **censurada**;
- ``sem_progresso``: duas sessões seguidas sem experimento novo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

FIM_NATURAL = "natural"
FIM_FALHA = "falha"
FIM_ORCAMENTO = "interrompida_pelo_orcamento"
FIM_SEM_PROGRESSO = "sem_progresso"

MOTIVOS_NATURAIS = frozenset({"solucao_encontrada", "sem_caminhos_promissores", "saturacao"})
MOTIVOS_RETOMAVEIS = frozenset({"limite_tokens", "limite_tempo", "limite_custo", "limite_cota_provedor"})
MOTIVO_SEM_MOTIVO = "sem_motivo_parada"
MOTIVO_PRAZO_DO_SEGMENTO = "prazo_do_segmento"
SESSOES_SEM_PROGRESSO = 2


@dataclass(frozen=True)
class Teto:
    """Teto de uma exploração (design §5): o orquestrador o impõe fora do agente."""

    usd: float
    sessoes: int
    minutos: float

    def __post_init__(self) -> None:
        if self.usd <= 0 or self.sessoes < 1 or self.minutos <= 0:
            raise ValueError(f"Teto inválido (usd={self.usd}, sessoes={self.sessoes}, minutos={self.minutos}).")


@dataclass(frozen=True)
class Segmento:
    """O que uma sessão (um segmento da cadeia) devolve ao laço.

    Attributes:
        session_id: Identificador da sessão (nome da pasta de saída).
        motivo_parada: ``motivo_parada`` gravado (``None`` se a sessão não chegou a gravar).
        minutos: Tempo de relógio do segmento.
        prazo_estourado: O subprocesso foi encerrado por tempo.
        custo_usd: Custo estimado da sessão.
        tokens: Total de tokens da sessão.
        chamadas: Chamadas de LLM da sessão.
        custo_por_provedor: US$ por provedor.
        uso_por_agente: Chamadas, tokens e US$ por agente (papel).
        experimentos_total: Experimentos do projeto ao fim do segmento (acumulado da cadeia).
    """

    session_id: str
    motivo_parada: str | None
    minutos: float
    prazo_estourado: bool = False
    custo_usd: float = 0.0
    tokens: int = 0
    chamadas: int = 0
    custo_por_provedor: dict[str, float] = field(default_factory=dict)
    uso_por_agente: dict[str, dict[str, float]] = field(default_factory=dict)
    experimentos_total: int = 0


class Backend(Protocol):
    """Quem cria e retoma as sessões da exploração."""

    def iniciar(self) -> Segmento: ...

    def retomar(self, session_id: str) -> Segmento: ...

    def estado(self) -> dict[str, Any]:
        """Totais do projeto no grafo (experimentos, resultados, hipóteses), para o ``exploracao.json``."""
        ...


def _sessao(seg: Segmento, novos: int) -> dict[str, Any]:
    return {
        "session_id": seg.session_id,
        "motivo_parada": seg.motivo_parada,
        "minutos": round(seg.minutos, 2),
        "custo_usd": round(seg.custo_usd, 6),
        "tokens": seg.tokens,
        "chamadas": seg.chamadas,
        "custo_por_provedor": {k: round(v, 6) for k, v in seg.custo_por_provedor.items()},
        "uso_por_agente": seg.uso_por_agente,
        "experimentos_novos": novos,
    }


def explorar(backend: Backend, teto: Teto, *, identidade: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa a exploração e devolve o conteúdo do ``exploracao.json`` (design §4.2 e §4.3).

    Args:
        backend: Cria e retoma as sessões.
        teto: Teto de custo, sessões e minutos da cadeia.
        identidade: Campos de identificação copiados para o resultado (combinação, regime, repetição, semente...).
    """
    sessoes: list[dict[str, Any]] = []
    custo = minutos = 0.0
    por_provedor: dict[str, float] = {}
    experimentos_antes = 0
    sem_progresso = 0
    fim = motivo_final = ""
    segmento = backend.iniciar()
    while True:
        novos = max(segmento.experimentos_total - experimentos_antes, 0)
        experimentos_antes = max(experimentos_antes, segmento.experimentos_total)
        sessoes.append(_sessao(segmento, novos))
        custo += segmento.custo_usd
        minutos += segmento.minutos
        for provedor, valor in segmento.custo_por_provedor.items():
            por_provedor[provedor] = por_provedor.get(provedor, 0.0) + valor
        motivo = segmento.motivo_parada
        if segmento.prazo_estourado:
            fim, motivo_final = FIM_FALHA, MOTIVO_PRAZO_DO_SEGMENTO
        elif motivo in MOTIVOS_NATURAIS:
            fim, motivo_final = FIM_NATURAL, str(motivo)
        elif motivo in MOTIVOS_RETOMAVEIS:
            sem_progresso = sem_progresso + 1 if novos == 0 else 0
            motivo_final = str(motivo)
            if sem_progresso >= SESSOES_SEM_PROGRESSO:
                fim = FIM_SEM_PROGRESSO
            elif custo >= teto.usd or len(sessoes) >= teto.sessoes or minutos >= teto.minutos:
                fim = FIM_ORCAMENTO
        else:
            fim, motivo_final = FIM_FALHA, motivo or MOTIVO_SEM_MOTIVO
        if fim:
            break
        segmento = backend.retomar(segmento.session_id)
    estado = backend.estado()
    return {
        "versao": 1,
        **(identidade or {}),
        "fim": fim,
        "motivo_final": motivo_final,
        "censurada": fim in (FIM_ORCAMENTO, FIM_SEM_PROGRESSO, FIM_FALHA),
        "sessoes": sessoes,
        "n_sessoes": len(sessoes),
        "custo_total_usd": round(custo, 6),
        "custo_por_provedor": {k: round(v, 6) for k, v in sorted(por_provedor.items())},
        "tokens_total": sum(s["tokens"] for s in sessoes),
        "chamadas_total": sum(s["chamadas"] for s in sessoes),
        "minutos_total": round(minutos, 2),
        "teto": {"usd": teto.usd, "sessoes": teto.sessoes, "minutos": teto.minutos},
        "experimentos": experimentos_antes,
        "estado_grafo": estado,
    }
