"""Normalização de termos de vocabulário (compartilhada entre agentes e grafo).

Fonte única das regras de comparação de nomes de métricas e termos de domínio:
o Validator (``src.agents.validator_agent``) e o serviço de vocabulário
(``src.knowledge.vocabulary``) usam as mesmas funções, para que um nome
resolva ao mesmo termo canônico em qualquer ponto do pipeline.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


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


QUALIFIER_WORDS: dict[str, str] = {
    "test": "teste", "teste": "teste", "holdout": "teste", "heldout": "teste",
    "cv": "cv", "crossval": "cv", "kfold": "cv",
    "train": "treino", "training": "treino", "treino": "treino",
    "val": "validacao", "valid": "validacao", "validation": "validacao", "validacao": "validacao",
}
_CV_PHRASES = ("validacao cruzada", "cross validation", "cross val", "crossvalidation")


@dataclass(frozen=True)
class MetricName:
    """Nome de métrica separado do qualificador de conjunto (``test_accuracy`` -> base ``accuracy``, ``teste``)."""

    base: str  # forma normalizada sem qualificador
    qualifier: str  # "teste" | "cv" | "treino" | "validacao" | "" (sem qualificador)
    raw: str  # nome como escrito


def normalized_words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", _strip_accents(text).lower()) if w]


def split_metric_name(name: str) -> MetricName:
    """Separa o conjunto de avaliação do nome de uma métrica.

    O nome é dividido em palavras (``_``, ``-``, ``.``, espaço); se a primeira ou a última palavra está na lista
    fechada de qualificadores, só ela sai do nome base. Sufixos estatísticos (``mean``, ``std``) ficam no base:
    ``cv_accuracy_mean`` tem base ``accuracymean`` e qualificador ``cv``, nunca a acurácia de teste.
    """
    words = normalized_words(name)
    qualifier = ""
    if len(words) > 1:
        if words[0] in QUALIFIER_WORDS:
            qualifier, words = QUALIFIER_WORDS[words[0]], words[1:]
        elif words[-1] in QUALIFIER_WORDS:
            qualifier, words = QUALIFIER_WORDS[words[-1]], words[:-1]
    return MetricName(base="".join(words), qualifier=qualifier, raw=name)


def criterion_qualifier(text: str) -> str:
    """Conjunto citado explicitamente em um trecho de critério ("... validação cruzada ..."), ou ``""``.

    Usa a mesma tabela de ``split_metric_name``; "validação cruzada" vale ``cv`` (não ``validacao``).
    """
    plain = " ".join(normalized_words(text))
    if any(phrase in plain for phrase in _CV_PHRASES):
        return "cv"
    for word in plain.split():
        if word in QUALIFIER_WORDS:
            return QUALIFIER_WORDS[word]
    return ""


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
