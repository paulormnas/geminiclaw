"""Vocabulário controlado de domínios e métricas (ADR 015 §4 e §8).

Responsabilidades:

    - **Carga inicial** idempotente (``seed_vocabulary``): domínios a partir da
      Tabela de Áreas do Conhecimento do CNPq (``data/vocabulary/cnpq_areas.csv``)
      e métricas a partir de ``data/vocabulary/metrics.yaml``.
    - **Resolução** de termos livres (``resolve_domain`` / ``resolve_metric``):
      nome exato -> sinônimo -> similaridade semântica -> candidato.
    - **Decisão do pesquisador** sobre candidatos (``approve_term``,
      ``reject_term``, ``map_term``, ``list_pending``): operações tipadas e
      determinísticas, sem LLM e sem Cypher livre. Nada é apagado.

Nós de vocabulário usam ``projeto_id="__global__"`` e
``visibilidade="compartilhavel"``: são comuns a todos os projetos.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src import config
from src.knowledge import schema
from src.knowledge.domain_search import DomainSearch
from src.knowledge.errors import GraphStoreError
from src.knowledge.graph_store import Edge, GraphStore, Node
from src.knowledge.normalization import clean_free_text, normalize_domain_term, normalize_metric_name
from src.knowledge.provenance import Actor
from src.logger import get_logger

logger = get_logger(__name__)

GLOBAL_PROJECT_ID = "__global__"
DEFAULT_VOCABULARY_DIR = Path(__file__).resolve().parents[2] / "data" / "vocabulary"
CNPQ_FILENAME = "cnpq_areas.csv"
METRICS_FILENAME = "metrics.yaml"

_CNPQ_COLUMNS = ("codigo_cnpq", "termo", "nivel", "codigo_pai")
_LEVELS = schema.NODE_SCHEMAS["Dominio"].properties["nivel"].enum or ()
_SCAN_LIMIT = 1_000_000

# (rótulo, termo livre) -> [(node_id, similaridade)], ordenado por similaridade decrescente.
SemanticSearch = Callable[[str, str], list[tuple[str, float]]]


class VocabularyError(GraphStoreError):
    """Erro de vocabulário controlado (carga, resolução ou decisão)."""


class VocabularySourceMissingError(VocabularyError):
    """Arquivo-fonte do vocabulário ausente (ex.: tabela oficial do CNPq)."""


@dataclass
class Resolution:
    """Resultado da resolução de um termo livre.

    Attributes:
        node_id: Termo canônico encontrado ou candidato criado.
        status: ``"exato"``, ``"sinonimo"``, ``"semantico"`` ou ``"candidato_criado"``.
        alternativas: Pares ``(node_id, similaridade)`` para revisão do pesquisador.
    """

    node_id: str | None
    status: str
    alternativas: list[tuple[str, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Carregadores
# ---------------------------------------------------------------------------


def load_cnpq_table(path: Path | None = None) -> list[dict[str, str]]:
    """Lê e valida a Tabela de Áreas do Conhecimento do CNPq.

    Args:
        path: Caminho do CSV; padrão ``data/vocabulary/cnpq_areas.csv``.

    Returns:
        Linhas validadas (``codigo_cnpq``, ``termo``, ``nivel``, ``codigo_pai``).

    Raises:
        VocabularySourceMissingError: Se o arquivo não existe. A tabela deve vir da fonte
            oficial do CNPq (ver ``data/vocabulary/README.md``); nunca é gerada pelo código.
        VocabularyError: Se o arquivo está malformado.
    """
    csv_path = path or DEFAULT_VOCABULARY_DIR / CNPQ_FILENAME
    if not csv_path.is_file():
        raise VocabularySourceMissingError(
            f"Tabela de Áreas do Conhecimento do CNPq não encontrada em '{csv_path}'. "
            "Obtenha o arquivo da fonte oficial do CNPq, salve-o nesse caminho com as colunas "
            f"{', '.join(_CNPQ_COLUMNS)} e registre fonte e versão em data/vocabulary/README.md. "
            "A tabela não pode ser reconstruída de memória."
        )
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != _CNPQ_COLUMNS:
            raise VocabularyError(
                f"Cabeçalho inválido em '{csv_path}': esperado {list(_CNPQ_COLUMNS)}, "
                f"encontrado {reader.fieldnames}."
            )
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]

    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):
        if not row["codigo_cnpq"] or not row["termo"]:
            raise VocabularyError(f"{csv_path}:{line}: 'codigo_cnpq' e 'termo' são obrigatórios.")
        if row["nivel"] not in _LEVELS:
            raise VocabularyError(f"{csv_path}:{line}: nivel '{row['nivel']}' inválido; use {list(_LEVELS)}.")
        if row["codigo_cnpq"] in seen:
            raise VocabularyError(f"{csv_path}:{line}: codigo_cnpq '{row['codigo_cnpq']}' duplicado.")
        seen.add(row["codigo_cnpq"])
    for line, row in enumerate(rows, start=2):
        if row["codigo_pai"] and row["codigo_pai"] not in seen:
            raise VocabularyError(
                f"{csv_path}:{line}: codigo_pai '{row['codigo_pai']}' não existe na tabela."
            )
    return rows


def load_metrics_catalog(path: Path | None = None) -> list[dict[str, Any]]:
    """Lê e valida o catálogo inicial de métricas (``metrics.yaml``).

    Args:
        path: Caminho do YAML; padrão ``data/vocabulary/metrics.yaml``.

    Returns:
        Lista de métricas (``nome``, ``sinonimos``, ``sentido``, ``faixa``, ``familia``).

    Raises:
        VocabularySourceMissingError: Se o arquivo não existe.
        VocabularyError: Se o conteúdo é inválido.
    """
    yaml_path = path or DEFAULT_VOCABULARY_DIR / METRICS_FILENAME
    if not yaml_path.is_file():
        raise VocabularySourceMissingError(f"Catálogo de métricas não encontrado em '{yaml_path}'.")
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    metrics = data.get("metricas")
    if not isinstance(metrics, list) or not metrics:
        raise VocabularyError(f"'{yaml_path}' deve conter a lista não vazia 'metricas'.")
    sentidos = schema.NODE_SCHEMAS["Metrica"].properties["sentido"].enum or ()
    names: set[str] = set()
    for item in metrics:
        nome = item.get("nome") if isinstance(item, dict) else None
        if not nome:
            raise VocabularyError(f"Métrica sem 'nome' em '{yaml_path}': {item!r}.")
        if item.get("sentido") not in sentidos:
            raise VocabularyError(f"Métrica '{nome}': sentido deve ser um de {list(sentidos)}.")
        if nome in names:
            raise VocabularyError(f"Métrica '{nome}' duplicada em '{yaml_path}'.")
        names.add(nome)
    return metrics


# ---------------------------------------------------------------------------
# Auxiliares de grafo
# ---------------------------------------------------------------------------


def _all_nodes(store: GraphStore, label: str) -> list[Node]:
    """Todos os nós de um rótulo (o vocabulário é pequeno o bastante para varredura)."""
    return store.find_nodes(label, {}, limit=_SCAN_LIMIT)


def _name_key(label: str) -> str:
    return "termo" if label == "Dominio" else "nome"


def _normalizer(label: str) -> Callable[[str], str]:
    return normalize_domain_term if label == "Dominio" else normalize_metric_name


def _base_props(sessao_id: str) -> dict[str, Any]:
    return {"projeto_id": GLOBAL_PROJECT_ID, "sessao_id": sessao_id, "visibilidade": "compartilhavel"}


def _agent_props(actor: Actor, justification: str) -> dict[str, Any]:
    if actor.requires_provenance_justification:
        return {"justificativa_criacao": justification, "nos_consultados": []}
    return {}


def _merge_synonyms(existing: list[str], new: list[str], canonical: str, label: str) -> list[str]:
    """Une sinônimos sem duplicar (por forma normalizada) nem repetir o termo canônico."""
    norm = _normalizer(label)
    merged = list(existing)
    keys = {norm(s) for s in merged} | {norm(canonical)}
    for item in new:
        key = norm(item)
        if key and key not in keys:
            merged.append(item)
            keys.add(key)
    return merged


def _has_edge(store: GraphStore, src_id: str, rel: str, dst_id: str) -> bool:
    sub = store.neighbors(src_id, [rel], direction="out", depth=1)
    return any(e.src_id == src_id and e.rel_type == rel and e.dst_id == dst_id for e in sub.edges)


# ---------------------------------------------------------------------------
# Carga inicial
# ---------------------------------------------------------------------------


def seed_vocabulary(
    store: GraphStore,
    *,
    vocabulary_dir: Path | None = None,
    sessao_id: str = "seed_vocabulary",
) -> dict[str, int]:
    """Carrega domínios (CNPq) e métricas no grafo, de forma idempotente.

    Chave de idempotência: ``codigo_cnpq`` (domínios) e ``nome`` (métricas). Em reexecução
    nada é duplicado; termos existentes só têm ``sinonimos`` ampliados.

    Args:
        store: Grafo de conhecimento.
        vocabulary_dir: Diretório com ``cnpq_areas.csv`` e ``metrics.yaml``.
        sessao_id: Identificador da sessão de carga (proveniência).

    Returns:
        Contadores ``dominios_criados``, ``metricas_criadas``, ``arestas_criadas``.

    Raises:
        VocabularySourceMissingError: Se a tabela do CNPq ou o catálogo não existem.
    """
    base = vocabulary_dir or DEFAULT_VOCABULARY_DIR
    # Valida as duas fontes antes de escrever qualquer coisa (fail-fast, sem carga parcial).
    cnpq_rows = load_cnpq_table(base / CNPQ_FILENAME)
    metrics = load_metrics_catalog(base / METRICS_FILENAME)
    actor = Actor(kind="orquestrador")
    stats = {"dominios_criados": 0, "metricas_criadas": 0, "arestas_criadas": 0}

    by_code = {
        n.properties.get("codigo_cnpq"): n.id
        for n in _all_nodes(store, "Dominio")
        if n.properties.get("codigo_cnpq")
    }
    for row in cnpq_rows:
        if row["codigo_cnpq"] in by_code:
            continue
        by_code[row["codigo_cnpq"]] = store.create_node(
            "Dominio",
            {
                "termo": row["termo"],
                "nivel": row["nivel"],
                "sinonimos": [],
                "codigo_cnpq": row["codigo_cnpq"],
                "status": "aprovado",
                **_base_props(sessao_id),
            },
            actor=actor,
        )
        stats["dominios_criados"] += 1
    for row in cnpq_rows:
        if row["codigo_pai"]:
            src, dst = by_code[row["codigo_cnpq"]], by_code[row["codigo_pai"]]
            if not _has_edge(store, src, "SUBAREA_DE", dst):
                store.create_edge(src, "SUBAREA_DE", dst, {}, actor=actor)
                stats["arestas_criadas"] += 1

    by_name = {n.properties["nome"]: n for n in _all_nodes(store, "Metrica")}
    ids: dict[str, str] = {}
    for item in metrics:
        sinonimos = list(item.get("sinonimos") or [])
        existing = by_name.get(item["nome"])
        if existing is not None:
            ids[item["nome"]] = existing.id
            current = list(existing.properties.get("sinonimos") or [])
            merged = _merge_synonyms(current, sinonimos, item["nome"], "Metrica")
            if merged != current:
                store.update_node(existing.id, {"sinonimos": merged}, actor=actor)
            continue
        props: dict[str, Any] = {
            "nome": item["nome"],
            "sinonimos": sinonimos,
            "sentido": item["sentido"],
            "status": "aprovado",
            **_base_props(sessao_id),
        }
        for optional in ("faixa", "familia", "unidade"):
            if item.get(optional):
                props[optional] = item[optional]
        ids[item["nome"]] = store.create_node("Metrica", props, actor=actor)
        stats["metricas_criadas"] += 1

    families: dict[str, list[str]] = {}
    for item in metrics:
        if item.get("familia"):
            families.setdefault(item["familia"], []).append(item["nome"])
    for names in families.values():
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                if not _has_edge(store, ids[a], "RELACIONADA_A", ids[b]) and not _has_edge(
                    store, ids[b], "RELACIONADA_A", ids[a]
                ):
                    store.create_edge(ids[a], "RELACIONADA_A", ids[b], {}, actor=actor)
                    stats["arestas_criadas"] += 1

    logger.info("Vocabulário carregado", extra={"extra": stats})
    return stats


# ---------------------------------------------------------------------------
# Resolução
# ---------------------------------------------------------------------------


def _resolve(
    store: GraphStore,
    label: str,
    term: str,
    *,
    actor: Actor,
    sessao_id: str,
    semantic_search: SemanticSearch | None,
    new_props: dict[str, Any],
    required_for_candidate: tuple[str, ...] = (),
    max_alternatives: int | None = None,
    keep_search_order: bool = False,
) -> Resolution:
    """Núcleo comum: exato -> sinônimo -> semântico -> candidato."""
    if not term or not term.strip():
        raise VocabularyError("Termo vazio não pode ser resolvido.")
    # Texto de agente: sem controles/quebras de linha e com tamanho limitado (volta ao prompt de outros agentes).
    term = clean_free_text(term)
    if len(term) > config.VOCAB_TERM_MAX_CHARS:
        raise VocabularyError(
            f"Termo com {len(term)} caracteres excede o limite de {config.VOCAB_TERM_MAX_CHARS} "
            "(VOCAB_TERM_MAX_CHARS); use a denominação do termo, não uma descrição."
        )
    if not term:
        raise VocabularyError("Termo vazio não pode ser resolvido.")
    norm = _normalizer(label)
    key = norm(term)
    if not key:
        raise VocabularyError(f"Termo '{term}' não contém caracteres alfanuméricos.")
    name_key = _name_key(label)
    nodes = [n for n in _all_nodes(store, label) if n.properties.get("status") != "rejeitado"]

    for node in nodes:
        if norm(str(node.properties[name_key])) == key:
            return Resolution(node.id, "exato")
    for node in nodes:
        if any(norm(str(s)) == key for s in node.properties.get("sinonimos") or []):
            return Resolution(node.id, "sinonimo")

    alternativas: list[tuple[str, float]] = []
    if semantic_search is not None:
        valid = {n.id: n for n in nodes}
        hits = [(nid, score) for nid, score in semantic_search(label, term) if nid in valid]
        if not keep_search_order:
            hits.sort(key=lambda h: h[1], reverse=True)
        # Na ordem da busca de domínio (mais específico dentro da margem), vale o primeiro que atinge o limiar.
        chosen = next((h for h in hits if h[1] >= config.VOCAB_MATCH_THRESHOLD), None)
        if chosen is not None:
            best = valid[chosen[0]]
            pending = list(best.properties.get("sinonimos_candidatos") or [])
            if all(norm(p) != key for p in pending):
                pending.append(term)
                store.update_node(best.id, {"sinonimos_candidatos": pending}, actor=actor)
            return Resolution(best.id, "semantico", alternativas=hits)
        alternativas = hits if max_alternatives is None else hits[:max_alternatives]

    for required in required_for_candidate:
        if required not in new_props:
            raise VocabularyError(
                f"'{term}' não existe no vocabulário e a propriedade '{required}' não foi informada; "
                f"informe '{required}' para criar o candidato."
            )
    props = {
        name_key: term.strip(),
        "sinonimos": [],
        "status": "candidato",
        **new_props,
        **_base_props(sessao_id),
        **_agent_props(actor, f"Candidato criado pela resolução do termo livre '{term.strip()}'."),
    }
    node_id = store.create_node(label, props, actor=actor)
    logger.info("Candidato de vocabulário criado", extra={"extra": {"label": label, "node_id": node_id}})
    return Resolution(node_id, "candidato_criado", alternativas=alternativas)


_DOMAIN_ALTERNATIVES = 3


def _domain_search_adapter(search: DomainSearch, context: str | None) -> SemanticSearch:
    """Adapta ``DomainSearch`` ao contrato ``(rótulo, termo) -> [(node_id, score)]`` do passo semântico."""

    def _search(_label: str, term: str) -> list[tuple[str, float]]:
        try:
            hits = search.search(term, context=context, include_candidates=True, limit=10)
        except ValueError:
            # Termo curto demais para a busca vetorial: segue para o candidato.
            return []
        return [(h.node_id, h.score) for h in hits]

    return _search


def resolve_domain(
    store: GraphStore,
    term: str,
    *,
    actor: Actor,
    sessao_id: str,
    nivel: str = "especialidade",
    semantic_search: SemanticSearch | None = None,
    domain_search: DomainSearch | None = None,
    context: str | None = None,
) -> Resolution:
    """Resolve um termo livre para um ``Dominio`` canônico ou cria um candidato.

    Ordem: nome exato normalizado, sinônimo, similaridade semântica
    (>= ``VOCAB_MATCH_THRESHOLD``; pulada se não houver busca semântica) e, por fim,
    candidato (``codigo_cnpq`` vazio, utilizável imediatamente).

    O passo semântico usa ``semantic_search`` quando injetada (compatibilidade); do contrário,
    ``domain_search`` (busca hierárquica de ``v17-domain-search``, que inclui termos candidatos
    para não duplicá-los). Sem nenhuma das duas, o passo é pulado. Com ``domain_search``,
    vale a ordem da busca (nível mais específico dentro de ``DOMAIN_SPECIFICITY_MARGIN``): o nó
    escolhido é o primeiro cujo escore atinge o limiar. Abaixo do limiar, as três
    melhores correspondências ficam em ``alternativas`` para revisão humana.

    Args:
        store: Grafo de conhecimento.
        term: Termo de domínio em texto livre.
        actor: Quem resolve (autoria do candidato/sinônimo candidato).
        sessao_id: Sessão corrente (proveniência).
        nivel: Nível do candidato, se for criado (padrão ``especialidade``).
        semantic_search: Busca semântica injetada ``(rótulo, termo) -> [(node_id, score)]``.
        domain_search: Busca hierárquica de domínios, usada quando ``semantic_search`` é ``None``.
        context: Contexto da busca (ex.: texto do problema); só vale com ``domain_search``.

    Returns:
        A ``Resolution``.
    """
    uses_domain_search = semantic_search is None and domain_search is not None
    if uses_domain_search:
        semantic_search = _domain_search_adapter(domain_search, context)
    return _resolve(
        store, "Dominio", term, actor=actor, sessao_id=sessao_id, semantic_search=semantic_search,
        new_props={"nivel": nivel}, max_alternatives=_DOMAIN_ALTERNATIVES,
        keep_search_order=uses_domain_search,
    )


def resolve_metric(
    store: GraphStore,
    name: str,
    *,
    actor: Actor,
    sessao_id: str,
    sentido: str | None = None,
    semantic_search: SemanticSearch | None = None,
) -> Resolution:
    """Resolve um nome de métrica para uma ``Metrica`` canônica ou cria um candidato.

    Mesma ordem de ``resolve_domain``, com a normalização de nomes de métrica compartilhada
    com o Validator.

    Args:
        store: Grafo de conhecimento.
        name: Nome da métrica em texto livre.
        actor: Quem resolve.
        sessao_id: Sessão corrente.
        sentido: ``maior_melhor`` ou ``menor_melhor``; obrigatório apenas se for preciso criar
            candidato (o schema exige ``sentido``).
        semantic_search: Busca semântica injetada.

    Returns:
        A ``Resolution``.

    Raises:
        VocabularyError: Se um candidato precisa ser criado e ``sentido`` não foi informado.
    """
    new_props: dict[str, Any] = {}
    if sentido is not None:
        new_props["sentido"] = sentido
    return _resolve(
        store, "Metrica", name, actor=actor, sessao_id=sessao_id, semantic_search=semantic_search,
        new_props=new_props, required_for_candidate=("sentido",),
    )


# ---------------------------------------------------------------------------
# Decisão do pesquisador
# ---------------------------------------------------------------------------

_PESQUISADOR = Actor(kind="pesquisador")


def _vocab_node(store: GraphStore, node_id: str) -> Node:
    node = store.get_node(node_id)
    if node is None:
        raise VocabularyError(f"Nó '{node_id}' não encontrado.")
    if node.label not in ("Dominio", "Metrica"):
        raise VocabularyError(f"Nó '{node_id}' é '{node.label}', não um termo de vocabulário.")
    return node


def list_pending(store: GraphStore) -> list[dict[str, Any]]:
    """Lista candidatos e sinônimos candidatos aguardando decisão.

    Returns:
        Itens ``{"id", "label", "termo", "tipo"}`` com ``tipo`` ``"termo"`` (nó candidato) ou
        ``"sinonimo"`` (termo livre aproximado a um nó aprovado; ``sinonimos_candidatos`` lista os termos).
    """
    items: list[dict[str, Any]] = []
    for label in ("Dominio", "Metrica"):
        for node in _all_nodes(store, label):
            name = node.properties[_name_key(label)]
            if node.properties.get("status") == "candidato":
                items.append({"id": node.id, "label": label, "termo": name, "tipo": "termo"})
            if node.properties.get("sinonimos_candidatos"):
                items.append({
                    "id": node.id, "label": label, "termo": name, "tipo": "sinonimo",
                    "sinonimos_candidatos": list(node.properties["sinonimos_candidatos"]),
                })
    return items


def approve_term(store: GraphStore, node_id: str) -> None:
    """Aprova um candidato (``status=aprovado``) ou promove os sinônimos candidatos de um termo aprovado.

    Raises:
        VocabularyError: Se o nó não é candidato nem tem sinônimos candidatos pendentes.
    """
    node = _vocab_node(store, node_id)
    pending = list(node.properties.get("sinonimos_candidatos") or [])
    if node.properties.get("status") == "candidato":
        store.update_node(node_id, {"status": "aprovado"}, actor=_PESQUISADOR)
    elif pending:
        name = str(node.properties[_name_key(node.label)])
        merged = _merge_synonyms(list(node.properties.get("sinonimos") or []), pending, name, node.label)
        store.update_node(node_id, {"sinonimos": merged, "sinonimos_candidatos": []}, actor=_PESQUISADOR)
    else:
        raise VocabularyError(f"Nó '{node_id}' não é candidato nem tem sinônimos pendentes.")


def reject_term(store: GraphStore, node_id: str, motivo: str | None = None) -> None:
    """Rejeita um candidato sem apagá-lo (``status=rejeitado``) ou descarta sinônimos candidatos pendentes.

    Raises:
        VocabularyError: Se o nó não é candidato nem tem sinônimos candidatos pendentes.
    """
    node = _vocab_node(store, node_id)
    if node.properties.get("status") == "candidato":
        changes: dict[str, Any] = {"status": "rejeitado"}
        if motivo:
            changes["motivo_decisao"] = motivo
        store.update_node(node_id, changes, actor=_PESQUISADOR)
    elif node.properties.get("sinonimos_candidatos"):
        store.update_node(node_id, {"sinonimos_candidatos": []}, actor=_PESQUISADOR)
    else:
        raise VocabularyError(f"Nó '{node_id}' não é candidato nem tem sinônimos pendentes.")


def _relocated_edge_props(store_edge: Edge) -> dict[str, Any]:
    keep = {k: v for k, v in store_edge.properties.items() if k in ("origem", "status", "evidencias")}
    return keep


def map_term(store: GraphStore, node_id: str, canonical_id: str) -> None:
    """Funde um candidato em um termo canônico, sem apagar nada.

    As arestas do candidato são recriadas apontando para o canônico (as originais permanecem
    no grafo), o termo e os sinônimos do candidato entram nos sinônimos do canônico e o
    candidato fica ``rejeitado`` com ``motivo_decisao="mapeado para <id>"``.

    Raises:
        VocabularyError: Se os nós não existem, têm rótulos diferentes, o primeiro não é
            candidato ou o destino está rejeitado.
    """
    cand = _vocab_node(store, node_id)
    canon = _vocab_node(store, canonical_id)
    if node_id == canonical_id:
        raise VocabularyError("Um termo não pode ser mapeado para si mesmo.")
    if cand.label != canon.label:
        raise VocabularyError(f"Rótulos diferentes: '{cand.label}' e '{canon.label}'.")
    if cand.properties.get("status") != "candidato":
        raise VocabularyError(f"Nó '{node_id}' não é candidato.")
    if canon.properties.get("status") == "rejeitado":
        raise VocabularyError(f"Nó canônico '{canonical_id}' está rejeitado.")

    name_key = _name_key(cand.label)
    canon_name = str(canon.properties[name_key])
    merged = _merge_synonyms(
        list(canon.properties.get("sinonimos") or []),
        [str(cand.properties[name_key]), *(cand.properties.get("sinonimos") or [])],
        canon_name,
        cand.label,
    )
    store.update_node(canonical_id, {"sinonimos": merged}, actor=_PESQUISADOR)

    sub = store.neighbors(node_id, None, direction="both", depth=1)
    for edge in sub.edges:
        if node_id not in (edge.src_id, edge.dst_id):
            continue
        src = canonical_id if edge.src_id == node_id else edge.src_id
        dst = canonical_id if edge.dst_id == node_id else edge.dst_id
        if src == dst or _has_edge(store, src, edge.rel_type, dst):
            continue
        rel_schema = schema.find_relation_schema(
            (store.get_node(src) or cand).label, edge.rel_type, (store.get_node(dst) or cand).label
        )
        specific = {k: v for k, v in edge.properties.items() if rel_schema and k in rel_schema.properties}
        store.create_edge(src, edge.rel_type, dst, {**_relocated_edge_props(edge), **specific}, actor=_PESQUISADOR)

    store.update_node(
        node_id, {"status": "rejeitado", "motivo_decisao": f"mapeado para {canonical_id}"}, actor=_PESQUISADOR
    )
