"""Vista do grafo para os candidatos estruturais no ciclo (ADR 026 §6; ``v18.9-cross-project-context`` design §4).

Lê os ``RegistroResultado`` de todos os projetos (visão local do pesquisador) e monta o ``GraphView`` de
:mod:`src.knowledge.structural_candidates`. Os candidatos do próprio projeto (composição e ramo pouco explorado) viram
sugestões ao Researcher (ver ``suggestions.build_candidates``); os de outro projeto (transferência) só viram
``Oportunidade`` com ``origem = "grafo"`` quando ``CROSS_PROJECT_CANDIDATES=true``, e nunca viram hipótese sem a
aprovação do pesquisador (ADR 013).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src import config
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.graph_views import sanitize_text
from src.knowledge.problem_similarity import problem_similarity
from src.knowledge.provenance import Actor
from src.knowledge.structural_candidates import (
    Candidate,
    Derivation,
    GraphView,
    ResultFact,
    approach_key,
    generate,
)
from src.logger import get_logger

logger = get_logger(__name__)

ACTOR = Actor(kind="orquestrador")
_PAGE = 200
# No ciclo não há corte temporal: o grafo inteiro até agora vale.
_NOW = "9999-12-31T23:59:59+00:00"
_MAX_TEXT = 200


@dataclass(frozen=True)
class StructuralContext:
    """A vista e os nomes originais das abordagens (a chave normalizada não serve para mostrar)."""

    view: GraphView
    names: dict[str, str]
    record_approach: dict[str, str]  # registro_id -> id do nó Abordagem


def _all_nodes(store: GraphStore, label: str) -> list[Node]:
    out: list[Node] = []
    after: str | None = None
    while True:
        page = store.list_nodes(label, after_id=after, limit=_PAGE)
        if not page:
            return out
        out.extend(page)
        after = page[-1].id


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def build_context(store: GraphStore, index: Any, problema_id: str) -> StructuralContext:
    """Registros (menos os ``retido``), derivações ``VARIANTE_DE`` e a semelhança do Problema com os demais.

    Raises:
        ValueError: Problema inexistente.
    """
    origin = store.get_node(problema_id)
    if origin is None:
        raise ValueError(f"Problema '{problema_id}' não encontrado.")
    facts: list[ResultFact] = []
    names: dict[str, str] = {}
    record_approach: dict[str, str] = {}
    problems: dict[str, Node] = {}
    for record in _all_nodes(store, "RegistroResultado"):
        if record.properties.get("qualificacao") == "retido":
            continue
        sub = store.neighbors(record.id, ["REGISTRA", "SOBRE"], direction="out", depth=1)
        by_id = {n.id: n for n in sub.nodes}
        approach = next((by_id[e.dst_id] for e in sub.edges if e.rel_type == "REGISTRA" and e.dst_id in by_id), None)
        problem = next((by_id[e.dst_id] for e in sub.edges if e.rel_type == "SOBRE" and e.dst_id in by_id), None)
        if approach is None or problem is None:
            continue
        key = approach_key(str(approach.properties.get("nome", "")))
        names.setdefault(key, str(approach.properties.get("nome", "")))
        record_approach[record.id] = approach.id
        problems[problem.id] = problem
        facts.append(
            ResultFact(
                registro_id=record.id, problema_id=problem.id, abordagem_key=key,
                criado_em=str(record.properties.get("atualizado_em") or record.properties.get("criado_em") or ""),
                delta_base=_num(record.properties.get("delta_base")),
                delta_pai=_num(record.properties.get("delta_pai")),
                atingiu_alvo=bool(record.properties.get("atingiu_alvo")),
                n_replicas=max(int(record.properties.get("n_replicas_independentes") or 0), 1),
            )
        )
    derivations: list[Derivation] = []
    project = origin.properties.get("projeto_id")
    for approach in store.find_nodes("Abordagem", {"projeto_id": project}, limit=1000):
        sub = store.neighbors(approach.id, ["VARIANTE_DE"], direction="out", depth=1)
        by_id = {n.id: n for n in sub.nodes}
        for edge in sub.edges:
            if edge.rel_type == "VARIANTE_DE" and edge.src_id == approach.id and edge.dst_id in by_id:
                derivations.append(
                    Derivation(
                        approach_key(str(approach.properties.get("nome", ""))),
                        approach_key(str(by_id[edge.dst_id].properties.get("nome", ""))),
                        str(edge.properties.get("criado_em") or approach.properties.get("criado_em") or ""),
                    )
                )
    cosines = {
        h.node_id: h.score
        for h in index.similar(node_id=problema_id, labels=["Problema"], min_score=0.0, limit=100)
    }
    sims: dict[str, float] = {}
    for pid, problem in problems.items():
        if pid == problema_id or pid not in cosines:
            continue
        sims[pid] = problem_similarity(
            cosines[pid],
            origin.properties.get("caracteristicas_dados"),
            problem.properties.get("caracteristicas_dados"),
        )

    def similarity(a: str, b: str) -> float:
        other = b if a == problema_id else a
        return sims.get(other, 0.0)

    view = GraphView(facts=tuple(facts), similarity=similarity, derivations=tuple(derivations))
    return StructuralContext(view, names, record_approach)


def _name(ctx: StructuralContext, key: str) -> str:
    return sanitize_text(ctx.names.get(key, key), _MAX_TEXT)


def own_project_candidates(ctx: StructuralContext, problema_id: str) -> list[Candidate]:
    """Candidatos do próprio projeto: composição e ramo pouco explorado (usam só registros do Problema)."""
    return [c for c in generate(ctx.view, problema_id, t=_NOW) if c.tipo in ("composicao", "pouco_explorado")]


def describe(ctx: StructuralContext, cand: Candidate) -> str:
    """Texto da sugestão (modelo fixo; nomes saneados)."""
    if cand.tipo == "composicao":
        a, _, b = cand.abordagem_id.partition("+")
        return f"Combinar as abordagens '{_name(ctx, a)}' e '{_name(ctx, b)}', que melhoraram o resultado do pai."
    if cand.tipo == "pouco_explorado":
        return (
            f"Explorar mais variações de '{_name(ctx, cand.abordagem_id)}', que melhorou a linha de base e tem "
            "poucos descendentes."
        )
    return f"Testar '{_name(ctx, cand.abordagem_id)}', que funcionou em problema semelhante."


def publish_cross_candidates(store: GraphStore, index: Any, problema_id: str, *, limit: int | None = None) -> list[str]:
    """Cria ``Oportunidade`` (``origem = "grafo"``, ``documentada``) para os candidatos de transferência.

    Só age com ``CROSS_PROJECT_CANDIDATES=true``. Nunca cria hipótese. Não repete: uma oportunidade do projeto com o
    mesmo ``registro_origem_id`` (em qualquer status) impede outra.

    Returns:
        Ids das oportunidades criadas.
    """
    if not config.CROSS_PROJECT_CANDIDATES:
        return []
    problem = store.get_node(problema_id)
    if problem is None:
        return []
    project = str(problem.properties.get("projeto_id") or "")
    ctx = build_context(store, index, problema_id)
    existing = {
        str(o.properties.get("registro_origem_id"))
        for o in store.find_nodes("Oportunidade", {"projeto_id": project, "origem": "grafo"}, limit=1000)
    }
    created: list[str] = []
    maximum = config.CURATOR_MAX_SUGGESTIONS if limit is None else limit
    for cand in generate(ctx.view, problema_id, t=_NOW):
        if cand.tipo != "transferencia" or len(created) >= maximum:
            continue
        origin = max(cand.origem_ids)
        if origin in existing:
            continue
        sim = cand.atributos["semelhanca"]
        node_id = store.create_node(
            "Oportunidade",
            {
                "enunciado": f"{describe(ctx, cand)}"[:500],
                "justificativa": (
                    f"Candidato estrutural: semelhança {sim:.2f} com o problema de origem, ganho sobre a linha de "
                    f"base {cand.atributos['margem']:.3g}, {int(cand.atributos['replicas'])} réplica(s). "
                    "Experiência de outro problema é hipótese a testar."
                ),
                "status": "documentada",
                "origem": "grafo",
                "registro_origem_id": origin,
                "projeto_id": project,
                "sessao_id": "structural-candidates",
            },
            actor=ACTOR,
        )
        store.create_edge(node_id, "PARA", problema_id, {"origem": "derivado"}, actor=ACTOR)
        approach_id = ctx.record_approach.get(origin)
        if approach_id:
            store.create_edge(node_id, "SUGERE", approach_id, {"origem": "derivado"}, actor=ACTOR)
        created.append(node_id)
        existing.add(origin)
    return created
