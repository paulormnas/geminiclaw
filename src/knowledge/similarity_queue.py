"""Fila de revisão de pares candidatos de similaridade (ADR 015 §6, fora do grafo).

Todo par na faixa "relacionado" (ou "duplicata") entra nesta fila — tabela
``similarity_queue`` no PostgreSQL — e **só vira aresta** ``SEMELHANTE_A``
quando o Curator o confirma (``GraphStore.create_edge``, fora do escopo deste
módulo). Nada é descartado por falta de tempo: a fila é revisada por
prioridade e o que não couber no orçamento da sessão espera.

Contém a interface ``SimilarityQueue`` e duas implementações:
``InMemorySimilarityQueue`` (testes) e ``PostgresSimilarityQueue``.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from src import config
from src.logger import get_logger

logger = get_logger(__name__)

TIPO_DUPLICATA = "duplicata"
TIPO_RELACIONADO = "relacionado"
STATUS_PENDENTE = "pendente"
STATUS_CONFIRMADO = "confirmado"
STATUS_DESCARTADO = "descartado"

# Revisão automática: pares pendentes cujo texto mudou viram histórico (não entram na calibração).
SYSTEM_REVIEWER = "sistema"
MOTIVO_TEXTO_ALTERADO = "texto alterado"

FAIXA_DUPLICATA = "duplicata"
FAIXA_RELACIONADO = "relacionado"
FAIXA_BAIXA = "baixa"


class QueueItemError(Exception):
    """Item da fila inexistente ou em estado que não admite a operação."""


@dataclass(frozen=True)
class Candidate:
    """Par candidato a entrar na fila (par não ordenado: ``node_a`` < ``node_b``).

    Attributes:
        node_a: Menor ID do par.
        node_b: Maior ID do par.
        label_a: Rótulo de ``node_a``.
        label_b: Rótulo de ``node_b``.
        tipo: ``duplicata`` ou ``relacionado``.
        score: Similaridade cosseno.
        entre_dominios: Domínios (nível ``area``) disjuntos.
        entre_projetos: ``projeto_id`` diferentes.
        prioridade: ``score × peso_evidencia × boost entre domínios``.
        text_hash_a: ``text_hash`` de ``node_a`` no momento da varredura.
        text_hash_b: ``text_hash`` de ``node_b`` no momento da varredura.
        embedding_model: Modelo de embedding usado.
        embedding_version: Versão do modelo de embedding.
    """

    node_a: str
    node_b: str
    label_a: str
    label_b: str
    tipo: str
    score: float
    entre_dominios: bool
    entre_projetos: bool
    prioridade: float
    text_hash_a: str
    text_hash_b: str
    embedding_model: str
    embedding_version: str


@dataclass(frozen=True)
class QueueItem:
    """Registro da fila (um ``Candidate`` + estado de revisão)."""

    id: int
    candidate: Candidate
    status: str = STATUS_PENDENTE
    criado_em: datetime | None = None
    revisado_em: datetime | None = None
    revisado_por: str | None = None
    motivo: str | None = None


@dataclass(frozen=True)
class BandRate:
    """Taxa de confirmação numa faixa, para calibração.

    Attributes:
        tipo: ``duplicata`` ou ``relacionado``.
        faixa: ``duplicata``, ``relacionado`` (>= limite do mesmo domínio) ou ``baixa`` (0,60–0,70).
        confirmados: Pares confirmados na janela.
        descartados: Pares descartados na janela.
    """

    tipo: str
    faixa: str
    confirmados: int
    descartados: int

    @property
    def avaliados(self) -> int:
        """Pares revisados (confirmados + descartados)."""
        return self.confirmados + self.descartados

    @property
    def taxa(self) -> float | None:
        """Fração confirmada, ou ``None`` se nada foi revisado na janela."""
        return None if self.avaliados == 0 else self.confirmados / self.avaliados


def classify_band(tipo: str, score: float, low_band_max: float | None = None) -> str:
    """Classifica um par numa faixa de calibração.

    Args:
        tipo: Tipo do par.
        score: Similaridade.
        low_band_max: Fronteira superior da faixa baixa (padrão ``SIM_RELATED_MIN_SAME_DOMAIN``).
    """
    if tipo == TIPO_DUPLICATA:
        return FAIXA_DUPLICATA
    limit = config.SIM_RELATED_MIN_SAME_DOMAIN if low_band_max is None else low_band_max
    return FAIXA_BAIXA if score < limit else FAIXA_RELACIONADO


class SimilarityQueue(ABC):
    """Interface da fila de similaridade."""

    @abstractmethod
    def enqueue(self, candidate: Candidate) -> bool:
        """Insere o par, a menos que já esteja registrado com os mesmos textos e modelo.

        Um par já avaliado (``confirmado``/``descartado``) ou ainda pendente
        não volta enquanto ``text_hash_a`` e ``text_hash_b`` forem os mesmos;
        se um texto mudou, entra como **novo registro** e o antigo permanece
        como histórico. Se o par ainda está **pendente** e a nova varredura
        traz ``entre_dominios``/``prioridade`` diferentes (ex.: o domínio foi
        atribuído depois da criação do nó), o registro pendente é atualizado.
        Ao inserir um registro novo para um par cujo texto mudou, os registros
        **pendentes** antigos do mesmo par/modelo viram ``descartado`` com
        ``revisado_por="sistema"`` e motivo "texto alterado" (histórico, fora da
        calibração): o Curator nunca revisa um par obsoleto.

        Returns:
            True se inseriu um novo registro; False se o par já estava registrado.
        """

    @abstractmethod
    def next_batch(self, limit: int) -> list[QueueItem]:
        """Itens ``pendente`` por prioridade decrescente (maior primeiro)."""

    @abstractmethod
    def mark_confirmed(self, item_id: int, by: str, motivo: str | None = None) -> None:
        """Marca um item pendente como ``confirmado`` (não cria a aresta).

        Raises:
            QueueItemError: Item inexistente ou não pendente.
        """

    @abstractmethod
    def mark_discarded(self, item_id: int, by: str, motivo: str | None = None) -> None:
        """Marca um item pendente como ``descartado``.

        Raises:
            QueueItemError: Item inexistente ou não pendente.
        """

    @abstractmethod
    def confirmation_rate(self, window_days: int) -> list[BandRate]:
        """Taxa de confirmação por tipo e faixa dos itens revisados nos últimos ``window_days`` dias."""

    @abstractmethod
    def pending_count(self) -> int:
        """Quantidade de itens ``pendente``."""


def _dedup_key(c: Candidate) -> tuple[str, ...]:
    return (c.node_a, c.node_b, c.embedding_model, c.embedding_version, c.text_hash_a, c.text_hash_b)


class InMemorySimilarityQueue(SimilarityQueue):
    """Fila em memória, para testes unitários (mesmas regras da implementação PostgreSQL)."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._items: dict[int, QueueItem] = {}
        self._keys: dict[tuple[str, ...], int] = {}
        self._next_id = 1
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()

    def enqueue(self, candidate: Candidate) -> bool:
        with self._lock:
            key = _dedup_key(candidate)
            existing_id = self._keys.get(key)
            if existing_id is not None:
                existing = self._items[existing_id]
                if existing.status == STATUS_PENDENTE and (
                    existing.candidate.entre_dominios != candidate.entre_dominios
                    or existing.candidate.prioridade != candidate.prioridade
                ):
                    self._items[existing_id] = replace(existing, candidate=candidate)
                return False
            item = QueueItem(id=self._next_id, candidate=candidate, criado_em=self._clock())
            self._keys[key] = item.id
            for old_id, old in list(self._items.items()):
                oc = old.candidate
                if (
                    old.status == STATUS_PENDENTE
                    and (oc.node_a, oc.node_b, oc.embedding_model, oc.embedding_version)
                    == (candidate.node_a, candidate.node_b, candidate.embedding_model, candidate.embedding_version)
                ):
                    self._items[old_id] = replace(
                        old, status=STATUS_DESCARTADO, revisado_em=self._clock(),
                        revisado_por=SYSTEM_REVIEWER, motivo=MOTIVO_TEXTO_ALTERADO,
                    )
            self._items[item.id] = item
            self._next_id += 1
            return True

    def next_batch(self, limit: int) -> list[QueueItem]:
        pending = [i for i in self._items.values() if i.status == STATUS_PENDENTE]
        pending.sort(key=lambda i: (-i.candidate.prioridade, i.id))
        return pending[:limit]

    def _review(self, item_id: int, status: str, by: str, motivo: str | None) -> None:
        item = self._items.get(item_id)
        if item is None or item.status != STATUS_PENDENTE:
            raise QueueItemError(f"Item {item_id} inexistente ou não pendente.")
        self._items[item_id] = replace(
            item, status=status, revisado_em=self._clock(), revisado_por=by, motivo=motivo
        )

    def mark_confirmed(self, item_id: int, by: str, motivo: str | None = None) -> None:
        self._review(item_id, STATUS_CONFIRMADO, by, motivo)

    def mark_discarded(self, item_id: int, by: str, motivo: str | None = None) -> None:
        self._review(item_id, STATUS_DESCARTADO, by, motivo)

    def confirmation_rate(self, window_days: int) -> list[BandRate]:
        since = self._clock() - timedelta(days=window_days)
        counts: dict[tuple[str, str], list[int]] = {}
        for item in self._items.values():
            if (
                item.status == STATUS_PENDENTE
                or item.revisado_em is None
                or item.revisado_em < since
                or item.revisado_por == SYSTEM_REVIEWER
            ):
                continue
            c = item.candidate
            slot = counts.setdefault((c.tipo, classify_band(c.tipo, c.score)), [0, 0])
            slot[0 if item.status == STATUS_CONFIRMADO else 1] += 1
        return sorted(
            (BandRate(tipo, faixa, conf, desc) for (tipo, faixa), (conf, desc) in counts.items()),
            key=lambda r: (r.tipo, r.faixa),
        )

    def pending_count(self) -> int:
        return sum(1 for i in self._items.values() if i.status == STATUS_PENDENTE)


_COLUMNS = (
    "node_a, node_b, label_a, label_b, tipo, score, entre_dominios, entre_projetos, prioridade, "
    "text_hash_a, text_hash_b, embedding_model, embedding_version"
)


class PostgresSimilarityQueue(SimilarityQueue):
    """Fila persistida na tabela ``similarity_queue`` (``scripts/init_db.sql``)."""

    def __init__(self, connection_factory: Callable[[], Any] | None = None) -> None:
        """Inicializa a fila.

        Args:
            connection_factory: Callable que devolve um context manager de conexão
                psycopg com ``dict_row``. Padrão: ``src.db.get_connection``.
        """
        self._connection_factory = connection_factory

    def _connection(self):
        if self._connection_factory is not None:
            return self._connection_factory()
        from src.db import get_connection

        return get_connection()

    def enqueue(self, candidate: Candidate) -> bool:
        c = candidate
        with self._connection() as conn:
            row = conn.execute(
                f"""
                INSERT INTO similarity_queue ({_COLUMNS})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (node_a, node_b, embedding_model, embedding_version, text_hash_a, text_hash_b)
                DO UPDATE SET entre_dominios = EXCLUDED.entre_dominios, prioridade = EXCLUDED.prioridade
                WHERE similarity_queue.status = 'pendente'
                  AND (similarity_queue.entre_dominios, similarity_queue.prioridade)
                      IS DISTINCT FROM (EXCLUDED.entre_dominios, EXCLUDED.prioridade)
                RETURNING (xmax = 0) AS inserido
                """,
                (
                    c.node_a, c.node_b, c.label_a, c.label_b, c.tipo, c.score, c.entre_dominios,
                    c.entre_projetos, c.prioridade, c.text_hash_a, c.text_hash_b,
                    c.embedding_model, c.embedding_version,
                ),
            ).fetchone()
        inserted = row is not None and bool(row["inserido"])
        if inserted:
            with self._connection() as conn:
                conn.execute(
                    """
                    UPDATE similarity_queue
                    SET status = 'descartado', revisado_em = now(), revisado_por = %s, motivo = %s
                    WHERE node_a = %s AND node_b = %s AND embedding_model = %s AND embedding_version = %s
                      AND status = 'pendente'
                      AND (text_hash_a, text_hash_b) <> (%s, %s)
                    """,
                    (SYSTEM_REVIEWER, MOTIVO_TEXTO_ALTERADO, c.node_a, c.node_b, c.embedding_model,
                     c.embedding_version, c.text_hash_a, c.text_hash_b),
                )
        return inserted

    def next_batch(self, limit: int) -> list[QueueItem]:
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT id, {_COLUMNS}, status, criado_em, revisado_em, revisado_por, motivo
                FROM similarity_queue
                WHERE status = 'pendente'
                ORDER BY prioridade DESC, id
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [
            QueueItem(
                id=r["id"],
                candidate=Candidate(
                    node_a=r["node_a"], node_b=r["node_b"], label_a=r["label_a"], label_b=r["label_b"],
                    tipo=r["tipo"], score=float(r["score"]), entre_dominios=r["entre_dominios"],
                    entre_projetos=r["entre_projetos"], prioridade=float(r["prioridade"]),
                    text_hash_a=r["text_hash_a"], text_hash_b=r["text_hash_b"],
                    embedding_model=r["embedding_model"], embedding_version=r["embedding_version"],
                ),
                status=r["status"], criado_em=r["criado_em"], revisado_em=r["revisado_em"],
                revisado_por=r["revisado_por"], motivo=r["motivo"],
            )
            for r in rows
        ]

    def _review(self, item_id: int, status: str, by: str, motivo: str | None) -> None:
        with self._connection() as conn:
            row = conn.execute(
                """
                UPDATE similarity_queue
                SET status = %s, revisado_em = now(), revisado_por = %s, motivo = %s
                WHERE id = %s AND status = 'pendente'
                RETURNING id
                """,
                (status, by, motivo, item_id),
            ).fetchone()
        if row is None:
            raise QueueItemError(f"Item {item_id} inexistente ou não pendente.")

    def mark_confirmed(self, item_id: int, by: str, motivo: str | None = None) -> None:
        self._review(item_id, STATUS_CONFIRMADO, by, motivo)

    def mark_discarded(self, item_id: int, by: str, motivo: str | None = None) -> None:
        self._review(item_id, STATUS_DESCARTADO, by, motivo)

    def confirmation_rate(self, window_days: int) -> list[BandRate]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT tipo,
                       CASE WHEN tipo = 'duplicata' THEN 'duplicata'
                            WHEN score::numeric < %s::numeric THEN 'baixa'
                            ELSE 'relacionado' END AS faixa,
                       count(*) FILTER (WHERE status = 'confirmado') AS confirmados,
                       count(*) FILTER (WHERE status = 'descartado') AS descartados
                FROM similarity_queue
                WHERE status IN ('confirmado', 'descartado')
                  AND revisado_em >= now() - make_interval(days => %s)
                  AND revisado_por IS DISTINCT FROM 'sistema'
                GROUP BY 1, 2
                ORDER BY 1, 2
                """,
                (config.SIM_RELATED_MIN_SAME_DOMAIN, window_days),
            ).fetchall()
        return [BandRate(r["tipo"], r["faixa"], int(r["confirmados"]), int(r["descartados"])) for r in rows]

    def pending_count(self) -> int:
        with self._connection() as conn:
            row = conn.execute("SELECT count(*) AS n FROM similarity_queue WHERE status = 'pendente'").fetchone()
        return int(row["n"])
