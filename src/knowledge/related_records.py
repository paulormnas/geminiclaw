"""Experiência de problemas semelhantes: semelhança de Problemas, seleção de registros e bloco do plano (ADR 026 §6).

``v18.9-cross-project-context`` design §2 e §3. Dois pedaços puros (semelhança e modelo de texto) e uma leitura do
grafo (``related_records``) que usa o índice semântico só para o cosseno do texto. Todo texto vindo de outro projeto
(título, nome da abordagem, limite, lição) é sanitizado e o bloco inteiro entra como dado não confiável, nunca como
instrução.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src import config
from src.knowledge.curator_common import wrap_text
from src.knowledge.graph_store import GraphStore, Node
from src.knowledge.graph_views import sanitize_text
from src.knowledge.problem_similarity import problem_similarity
from src.knowledge.semantic_index import SemanticIndex, _parse_ts
from src.logger import get_logger

logger = get_logger(__name__)

BLOCK_NAME = "experiencia_de_problemas_semelhantes"
INSTRUCTION = (
    "Experiência de outro problema é hipótese a testar, não conclusão: confira se vale para este problema antes "
    "de reaproveitar a abordagem."
)
_MAX_CONFIG_CHARS = 90
_MAX_FIELD_CHARS = 120
_NOT_QUALIFIED = "não qualificado"


@dataclass(frozen=True)
class RelatedRecord:
    """Um registro de resultado de um Problema semelhante, pronto para o bloco."""

    problema_id: str
    registro_id: str
    similaridade: float
    titulo: str
    classe: str
    n_linhas: str
    n_atributos: str
    abordagem: str
    config_resumida: str
    metrica: str
    melhor_valor: float | None
    alvo: float | None
    delta_base: float | None
    replicas: int
    qualificacao: str
    limite: str
    atingiu_alvo: bool
    rank: float


def _clip(value: Any, limit: int = _MAX_FIELD_CHARS) -> str:
    return sanitize_text(value, limit) if value is not None else ""


def _config_summary(condicoes: Any) -> str:
    cfg = condicoes.get("config") if isinstance(condicoes, dict) else None
    if not isinstance(cfg, dict) or not cfg:
        return ""
    parts = [f"{k}={v}" for k, v in cfg.items() if not isinstance(v, (dict, list))]
    return _clip(", ".join(parts), _MAX_CONFIG_CHARS)


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _recency(stamp: Any, now: datetime) -> float:
    created = _parse_ts(stamp)
    if created is None:
        return 1.0
    return 0.5 ** (max((now - created).total_seconds() / 86400, 0.0) / config.RECENCY_HALF_LIFE_DAYS)


def _facts(data: Any, key: str) -> str:
    return _clip(data.get(key), 40) if isinstance(data, dict) and data.get(key) is not None else "?"


def _record_of(store: GraphStore, record: Node, problem: Node, sim: float, now: datetime) -> RelatedRecord | None:
    props = record.properties
    sub = store.neighbors(record.id, ["REGISTRA"], direction="out", depth=1)
    approach = next((n for n in sub.nodes if n.label == "Abordagem"), None)
    if approach is None:
        return None
    criterio = problem.properties.get("criterio_sucesso")
    replicas = int(props.get("n_replicas_independentes") or 0)
    margin = max(_num(props.get("delta_base")) or 0.0, 0.0)
    data = problem.properties.get("caracteristicas_dados")
    return RelatedRecord(
        problema_id=problem.id,
        registro_id=record.id,
        similaridade=sim,
        titulo=_clip(problem.properties.get("titulo")),
        classe=_clip(problem.properties.get("classe"), 40) or "?",
        n_linhas=_facts(data, "tamanho"),
        n_atributos=_facts(data, "atributos"),
        abordagem=_clip(approach.properties.get("nome")),
        config_resumida=_config_summary(props.get("condicoes")),
        metrica=_clip(props.get("metrica"), 40),
        melhor_valor=_num(props.get("melhor_valor")),
        alvo=_num(criterio.get("alvo")) if isinstance(criterio, dict) else None,
        delta_base=_num(props.get("delta_base")),
        replicas=replicas,
        qualificacao=str(props.get("qualificacao") or "pendente"),
        limite=_clip(props.get("limite_aplicabilidade")),
        atingiu_alvo=bool(props.get("atingiu_alvo")),
        rank=sim * (1.0 + margin) * min(max(replicas, 1), 3) * _recency(props.get("atualizado_em"), now),
    )


def related_records(
    store: GraphStore,
    index: SemanticIndex,
    problema_id: str,
    *,
    k: int | None = None,
    min_similarity: float | None = None,
    now: datetime | None = None,
    mode: str | None = None,
) -> list[RelatedRecord]:
    """Registros dos ``k`` Problemas de outros projetos mais semelhantes (visão local do pesquisador).

    Por Problema entram o melhor registro que atingiu o alvo e o registro ``restricao`` mais recente; ``retido`` fica
    de fora (design §2). Só Problemas com semelhança de pelo menos ``min_similarity`` (padrão
    ``CANDIDATE_MIN_SIMILARITY``).

    ``mode`` (padrão ``RELATED_RECORDS_MODE``) escolhe o braço do E2: ``grafo`` (o descrito acima), ``plana`` (todos os
    registros dos mesmos Problemas, sem filtro de qualificação nem seleção), ``distante`` (os ``k`` Problemas mais
    próximos *abaixo* do limiar, com a seleção do ``grafo``) e ``sem`` (nada). ``RELATED_RECORDS_CUTOFF`` congela o
    corpus: Problemas criados depois dele não entram.
    """
    mode = config.RELATED_RECORDS_MODE if mode is None else mode
    if mode == "sem":
        return []
    k = config.RELATED_RECORDS_K if k is None else k
    floor = config.CANDIDATE_MIN_SIMILARITY if min_similarity is None else min_similarity
    now = now or datetime.now(timezone.utc)
    origin = store.get_node(problema_id)
    if origin is None:
        return []
    own_project = origin.properties.get("projeto_id")
    hits = index.similar(node_id=problema_id, labels=["Problema"], min_score=0.0, limit=50)
    scored: list[tuple[float, Node]] = []
    for hit in hits:
        other = store.get_node(hit.node_id)
        if other is None or other.properties.get("projeto_id") == own_project:
            continue
        sim = problem_similarity(
            hit.score, origin.properties.get("caracteristicas_dados"), other.properties.get("caracteristicas_dados")
        )
        created = str(other.properties.get("criado_em") or "")
        if config.RELATED_RECORDS_CUTOFF and created > config.RELATED_RECORDS_CUTOFF:
            continue
        if (sim < floor) == (mode == "distante"):
            scored.append((sim, other))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    found: list[RelatedRecord] = []
    for sim, problem in scored[:k]:
        sub = store.neighbors(problem.id, ["SOBRE"], direction="in", depth=1)
        if mode == "plana":
            found.extend(
                r
                for node in sub.nodes
                if node.label == "RegistroResultado"
                if (r := _record_of(store, node, problem, sim, now)) is not None
            )
            continue
        items = [
            r
            for node in sub.nodes
            if node.label == "RegistroResultado" and node.properties.get("qualificacao") != "retido"
            if (r := _record_of(store, node, problem, sim, now)) is not None
        ]
        reached = [r for r in items if r.atingiu_alvo]
        constraints = [r for r in items if r.qualificacao == "restricao"]
        if reached:
            found.append(max(reached, key=lambda r: (r.rank, r.registro_id)))
        if constraints:
            latest = max(constraints, key=lambda r: r.registro_id)  # ids são UUIDv7: ordem de criação
            if all(latest.registro_id != f.registro_id for f in found):
                found.append(latest)
    return found


def _fmt(value: float | None) -> str:
    return "?" if value is None else f"{value:.4g}"


def render_block(
    records: list[RelatedRecord], here: dict[str, str], *, limit: int | None = None, flat: bool = False
) -> str | None:
    """Bloco ``experiencia_de_problemas_semelhantes`` em modelo fixo (design §2); ``None`` sem registros.

    Args:
        records: Registros de ``related_records``.
        here: Descrição do problema atual (``classe``, ``n_linhas``, ``n_atributos``).
        limit: Teto de caracteres (padrão ``RELATED_RECORDS_MAX_CHARS``).
    """
    if not records:
        return None
    limit = config.RELATED_RECORDS_MAX_CHARS if limit is None else limit
    lines: list[str] = []
    current: str | None = None
    for rec in records:
        if rec.problema_id != current:
            current = rec.problema_id
            lines.append(f"[{rec.titulo} | classe {rec.classe} | {rec.n_linhas} linhas, {rec.n_atributos} atributos]")
        if flat:  # memória plana (E2): só abordagem e valor, sem fatos qualificados nem limite de aplicabilidade
            lines.append(f"{rec.abordagem}: {rec.metrica} {_fmt(rec.melhor_valor)}")
            continue
        cfg = f" ({rec.config_resumida})" if rec.config_resumida else ""
        lines.append(
            f"{rec.abordagem}{cfg}: {rec.metrica} {_fmt(rec.melhor_valor)} (alvo {_fmt(rec.alvo)}; "
            f"Δbase {_fmt(rec.delta_base)}; réplicas {rec.replicas}) — {rec.qualificacao}"
        )
        lines.append(f"Limite: {rec.limite or _NOT_QUALIFIED}")
    lines.append(
        f"Este problema: {here.get('classe', '?')} | {here.get('n_linhas', '?')} linhas, "
        f"{here.get('n_atributos', '?')} atributos"
    )
    return INSTRUCTION + "\n" + wrap_text(BLOCK_NAME, "\n".join(lines), limit)


def problem_description(problem: Node) -> dict[str, str]:
    """``classe``, ``n_linhas`` e ``n_atributos`` do Problema, no formato de ``render_block``."""
    data = problem.properties.get("caracteristicas_dados")
    return {
        "classe": _clip(problem.properties.get("classe"), 40) or "?",
        "n_linhas": _facts(data, "tamanho"),
        "n_atributos": _facts(data, "atributos"),
    }


def experience_block(store: GraphStore, index: SemanticIndex | None, problem: Node | None) -> str | None:
    """Bloco do plano para o Problema, ou ``None`` sem índice, sem registros ou com o grafo indisponível.

    Falha de leitura vira omissão do bloco com um aviso no log: o plano segue sem a experiência (nunca inventa).
    """
    if index is None or problem is None:
        return None
    try:
        records = related_records(store, index, problem.id)
    except Exception as exc:  # noqa: BLE001 - índice ou grafo fora do ar: o plano segue sem o bloco
        logger.warning(
            "Experiência de problemas semelhantes indisponível", extra={"extra": {"erro": type(exc).__name__}}
        )
        return None
    return render_block(records, problem_description(problem), flat=config.RELATED_RECORDS_MODE == "plana")
