"""Candidatos estruturais a partir dos registros de resultado (ADR 026 §6; ``v18.9-memory-evaluation`` design §2).

Módulo puro (sem banco, rede nem LLM). A entrada é uma vista do grafo (``GraphView``) com os registros de resultado e
as derivações entre abordagens; a saída é a lista de ``Candidate`` de um Problema num instante ``t``. Nenhum fato com
``criado_em > t`` influencia a saída (o replay depende disso). Não confundir com ``candidates.py``, que gera os pares
da fila de similaridade.

Uma abordagem é identificada por ``abordagem_key``: a mesma chave em Problemas de projetos diferentes designa a mesma
abordagem (os nós ``Abordagem`` são por projeto; quem monta a vista escolhe a chave).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from src import config

CandidateType = Literal["transferencia", "composicao", "pouco_explorado"]
CANDIDATE_TYPES: tuple[CandidateType, ...] = ("transferencia", "composicao", "pouco_explorado")
_MAX_REPLICAS_WEIGHT = 3


@dataclass(frozen=True)
class ResultFact:
    """Fatos de um registro de resultado de uma abordagem num Problema.

    Attributes:
        registro_id: Identificador do registro (ou do resultado de que ele vem).
        problema_id: Problema em que a abordagem foi aplicada.
        abordagem_key: Chave da abordagem, comum entre projetos.
        criado_em: Instante ISO 8601 do fato.
        delta_base: Melhora sobre a linha de base (``None`` sem referência).
        delta_pai: Melhora sobre o registro de origem (``None`` sem origem).
        atingiu_alvo: O alvo do critério foi atingido.
        n_replicas: Réplicas independentes que sustentam o fato.
    """

    registro_id: str
    problema_id: str
    abordagem_key: str
    criado_em: str
    delta_base: float | None = None
    delta_pai: float | None = None
    atingiu_alvo: bool = False
    n_replicas: int = 1


@dataclass(frozen=True)
class Derivation:
    """A abordagem ``filha`` deriva de ``pai`` (variante) a partir do instante ``criado_em``."""

    filha: str
    pai: str
    criado_em: str


@dataclass(frozen=True)
class GraphView:
    """Vista do grafo para gerar candidatos.

    Attributes:
        facts: Registros de resultado de todos os Problemas (qualquer instante; ``generate`` corta em ``t``).
        derivations: Derivações entre abordagens.
        combinations: Pares de abordagens já combinados (``frozenset`` de duas chaves).
        similarity: Semelhança em [0, 1] entre dois Problemas (simétrica).
    """

    facts: tuple[ResultFact, ...]
    similarity: Callable[[str, str], float]
    derivations: tuple[Derivation, ...] = ()
    combinations: frozenset[frozenset[str]] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Candidate:
    """Próximo passo sugerido pela estrutura do grafo.

    Attributes:
        tipo: ``transferencia``, ``composicao`` ou ``pouco_explorado``.
        problema_id: Problema em que o passo seria dado.
        abordagem_id: Chave da abordagem (``a+b`` para composição, com as chaves em ordem).
        origem_ids: Registros em que o candidato se apoia.
        atributos: ``semelhanca``, ``margem``, ``replicas``, ``grau_abordagem``, ``vizinhos_comuns``, ``descendentes``.
    """

    tipo: CandidateType
    problema_id: str
    abordagem_id: str
    origem_ids: tuple[str, ...]
    atributos: Mapping[str, float]


def _positive(fact: ResultFact) -> bool:
    return fact.atingiu_alvo or (fact.delta_base is not None and fact.delta_base > 0)


def descendants(derivations: tuple[Derivation, ...], key: str) -> int:
    """Abordagens que descendem de ``key`` (transitivamente)."""
    children: dict[str, list[str]] = {}
    for d in derivations:
        children.setdefault(d.pai, []).append(d.filha)
    seen: set[str] = set()
    stack = [key]
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in seen and child != key:
                seen.add(child)
                stack.append(child)
    return len(seen)


def default_score(attrs: Mapping[str, float]) -> float:
    """Ordenação padrão: ``semelhanca × (1 + margem) × min(replicas, 3) / (1 + log(1 + descendentes))``."""
    return (
        attrs["semelhanca"]
        * (1.0 + attrs["margem"])
        * min(attrs["replicas"], _MAX_REPLICAS_WEIGHT)
        / (1.0 + math.log(1.0 + attrs["descendentes"]))
    )


def similarity_score(attrs: Mapping[str, float]) -> float:
    """Linha de base: só a semelhança entre os Problemas."""
    return attrs["semelhanca"]


def degree_score(attrs: Mapping[str, float]) -> float:
    """Linha de base: só o grau da abordagem (*preferential attachment*)."""
    return attrs["grau_abordagem"]


ORDERINGS: dict[str, Callable[[Mapping[str, float]], float]] = {
    "padrao": default_score,
    "semelhanca": similarity_score,
    "grau_abordagem": degree_score,
}


def _problems_with(facts: list[ResultFact], key: str) -> set[str]:
    return {f.problema_id for f in facts if f.abordagem_key == key}


def _keys_in(facts: list[ResultFact], problema_id: str) -> set[str]:
    return {f.abordagem_key for f in facts if f.problema_id == problema_id}


def generate(
    view: GraphView,
    problema_id: str,
    *,
    t: str,
    min_similarity: float | None = None,
    max_descendants: int | None = None,
) -> list[Candidate]:
    """Candidatos do Problema com o grafo até ``t`` (inclusive), ordenados pela ordenação padrão (maior primeiro).

    Args:
        view: Vista do grafo.
        problema_id: Problema para o qual gerar.
        t: Instante ISO 8601 de corte; fatos e derivações posteriores são ignorados.
        min_similarity: Semelhança mínima da transferência (padrão ``CANDIDATE_MIN_SIMILARITY``).
        max_descendants: Teto de descendentes do ``pouco_explorado`` (padrão ``CANDIDATE_MAX_DESCENDANTS``).
    """
    min_sim = config.CANDIDATE_MIN_SIMILARITY if min_similarity is None else min_similarity
    max_desc = config.CANDIDATE_MAX_DESCENDANTS if max_descendants is None else max_descendants
    facts = [f for f in view.facts if f.criado_em <= t]
    derivations = tuple(d for d in view.derivations if d.criado_em <= t)
    own = _keys_in(facts, problema_id)
    found: list[Candidate] = []

    sources: dict[str, list[tuple[ResultFact, float]]] = {}
    for fact in facts:
        if fact.problema_id == problema_id or fact.abordagem_key in own or not _positive(fact):
            continue
        sim = view.similarity(problema_id, fact.problema_id)
        if sim >= min_sim:
            sources.setdefault(fact.abordagem_key, []).append((fact, sim))
    for key, origins in sources.items():
        best_fact, best_sim = max(origins, key=lambda o: (o[1], o[0].registro_id))
        shared = len(own & _keys_in(facts, best_fact.problema_id))
        found.append(
            Candidate(
                "transferencia",
                problema_id,
                key,
                tuple(sorted(f.registro_id for f, _ in origins)),
                {
                    "semelhanca": best_sim,
                    "margem": max(max(f.delta_base or 0.0, 0.0) for f, _ in origins),
                    "replicas": float(max(f.n_replicas for f, _ in origins)),
                    "grau_abordagem": float(len(_problems_with(facts, key))),
                    "vizinhos_comuns": float(shared),
                    "descendentes": float(descendants(derivations, key)),
                },
            )
        )

    parent_of = {d.filha: d.pai for d in derivations}
    gains = {f.abordagem_key: f for f in facts if f.problema_id == problema_id and (f.delta_pai or 0.0) > 0}
    by_parent: dict[str, list[str]] = {}
    for child in gains:
        if child in parent_of:
            by_parent.setdefault(parent_of[child], []).append(child)
    for children in by_parent.values():
        ordered = sorted(children)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                if frozenset((a, b)) in view.combinations:
                    continue
                fa, fb = gains[a], gains[b]
                found.append(
                    Candidate(
                        "composicao",
                        problema_id,
                        f"{a}+{b}",
                        (fa.registro_id, fb.registro_id),
                        {
                            "semelhanca": 1.0,
                            "margem": max(max(fa.delta_base or 0.0, 0.0), max(fb.delta_base or 0.0, 0.0)),
                            "replicas": float(min(fa.n_replicas, fb.n_replicas)),
                            "grau_abordagem": float(
                                len(_problems_with(facts, a)) + len(_problems_with(facts, b))
                            ),
                            "vizinhos_comuns": 0.0,
                            "descendentes": float(max(descendants(derivations, a), descendants(derivations, b))),
                        },
                    )
                )

    for fact in facts:
        if fact.problema_id != problema_id or (fact.delta_base or 0.0) <= 0:
            continue
        n_desc = descendants(derivations, fact.abordagem_key)
        if n_desc <= max_desc:
            found.append(
                Candidate(
                    "pouco_explorado",
                    problema_id,
                    fact.abordagem_key,
                    (fact.registro_id,),
                    {
                        "semelhanca": 1.0,
                        "margem": fact.delta_base or 0.0,
                        "replicas": float(fact.n_replicas),
                        "grau_abordagem": float(len(_problems_with(facts, fact.abordagem_key))),
                        "vizinhos_comuns": 0.0,
                        "descendentes": float(n_desc),
                    },
                )
            )
    return sorted(found, key=lambda c: (-default_score(c.atributos), c.tipo, c.abordagem_id))
