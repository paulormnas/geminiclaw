"""Integração de ``PostgresSimilarityQueue`` com um PostgreSQL real.

Exige a tabela ``similarity_queue`` (``scripts/init_db.sql``) no banco de
``DATABASE_URL``; sem banco acessível ou sem a tabela, o módulo é pulado.
Usa apenas linhas próprias (``node_a`` com prefixo ``itest-``) e as remove ao final.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import pytest

from src.knowledge.similarity_queue import Candidate, PostgresSimilarityQueue, QueueItemError


def _connect():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3, row_factory=dict_row, autocommit=True)


def _table_ready() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql://"):
        return False
    try:
        with _connect() as conn:
            return conn.execute("SELECT to_regclass('public.similarity_queue') AS t").fetchone()["t"] is not None
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _table_ready(), reason="PostgreSQL com a tabela similarity_queue indisponível."),
]


@pytest.fixture
def queue():
    prefix = f"itest-{uuid.uuid4().hex[:8]}"

    @contextmanager
    def factory():
        with _connect() as conn:
            yield conn

    yield prefix, PostgresSimilarityQueue(factory)
    with _connect() as conn:
        conn.execute("DELETE FROM similarity_queue WHERE node_a LIKE %s", (f"{prefix}%",))


def _cand(prefix: str, suffix: str, **kw) -> Candidate:
    base = dict(
        node_a=f"{prefix}-{suffix}-a", node_b=f"{prefix}-{suffix}-b", label_a="Problema", label_b="Problema",
        tipo="relacionado", score=0.8, entre_dominios=False, entre_projetos=False, prioridade=0.4,
        text_hash_a="ha", text_hash_b="hb", embedding_model="m", embedding_version="1",
    )
    base.update(kw)
    return Candidate(**base)


def test_fluxo_completo_da_fila(queue):
    prefix, q = queue
    assert q.enqueue(_cand(prefix, "x")) is True
    assert q.enqueue(_cand(prefix, "x")) is False  # mesmo par, mesmos textos
    assert q.enqueue(_cand(prefix, "y", prioridade=0.9, entre_dominios=True)) is True

    mine = [i for i in q.next_batch(1000) if i.candidate.node_a.startswith(prefix)]
    assert [i.candidate.node_a.split("-")[2] for i in mine] == ["y", "x"]  # prioridade decrescente

    q.mark_discarded(mine[1].id, "pesquisador", "irrelevante")
    assert q.enqueue(_cand(prefix, "x")) is False  # descartado não volta com os mesmos textos
    assert q.enqueue(_cand(prefix, "x", text_hash_a="mudou")) is True  # texto mudou: novo registro
    with pytest.raises(QueueItemError):
        q.mark_confirmed(mine[1].id, "pesquisador")
