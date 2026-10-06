"""Researcher consultor nos modos autônomos (V18 — Spec `researcher-consult`, ADR 012 §8).

Reúne as constantes e os textos compartilhados entre a skill ``ask_researcher``, o núcleo de
consulta do orquestrador e o consultor (``agents/researcher/consult.py``).
"""

from __future__ import annotations

import re
import unicodedata

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


# Classificação determinística, por palavras-chave na PERGUNTA, das decisões reservadas. Roda além
# da autodeclaração (`decisao_reservada`) e da classificação do consultor, e é deliberadamente
# larga (falha fechada): um falso positivo só deixa a pergunta pendente para o pesquisador.
_VERBO = r"(aprov\w*|autoriz\w*|valid\w*|confirm\w*|homolog\w*)"
_ESCRITA = r"(escrev\w*|escrit\w*|grav\w*|write|alter\w*|modific\w*)"
_RESERVED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (nome, re.compile(padrao))
    for nome, padrao in (
        ("aprovar_oportunidade", rf"(\b{_VERBO}\b.{{0,60}}\boportunidade|\boportunidade.{{0,60}}\b{_VERBO}\b)"),
        ("confirmar_problema", rf"(\b{_VERBO}\b.{{0,60}}\bproblema\b|\bproblema\b.{{0,60}}\b{_VERBO}\b)"),
        (
            "aprovar_termo_vocabulario",
            r"(\b(aprov\w*|adicion\w*|inclu\w*|autoriz\w*|homolog\w*)\b.{0,60}\b(termo|vocabulario)\b"
            r"|\b(termo|vocabulario)\b.{0,60}\b(aprov\w*|homolog\w*)\b)",
        ),
        (
            "autorizar_escrita_instrumento",
            rf"(\binstrument\w*.{{0,80}}\b{_ESCRITA}|\b{_ESCRITA}.{{0,80}}\binstrument\w*)",
        ),
        (
            "ativar_modo_sem_limite",
            r"(\b(ativ\w*|habilit\w*|lig\w*|entr\w*|usar|use)\b.{0,60}(sem limite|ilimitad\w*|sem limites)"
            r"|\bmodo (sem|nenhum) limite)",
        ),
    )
)


def classify_reserved(pergunta: str) -> str | None:
    """Identifica, por palavras-chave, uma pergunta que pede decisão reservada ao pesquisador.

    Args:
        pergunta: Texto da pergunta do agente.

    Returns:
        O nome da decisão (um item de ``DECISOES_RESERVADAS``) ou ``None``.
    """
    texto = unicodedata.normalize("NFKD", pergunta.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    for nome, padrao in _RESERVED_PATTERNS:
        if padrao.search(texto):
            return nome
    return None
