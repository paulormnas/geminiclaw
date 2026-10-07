"""Visualização do grafo pelo pesquisador (``v17-graph-cli``; ADR 015 §11): somente leitura, sem LLM.

Consultas **fixas** sobre ``GraphStore`` (``project_subgraph``, ``find_nodes``, ``neighbors``, ``get_node``,
``audit_history``), restritas ao projeto ativo (mais os nós ``compartilhavel`` quando vistos por ``graph node``).
Nenhuma consulta Cypher/SQL digitada pelo usuário ou gerada por modelo passa por aqui, e nenhum provedor de LLM é
importado.

Toda saída destinada ao terminal passa por :func:`sanitize_text`: o conteúdo do grafo (inclusive o que veio de artigos,
arquivos ou agentes) pode conter sequências de escape de terminal (ANSI/OSC), caracteres de controle ou de direção de
texto (bidi); eles são removidos antes de qualquer impressão. Tamanhos de texto e número de nós são limitados.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Protocol

from src import config
from src.knowledge import schema
from src.knowledge.graph_store import Edge, Node, Subgraph

FORMATS = ("text", "table", "json", "mermaid")
MAX_DEPTH = 3
AUDIT_LIMIT = 30
_MAX_COLLECTION_ITEMS = 30
_HIDDEN_PROPERTIES = frozenset({"estado_vetorizacao", "versao_schema", "origem_no"})
# Texto principal de um nó, por ordem de preferência.
_TEXT_KEYS = ("enunciado", "titulo", "nome", "termo", "contexto", "subtarefa_id", "nome_original")
_TABLE_KEYS = ("status", "tipo", "veredito", "criado_por")
_VERDICT_LABELS = frozenset({"Hipotese", "Descoberta"})
_STATUS_RE_MAX = 40
_REMOVED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


class GraphViewError(Exception):
    """Pedido de visualização inválido (rótulo desconhecido, projeto inexistente, nó fora do escopo...)."""


class GraphReader(Protocol):
    """O que a visualização usa do grafo: **apenas leituras** (nenhum método de escrita nem ``read_query``)."""

    def get_node(self, node_id: str) -> Node | None: ...

    def find_nodes(self, label: str, filters: dict[str, Any], limit: int = 50) -> list[Node]: ...

    def list_nodes(self, label: str, *, after_id: str | None = None, limit: int = 200) -> list[Node]: ...

    def neighbors(self, node_id: str, rels: list[str] | None, direction: str = "both", depth: int = 1) -> Subgraph: ...

    def project_subgraph(self, projeto_id: str, labels: list[str] | None = None) -> Subgraph: ...

    def audit_history(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]: ...


class ReadOnlyGraph:
    """Fachada somente-leitura sobre um ``GraphStore``: não expõe nenhuma operação de escrita nem consulta livre."""

    __slots__ = ("_store",)

    def __init__(self, store: Any) -> None:
        self._store = store

    def get_node(self, node_id: str) -> Node | None:
        return self._store.get_node(node_id)

    def find_nodes(self, label: str, filters: dict[str, Any], limit: int = 50) -> list[Node]:
        return self._store.find_nodes(label, filters, limit)

    def list_nodes(self, label: str, *, after_id: str | None = None, limit: int = 200) -> list[Node]:
        return self._store.list_nodes(label, after_id=after_id, limit=limit)

    def neighbors(self, node_id: str, rels: list[str] | None, direction: str = "both", depth: int = 1) -> Subgraph:
        return self._store.neighbors(node_id, rels, direction, depth)

    def project_subgraph(self, projeto_id: str, labels: list[str] | None = None) -> Subgraph:
        return self._store.project_subgraph(projeto_id, labels)

    def audit_history(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self._store.audit_history(node_id, limit)


# ---------------------------------------------------------------------------
# Sanitização de saída
# ---------------------------------------------------------------------------


def sanitize_text(value: Any, limit: int | None = None) -> str:
    """Texto seguro para o terminal, em uma linha.

    Remove caracteres de controle (inclui ``ESC``, ``DEL`` e os C1), de formatação (inclui marcas bidi e de largura
    zero), separadores de linha/parágrafo, caracteres privados e não atribuídos; quebras e tabulações viram espaço e
    espaços repetidos colapsam. Com ``limit``, corta com reticências.
    """
    text = value if isinstance(value, str) else str(value)
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if char in "\n\r\t":
            kept.append(" ")
        elif category in _REMOVED_CATEGORIES:
            continue
        else:
            kept.append(char)
    clean = " ".join("".join(kept).split())
    cap = config.GRAPH_SHOW_MAX_TEXT_CHARS if limit is None else limit
    if cap > 0 and len(clean) > cap:
        clean = clean[: max(cap - 1, 0)] + "…"
    return clean


def sanitize_value(value: Any, limit: int | None = None, _depth: int = 0) -> Any:
    """Versão recursiva de :func:`sanitize_text` para propriedades (textos limpos; coleções e profundidade limitadas)."""
    if isinstance(value, str):
        return sanitize_text(value, limit)
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if _depth >= 3:
        return sanitize_text(value, limit)
    if isinstance(value, dict):
        return {
            sanitize_text(k, 80): sanitize_value(v, limit, _depth + 1)
            for k, v in list(value.items())[:_MAX_COLLECTION_ITEMS]
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_value(v, limit, _depth + 1) for v in list(value)[:_MAX_COLLECTION_ITEMS]]
    return sanitize_text(value, limit)


def format_verdict(veredito: Any) -> str | None:
    """``+0,36 funciona (moderada)`` a partir do veredito numérico (leitura determinística, sem LLM)."""
    if isinstance(veredito, bool) or not isinstance(veredito, (int, float)):
        return None
    from src.knowledge.verdict import VerdictParams, read_verdict

    leitura, tipo = read_verdict(float(veredito), VerdictParams.from_config().thresholds)
    number = f"{float(veredito):+.2f}".replace(".", ",")
    if tipo is None:
        return f"{number} {leitura}"
    faixa = leitura.removeprefix(f"{tipo}_")
    nome = "não funciona" if tipo == "nao_funciona" else tipo
    return f"{number} {nome} ({faixa})"


# ---------------------------------------------------------------------------
# Modelo da visão
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphView:
    """Visão do subgrafo do projeto, já filtrada, ordenada e limitada.

    Attributes:
        projeto_id: Projeto exibido.
        nodes: Nós exibidos (página corrente).
        edges: Arestas entre nós exibidos.
        total_nodes: Nós que atendem aos filtros (antes do limite).
        offset: Deslocamento da página.
        truncated: ``True`` se há mais nós do que os exibidos.
        filters: Filtros aplicados (para a sugestão no aviso).
    """

    projeto_id: str
    nodes: list[Node]
    edges: list[Edge]
    total_nodes: int
    offset: int = 0
    truncated: bool = False
    filters: dict[str, Any] = field(default_factory=dict)


def _norm(text: Any) -> str:
    return " ".join(str(text).casefold().split())


def _node_sort_key(node: Node) -> tuple[str, str, str]:
    return (node.label, str(node.properties.get("criado_em", "")), node.id)


def _domain_node_ids(store: GraphReader, term: str) -> list[str]:
    """IDs de ``Dominio`` cujo termo ou sinônimo é ``term`` (comparação sem caixa), só os visíveis (compartilháveis)."""
    wanted = _norm(term)
    found: list[str] = []
    after: str | None = None
    for _ in range(50):
        page = store.list_nodes("Dominio", after_id=after, limit=200)
        if not page:
            break
        for node in page:
            names = [node.properties.get("termo", "")] + list(node.properties.get("sinonimos") or [])
            if any(_norm(n) == wanted for n in names):
                found.append(node.id)
        after = page[-1].id
        if len(page) < 200:
            break
    return found


def load_project_view(
    store: GraphReader,
    projeto_id: str,
    *,
    labels: list[str] | None = None,
    dominio: str | None = None,
    status: str | None = None,
    depth: int = 0,
    max_nodes: int | None = None,
    offset: int = 0,
) -> GraphView:
    """Carrega o subgrafo do projeto com filtros fixos (rótulo, domínio, status) e expansão por ``depth`` saltos.

    Args:
        store: Leitor do grafo (somente leitura).
        projeto_id: Projeto ativo; nada de outro projeto é devolvido.
        labels: Rótulos a incluir (validados contra o schema).
        dominio: Termo (ou sinônimo) de ``Dominio``: só nós ligados a ele por ``NO_DOMINIO``.
        status: Valor de ``status`` exigido.
        depth: Saltos a partir dos nós filtrados (0 = só os filtrados), até ``MAX_DEPTH``; só dentro do projeto.
        max_nodes: Limite de nós exibidos (padrão ``GRAPH_SHOW_MAX_NODES``).
        offset: Deslocamento para paginar além do limite.

    Raises:
        GraphViewError: Rótulo desconhecido, ``depth``/``offset`` inválidos.
    """
    labels = list(dict.fromkeys(labels or []))
    for label in labels:
        if label not in schema.NODE_LABELS:
            raise GraphViewError(f"Rótulo desconhecido: {sanitize_text(label, 40)}.")
    if not isinstance(depth, int) or not 0 <= depth <= MAX_DEPTH:
        raise GraphViewError(f"--depth deve estar entre 0 e {MAX_DEPTH}.")
    if not isinstance(offset, int) or offset < 0:
        raise GraphViewError("--offset deve ser um inteiro >= 0.")
    cap = config.GRAPH_SHOW_MAX_NODES if max_nodes is None else max_nodes
    if cap < 1:
        raise GraphViewError("O limite de nós deve ser >= 1.")

    full = store.project_subgraph(projeto_id, None)
    by_id = {n.id: n for n in full.nodes if n.properties.get("projeto_id") == projeto_id}
    edges = [e for e in full.edges if e.src_id in by_id and e.dst_id in by_id]

    selected = set(by_id)
    if labels:
        selected = {i for i in selected if by_id[i].label in labels}
    if status is not None:
        selected = {i for i in selected if by_id[i].properties.get("status") == status}
    if dominio is not None:
        linked: set[str] = set()
        for domain_id in _domain_node_ids(store, dominio):
            sub = store.neighbors(domain_id, ["NO_DOMINIO"], "in", 1)
            linked.update(n.id for n in sub.nodes if n.id in by_id)
        selected &= linked
    if depth and selected:
        frontier = set(selected)
        for _ in range(depth):
            reached = {e.dst_id for e in edges if e.src_id in frontier} | {
                e.src_id for e in edges if e.dst_id in frontier
            }
            frontier = reached - selected
            selected |= reached
            if not frontier:
                break

    ordered = sorted((by_id[i] for i in selected), key=_node_sort_key)
    page = ordered[offset : offset + cap]
    shown = {n.id for n in page}
    shown_edges = sorted(
        (e for e in edges if e.src_id in shown and e.dst_id in shown),
        key=lambda e: (e.src_id, e.rel_type, e.dst_id),
    )
    filters = {k: v for k, v in {"label": labels or None, "dominio": dominio, "status": status}.items() if v}
    return GraphView(
        projeto_id=projeto_id,
        nodes=page,
        edges=shown_edges,
        total_nodes=len(ordered),
        offset=offset,
        truncated=offset + cap < len(ordered),
        filters=filters,
    )


# ---------------------------------------------------------------------------
# Renderizadores (todos devolvem texto já sanitizado)
# ---------------------------------------------------------------------------


def node_text(node: Node, limit: int = 120) -> str:
    """Texto principal curto de um nó (sanitizado)."""
    for key in _TEXT_KEYS:
        value = node.properties.get(key)
        if isinstance(value, str) and value.strip():
            return sanitize_text(value, limit)
    return ""


def _node_summary(node: Node) -> str:
    parts = [f"{sanitize_text(node.id, 64)}"]
    status = node.properties.get("status")
    if status:
        parts.append(f"[{sanitize_text(status, 30)}]")
    text = node_text(node)
    if text:
        parts.append(text)
    verdict = format_verdict(node.properties.get("veredito")) if node.label in _VERDICT_LABELS else None
    if verdict:
        parts.append(f"| veredito {verdict}")
    return " ".join(parts)


def _truncation_notice(view: GraphView) -> str:
    first, last = view.offset + 1, view.offset + len(view.nodes)
    filters = " ".join(f"--{k} {v}" if not isinstance(v, list) else " ".join(f"--label {x}" for x in v)
                       for k, v in view.filters.items()) or "(nenhum)"
    return (
        f"AVISO: saída truncada: exibindo os nós {first}-{last} de {view.total_nodes} "
        f"(limite {config.GRAPH_SHOW_MAX_NODES}). Refine com --label, --status ou --dominio, ou use "
        f"--offset {view.offset + len(view.nodes)} para a próxima página. Filtros atuais: {sanitize_text(filters, 120)}."
    )


def render_text(view: GraphView) -> str:
    """Agrupado por rótulo, com as relações de saída de cada nó em árvore."""
    if not view.nodes:
        return "Nenhum nó encontrado para os filtros informados."
    index = {n.id: n for n in view.nodes}
    out_edges: dict[str, list[Edge]] = {}
    for edge in view.edges:
        out_edges.setdefault(edge.src_id, []).append(edge)
    lines = [f"Projeto {sanitize_text(view.projeto_id, 64)}: {view.total_nodes} nó(s), {len(view.edges)} relação(ões) exibida(s)."]
    for label in sorted({n.label for n in view.nodes}):
        group = [n for n in view.nodes if n.label == label]
        lines.append("")
        lines.append(f"{sanitize_text(label, 40)} ({len(group)})")
        for node in group:
            lines.append(f"- {_node_summary(node)}")
            rels = out_edges.get(node.id, [])
            for i, edge in enumerate(rels):
                branch = "└─" if i == len(rels) - 1 else "├─"
                dst = index[edge.dst_id]
                mark = "" if edge.properties.get("status") in (None, "confirmada") else f" ({sanitize_text(edge.properties.get('status'), 20)})"
                lines.append(
                    f"    {branch} {sanitize_text(edge.rel_type, 40)}{mark} -> {sanitize_text(dst.label, 40)} "
                    f"{sanitize_text(dst.id, 64)} {node_text(dst, 60)}".rstrip()
                )
    if view.truncated:
        lines += ["", _truncation_notice(view)]
    return "\n".join(lines)


def _cell(value: Any, width: int = 40) -> str:
    return sanitize_text("" if value is None else value, width)


def render_table(view: GraphView) -> str:
    """Uma tabela por rótulo com as propriedades principais."""
    if not view.nodes:
        return "Nenhum nó encontrado para os filtros informados."
    blocks: list[str] = []
    for label in sorted({n.label for n in view.nodes}):
        group = [n for n in view.nodes if n.label == label]
        columns = ["id", "texto"] + [k for k in _TABLE_KEYS if any(k in n.properties for n in group)]
        rows = []
        for node in group:
            row = [_cell(node.id, 64), node_text(node, 40)]
            for key in columns[2:]:
                value = node.properties.get(key)
                row.append(format_verdict(value) or _cell(value) if key == "veredito" else _cell(value))
            rows.append(row)
        widths = [max(len(columns[i]), *(len(r[i]) for r in rows)) for i in range(len(columns))]
        header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
        rule = "-+-".join("-" * w for w in widths)
        body = [" | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) for r in rows]
        blocks.append("\n".join([f"{sanitize_text(label, 40)} ({len(group)})", header, rule, *body]))
    if view.truncated:
        blocks.append(_truncation_notice(view))
    return "\n\n".join(blocks)


def node_properties(node: Node, limit: int | None = None) -> dict[str, Any]:
    """Propriedades visíveis do nó, sanitizadas e com textos limitados."""
    return {
        sanitize_text(k, 80): sanitize_value(v, limit)
        for k, v in sorted(node.properties.items())
        if k not in _HIDDEN_PROPERTIES
    }


def render_json(view: GraphView) -> str:
    """``{"nodes": [...], "edges": [...]}`` (JSON válido, strings sanitizadas), mais metadados de truncamento."""
    payload = {
        "nodes": [
            {"id": sanitize_text(n.id, 64), "label": sanitize_text(n.label, 40), "properties": node_properties(n)}
            for n in view.nodes
        ],
        "edges": [
            {
                "src": sanitize_text(e.src_id, 64),
                "rel": sanitize_text(e.rel_type, 40),
                "dst": sanitize_text(e.dst_id, 64),
                "status": sanitize_value(e.properties.get("status")),
            }
            for e in view.edges
        ],
        "total_nodes": view.total_nodes,
        "offset": view.offset,
        "truncated": view.truncated,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _mermaid_label(text: str) -> str:
    """Rótulo de nó Mermaid seguro: entre aspas, com ``" < > & | [ ] { } ( )`` neutralizados."""
    replacements = {
        '"': "#quot;", "<": "#lt;", ">": "#gt;", "&": "#amp;", "|": "#124;",
        "[": "#91;", "]": "#93;", "{": "#123;", "}": "#125;", "(": "#40;", ")": "#41;", "`": "#96;",
    }
    return "".join(replacements.get(c, c) for c in text)


def render_mermaid(view: GraphView) -> str:
    """Diagrama ``graph LR`` para colar em Markdown (aliases ``n0``, ``n1``...; textos neutralizados)."""
    alias = {n.id: f"n{i}" for i, n in enumerate(view.nodes)}
    lines = ["graph LR"]
    for node in view.nodes:
        text = node_text(node, 50)
        label = _mermaid_label(f"{sanitize_text(node.label, 40)}: {text}" if text else sanitize_text(node.label, 40))
        lines.append(f'    {alias[node.id]}["{label}"]')
    for edge in view.edges:
        rel = _mermaid_label(sanitize_text(edge.rel_type, 40))
        lines.append(f"    {alias[edge.src_id]} -->|{rel}| {alias[edge.dst_id]}")
    if view.truncated:
        lines.append(f"    %% {sanitize_text(_truncation_notice(view), 300).replace('%%', '')}")
    return "\n".join(lines)


def render_view(view: GraphView, fmt: str) -> str:
    """Renderiza ``view`` no formato ``text``, ``table``, ``json`` ou ``mermaid``."""
    renderers = {"text": render_text, "table": render_table, "json": render_json, "mermaid": render_mermaid}
    if fmt not in renderers:
        raise GraphViewError(f"Formato desconhecido: {sanitize_text(fmt, 20)} (use {', '.join(FORMATS)}).")
    return renderers[fmt](view)


# ---------------------------------------------------------------------------
# Detalhe de um nó
# ---------------------------------------------------------------------------


@dataclass
class NodeDetail:
    """Detalhe de um nó: propriedades, relações, histórico e, se houver, o detalhamento do veredito."""

    node: Node
    relations: list[dict[str, Any]]
    hidden_relations: int
    history: list[dict[str, Any]]
    verdict: dict[str, Any] | None = None
    verdict_note: str | None = None


def _visible(node: Node, projeto_id: str) -> bool:
    return node.properties.get("projeto_id") == projeto_id or node.properties.get("visibilidade") == "compartilhavel"


def _verdict_detail(store: GraphReader, node: Node) -> tuple[dict[str, Any] | None, str | None]:
    """Detalhamento ``q, m, d, b, w`` por tentativa (cálculo determinístico do ``KnowledgeService``; sem LLM)."""
    from src.knowledge.service import KnowledgeService, KnowledgeServiceError

    service = KnowledgeService(store)  # type: ignore[arg-type]  # só chama métodos de leitura
    try:
        if node.label == "Hipotese":
            result, _, _ = service.verdict_for_hypothesis(node.id)
        else:
            sub = store.neighbors(node.id, ["SOBRE"], "out", 1)
            filtro = node.properties.get("filtro_condicoes")
            scope = service.verdict_for_scope(
                [n for n in sub.nodes if _visible(n, str(node.properties.get("projeto_id")))],
                filtro if isinstance(filtro, dict) else None,
            )
            if scope is None:
                return None, "sem escopo calculável (SOBRE sem Hipótese ou Abordagem+Problema)."
            result = scope[0]
    except KnowledgeServiceError as exc:
        return None, f"detalhamento indisponível: {sanitize_text(exc, 160)}"
    return {
        "veredito": round(result.veredito, 4),
        "leitura": format_verdict(result.veredito),
        "suporte": round(result.suporte, 4),
        "certeza": round(result.certeza, 4),
        "n_tentativas": result.n_tentativas,
        "tentativas": [
            {
                "tentativa": sanitize_text(d.attempt_id, 64),
                "classificacao": sanitize_text(d.classificacao, 30),
                "q": round(d.q, 4), "m": round(d.m, 4), "d": round(d.d, 4), "b": round(d.b, 4), "w": round(d.w, 4),
            }
            for d in result.detalhes[:_MAX_COLLECTION_ITEMS * 3]
        ],
    }, None


def load_node_detail(store: GraphReader, node_id: str, projeto_id: str) -> NodeDetail:
    """Detalhe de um nó do projeto (ou compartilhável).

    Raises:
        GraphViewError: Nó inexistente **ou de outro projeto privado** (a mesma mensagem, para não revelar existência).
    """
    node = store.get_node(node_id) if isinstance(node_id, str) and 0 < len(node_id) <= 128 else None
    if node is None or not _visible(node, projeto_id):
        raise GraphViewError("Nó não encontrado no projeto.")
    sub = store.neighbors(node.id, None, "both", 1)
    others = {n.id: n for n in sub.nodes}
    relations: list[dict[str, Any]] = []
    hidden = 0
    for edge in sub.edges:
        outgoing = edge.src_id == node.id
        other = others.get(edge.dst_id if outgoing else edge.src_id)
        if other is None or not _visible(other, projeto_id):
            hidden += 1
            continue
        relations.append(
            {
                "direcao": "saida" if outgoing else "entrada",
                "rel": sanitize_text(edge.rel_type, 40),
                "status": sanitize_value(edge.properties.get("status")),
                "no": sanitize_text(other.id, 64),
                "label": sanitize_text(other.label, 40),
                "texto": node_text(other, 80),
            }
        )
    relations.sort(key=lambda r: (r["direcao"], r["rel"], r["no"]))
    history = [
        {
            "actor": sanitize_text(h.get("actor"), 80),
            "timestamp": sanitize_text(h.get("timestamp"), 40),
            "changes": sanitize_value(h.get("changes"), 300),
        }
        for h in store.audit_history(node.id, AUDIT_LIMIT)
    ]
    verdict, note = (None, None)
    if node.label in _VERDICT_LABELS:
        verdict, note = _verdict_detail(store, node)
    return NodeDetail(node, relations[:100], hidden, history, verdict, note)


def render_node_detail(detail: NodeDetail, fmt: str = "text") -> str:
    """Renderiza o detalhe (``text`` ou ``json``)."""
    node = detail.node
    if fmt == "json":
        return json.dumps(
            {
                "id": sanitize_text(node.id, 64),
                "label": sanitize_text(node.label, 40),
                "properties": node_properties(node, 1000),
                "relations": detail.relations,
                "hidden_relations": detail.hidden_relations,
                "history": detail.history,
                "verdict_breakdown": detail.verdict,
                "verdict_note": detail.verdict_note,
            },
            ensure_ascii=False,
            indent=2,
        )
    if fmt != "text":
        raise GraphViewError("Formato de graph node: text ou json.")
    lines = [f"{sanitize_text(node.label, 40)} {sanitize_text(node.id, 64)}", "", "Propriedades:"]
    for key, value in node_properties(node, 1000).items():
        shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        lines.append(f"  {key}: {shown}")
    verdict = format_verdict(node.properties.get("veredito")) if node.label in _VERDICT_LABELS else None
    if verdict:
        lines.append(f"  leitura do veredito: {verdict}")
    lines += ["", f"Relações ({len(detail.relations)}):"]
    for rel in detail.relations or []:
        arrow = f"-{rel['rel']}->" if rel["direcao"] == "saida" else f"<-{rel['rel']}-"
        lines.append(f"  {arrow} {rel['label']} {rel['no']} {rel['texto']}".rstrip())
    if not detail.relations:
        lines.append("  (nenhuma)")
    if detail.hidden_relations:
        lines.append(f"  ({detail.hidden_relations} relação(ões) com nós de outros projetos omitida(s))")
    lines += ["", f"Histórico de alterações ({len(detail.history)}):"]
    for item in detail.history:
        changes = json.dumps(item["changes"], ensure_ascii=False)
        lines.append(f"  {item['timestamp']}  {item['actor']}  {sanitize_text(changes, 300)}")
    if not detail.history:
        lines.append("  (nenhum registro)")
    if node.label in _VERDICT_LABELS:
        lines += ["", "Veredito por tentativa:"]
        if detail.verdict is None:
            lines.append(f"  {detail.verdict_note or 'indisponível.'}")
        else:
            v = detail.verdict
            lines.append(f"  veredito {v['leitura']}; suporte {v['suporte']}; certeza {v['certeza']}; "
                         f"tentativas {v['n_tentativas']}")
            for t in v["tentativas"]:
                lines.append(
                    f"  - {t['tentativa']} {t['classificacao']}: q={t['q']} m={t['m']} d={t['d']} b={t['b']} w={t['w']}"
                )
    return "\n".join(lines)
