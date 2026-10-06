"""Busca semântica de domínios do vocabulário controlado (v17-domain-search §4).

``DomainSearch`` consulta os pontos ``Dominio`` do índice semântico e devolve candidatos com
score, nível e caminho completo (da grande área ao termo), preferindo o nível mais
específico quando a pontuação está dentro de ``DOMAIN_SPECIFICITY_MARGIN`` do melhor.

Somente leitura: não escreve no grafo nem no Qdrant. A consulta é tratada como dado: vira
um vetor e os filtros são objetos tipados, nada é interpolado em Cypher ou SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src import config
from src.knowledge.graph_store import GraphStore
from src.knowledge.semantic_index import DOMAIN_LEVELS, SemanticIndex
from src.logger import get_logger

logger = get_logger(__name__)

# Teto fixo de resultados, independente de ``limit`` e de ``DOMAIN_SEARCH_LIMIT``.
MAX_RESULTS = 10
# Tamanho mínimo da consulta (caracteres, depois do ``strip``).
MIN_QUERY_CHARS = 2
# Tamanho máximo aceito para o identificador ``within`` (código CNPq ou ID de nó).
_MAX_WITHIN_CHARS = 100


@dataclass(frozen=True)
class DomainHit:
    """Candidato de domínio devolvido pela busca.

    Attributes:
        node_id: ID do nó ``Dominio``.
        termo: Denominação do termo.
        nivel: ``grande_area``, ``area``, ``subarea`` ou ``especialidade``.
        caminho: Denominações da grande área até o termo.
        caminho_ids: IDs dos nós na mesma ordem.
        score: Similaridade cosseno.
        status: ``aprovado`` ou ``candidato``.
        sinonimos: Sinônimos aprovados do termo.
    """

    node_id: str
    termo: str
    nivel: str
    caminho: list[str]
    caminho_ids: list[str]
    score: float
    status: str
    sinonimos: list[str] = field(default_factory=list)


def _clip(text: str, limit: int, what: str) -> str:
    """Trunca ``text`` a ``limit`` caracteres e registra o truncamento (sem o conteúdo)."""
    if len(text) <= limit:
        return text
    logger.warning(
        "Entrada da busca de domínio truncada",
        extra={"extra": {"campo": what, "tamanho_original": len(text), "limite": limit}},
    )
    return text[:limit]


class DomainSearch:
    """Busca hierárquica de domínios sobre o índice semântico."""

    def __init__(self, store: GraphStore, index: SemanticIndex) -> None:
        """Inicializa a busca.

        Args:
            store: Grafo de conhecimento (leitura de sinônimos e resolução de ``within``).
            index: Índice semântico com os pontos ``Dominio``.
        """
        self._store = store
        self._index = index

    def _resolve_within(self, within: str) -> str:
        """Converte ``within`` (código CNPq ou ID) no ID de um ``Dominio`` existente.

        Raises:
            ValueError: Valor vazio, longo demais ou que não identifica nenhum domínio. Nunca cai
                em busca global.
        """
        value = within.strip() if isinstance(within, str) else ""
        if not value or len(value) > _MAX_WITHIN_CHARS:
            raise ValueError("`dentro_de` deve ser o código CNPq ou o ID de um domínio existente.")
        node = self._store.get_node(value)
        if node is not None and node.label == "Dominio":
            return node.id
        found = self._store.find_nodes("Dominio", {"codigo_cnpq": value}, limit=1)
        if found:
            return found[0].id
        raise ValueError(f"`dentro_de` '{value}' não é código CNPq nem ID de nenhum domínio conhecido.")

    def search(
        self,
        text: str,
        *,
        context: str | None = None,
        within: str | None = None,
        max_level: str | None = None,
        include_candidates: bool = False,
        limit: int | None = None,
    ) -> list[DomainHit]:
        """Busca domínios semanticamente próximos de um texto livre.

        Args:
            text: Termo ou descrição (2 a ``DOMAIN_SEARCH_MAX_QUERY_CHARS`` caracteres; o excesso é
                truncado e registrado).
            context: Contexto opcional (ex.: título do problema), truncado do mesmo modo.
            within: Código CNPq ou ID de um domínio; restringe a busca à sua subárvore.
            max_level: Nível mais específico aceito (``grande_area`` ... ``especialidade``).
            include_candidates: Inclui termos ``candidato`` (por padrão só os ``aprovado``).
            limit: Máximo de resultados (padrão ``DOMAIN_SEARCH_LIMIT``; teto 10).

        Returns:
            Candidatos ordenados por score, com preferência pelo nível mais específico entre os
            que estão dentro da margem do melhor. Vazio significa "sem correspondência".

        Raises:
            ValueError: Texto vazio ou curto demais, ``max_level`` inválido ou ``within`` desconhecido.
        """
        query = (text or "").strip() if isinstance(text, str) else ""
        if len(query) < MIN_QUERY_CHARS:
            raise ValueError(f"O texto da busca deve ter ao menos {MIN_QUERY_CHARS} caracteres.")
        max_chars = max(config.DOMAIN_SEARCH_MAX_QUERY_CHARS, MIN_QUERY_CHARS)
        query = _clip(query, max_chars, "texto")
        if max_level is not None and max_level not in DOMAIN_LEVELS:
            raise ValueError(f"`nivel_maximo` inválido; use um de {list(DOMAIN_LEVELS)}.")
        levels = list(DOMAIN_LEVELS[: DOMAIN_LEVELS.index(max_level) + 1]) if max_level else list(DOMAIN_LEVELS)
        within_id = self._resolve_within(within) if within is not None else None

        formatted = f"Domínio: {query}"
        if context and context.strip():
            formatted += f"\nContexto: {_clip(context.strip(), max_chars, 'contexto')}"

        wanted = config.DOMAIN_SEARCH_LIMIT if limit is None else limit
        wanted = min(max(int(wanted), 1), MAX_RESULTS)
        statuses = ["aprovado", "candidato"] if include_candidates else ["aprovado"]
        hits = self._index.search_domains(
            formatted, statuses=statuses, levels=levels, within=within_id, limit=max(wanted * 3, 15)
        )
        hits = [h for h in hits if h.score >= config.DOMAIN_SEARCH_MIN_SCORE]
        if not hits:
            return []

        hits.sort(key=lambda h: h.score, reverse=True)
        floor = hits[0].score - config.DOMAIN_SPECIFICITY_MARGIN
        near = [h for h in hits if h.score >= floor]
        rest = [h for h in hits if h.score < floor]
        near.sort(key=lambda h: (-self._depth(h.payload), -h.score))
        return [self._to_domain_hit(h) for h in (near + rest)[:wanted]]

    @staticmethod
    def _depth(payload: dict[str, Any]) -> int:
        nivel = payload.get("nivel")
        return DOMAIN_LEVELS.index(nivel) if nivel in DOMAIN_LEVELS else -1

    def _to_domain_hit(self, hit: Any) -> DomainHit:
        payload: dict[str, Any] = hit.payload
        termos = [str(t) for t in payload.get("caminho_termos") or []]
        node = self._store.get_node(hit.node_id)
        sinonimos = [str(s) for s in (node.properties.get("sinonimos") or [])] if node else []
        return DomainHit(
            node_id=hit.node_id,
            termo=termos[-1] if termos else (str(node.properties.get("termo")) if node else ""),
            nivel=str(payload.get("nivel") or ""),
            caminho=termos,
            caminho_ids=[str(i) for i in payload.get("caminho_ids") or []],
            score=float(hit.score),
            status=str(payload.get("status") or ""),
            sinonimos=sinonimos,
        )


def open_domain_search() -> DomainSearch:
    """Monta a ``DomainSearch`` de produção (grafo somente leitura + índice no Qdrant local).

    Não cria coleção nem grava nada.

    Raises:
        RuntimeError: Se ``KNOWLEDGE_READER_DATABASE_URL`` não está configurada.
    """
    from src.embeddings.reindex import _make_client
    from src.knowledge.factory import open_raw_graph_store

    store = open_raw_graph_store()
    return DomainSearch(store, SemanticIndex(store, _make_client(config.QDRANT_URL)))
