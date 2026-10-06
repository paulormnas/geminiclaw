"""Normalização de termos de vocabulário (compartilhada entre agentes e grafo).

Fonte única das regras de comparação de nomes de métricas e termos de domínio:
o Validator (``src.agents.validator_agent``) e o serviço de vocabulário
(``src.knowledge.vocabulary``) usam as mesmas funções, para que um nome
resolva ao mesmo termo canônico em qualquer ponto do pipeline.
"""

from __future__ import annotations

import re
import unicodedata


def _strip_accents(text: str) -> str:
    """Remove acentos e decompõe formas de compatibilidade (``r²`` vira ``r2``)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def normalize_metric_name(name: str) -> str:
    """Normaliza um nome de métrica para comparação.

    Remove acentos, passa para minúsculas e elimina qualquer separador, de modo
    que ``"F1-Score"``, ``"f1_score"`` e ``"f1 score"`` coincidam.

    Args:
        name: Nome de métrica em texto livre.

    Returns:
        Forma normalizada, apenas ``[a-z0-9]``.
    """
    return re.sub(r"[^a-z0-9]+", "", _strip_accents(name).lower())


def normalize_domain_term(term: str) -> str:
    """Normaliza um termo de domínio para comparação.

    Minúsculas, sem acentos, e qualquer sequência de espaços, hífens ou
    pontuação vira um único ``_``.

    Args:
        term: Termo de domínio em texto livre.

    Returns:
        Forma normalizada (ex.: ``"Química Orgânica"`` -> ``"quimica_organica"``).
    """
    return re.sub(r"[^a-z0-9]+", "_", _strip_accents(term).lower()).strip("_")


def clean_free_text(text: str) -> str:
    """Neutraliza texto livre vindo de agente: sem controles nem quebras de linha.

    Caracteres de controle e de formatação Unicode (``Cc``, ``Cf``) e separadores de linha ou
    parágrafo (``Zl``, ``Zp``) viram espaço; sequências de espaços colapsam em um só. Evita
    que o texto forje linhas de campo (``Caminho:``) ou quebre a saída de uma ferramenta.

    Args:
        text: Texto em formato livre.

    Returns:
        Texto em uma linha, sem espaços nas pontas.
    """
    spaced = "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c for c in text)
    return " ".join(spaced.split())
