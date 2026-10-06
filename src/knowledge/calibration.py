"""Calibração dos limiares de similaridade pelo uso (ADR 015 §6 item 7, design §7).

O sistema apenas **sugere** ajustes a partir da taxa de confirmação da fila; o
ajuste em si é uma mudança de configuração feita pelo pesquisador. Nada aqui
altera ``src.config`` nem variáveis de ambiente.
"""

from __future__ import annotations

from src import config
from src.knowledge.similarity_queue import FAIXA_BAIXA, FAIXA_DUPLICATA, FAIXA_RELACIONADO, BandRate

LOW_RATE = 0.10
HIGH_RATE = 0.60

# Variável de configuração do limite inferior de cada faixa.
_LOWER_BOUND_VAR = {
    FAIXA_BAIXA: "SIM_RELATED_MIN_CROSS",
    FAIXA_RELACIONADO: "SIM_RELATED_MIN_SAME_DOMAIN",
    FAIXA_DUPLICATA: "SIM_DUPLICATE_MIN",
}
_BAND_LABEL = {
    FAIXA_BAIXA: "faixa baixa (0,60–0,70, entre domínios)",
    FAIXA_RELACIONADO: "faixa relacionado (0,70–0,90)",
    FAIXA_DUPLICATA: "faixa duplicata (>= 0,90)",
}


def suggest_adjustments(rates: list[BandRate], min_samples: int | None = None) -> list[str]:
    """Sugere ajustes de limiar a partir das taxas de confirmação por faixa.

    Taxa < 10% -> a faixa está frouxa demais: subir o limite inferior.
    Taxa > 60% -> provavelmente há oportunidades sendo perdidas: descer o limite inferior.

    Args:
        rates: Taxas por tipo e faixa (``SimilarityQueue.confirmation_rate``).
        min_samples: Pares revisados mínimos na faixa para sugerir (padrão
            ``SIM_CALIBRATION_MIN_SAMPLES``); abaixo disso a amostra é considerada insuficiente.

    Returns:
        Frases de sugestão (lista vazia se nenhuma taxa está fora da zona saudável).
        Nenhuma configuração é alterada.
    """
    minimum = config.SIM_CALIBRATION_MIN_SAMPLES if min_samples is None else min_samples
    suggestions = []
    for rate in rates:
        taxa = rate.taxa
        if taxa is None or rate.avaliados < minimum:
            continue
        var = _LOWER_BOUND_VAR[rate.faixa]
        label = _BAND_LABEL[rate.faixa]
        if taxa < LOW_RATE:
            suggestions.append(
                f"{label}: taxa de confirmação {taxa:.0%} ({rate.confirmados}/{rate.avaliados}) < 10% — "
                f"sugestão: subir o limite inferior ({var})."
            )
        elif taxa > HIGH_RATE:
            suggestions.append(
                f"{label}: taxa de confirmação {taxa:.0%} ({rate.confirmados}/{rate.avaliados}) > 60% — "
                f"sugestão: descer o limite inferior ({var})."
            )
    return suggestions
