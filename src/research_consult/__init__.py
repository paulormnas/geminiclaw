"""Researcher consultor nos modos autônomos (V18 — Spec `researcher-consult`, ADR 012 §8).

Reúne as constantes e os textos compartilhados entre a skill ``ask_researcher``, o núcleo de
consulta do orquestrador e o consultor (``agents/researcher/consult.py``).
"""

from __future__ import annotations

# Decisões que só o pesquisador humano toma; o consultor nunca as responde (design §5).
DECISOES_RESERVADAS: tuple[str, ...] = (
    "aprovar_oportunidade",
    "confirmar_problema",
    "aprovar_termo_vocabulario",
    "autorizar_escrita_instrumento",
    "ativar_modo_sem_limite",
)

# Valores de ``respondido_por`` em ``researcher_interactions``.
RESPONDIDO_PESQUISADOR = "pesquisador"
RESPONDIDO_RESEARCHER = "researcher"
RESPONDIDO_SUPOSICAO = "suposicao"
PENDENTE_PESQUISADOR = "pendente_pesquisador"

RESERVED_MESSAGE = (
    "[Decisão reservada ao pesquisador] Esta decisão não pode ser tomada pelo Researcher "
    "consultor; foi registrada como pendente para o pesquisador. Prossiga com a suposição "
    "documentada, sem executar a decisão, e registre isso em 'scientific_rationale'."
)


def assumption_text(mode: str, question: str, motivo: str | None = None) -> str:
    """Texto da suposição documentada devolvida ao agente quando não há consulta.

    Args:
        mode: Modo da sessão (``semi`` ou ``auto``).
        question: Pergunta feita pelo agente.
        motivo: ``motivo_fallback`` (por que o consultor não respondeu), se houver.

    Returns:
        A mensagem de suposição documentada.
    """
    suffix = f" (consultor não usado: {motivo})" if motivo else ""
    return (
        f"[Modo {mode} — suposição documentada, sem consulta ao pesquisador]{suffix} "
        f"Pergunta: {question} | Prosseguindo com a melhor suposição razoável a "
        "partir do contexto disponível; documente esta decisão em 'scientific_rationale'."
    )
