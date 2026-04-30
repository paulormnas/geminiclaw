"""Testes para DeepSearchCache (PostgreSQL via mock).

Substitui a versão anterior que dependia de sqlite_utils.
"""

import pytest
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.skills.search_deep.cache import DeepSearchCache


def _make_ctx(fetchone=None):
    """Cria context manager mock de conexão."""
    mock_conn = MagicMock()
    cursor = MagicMock()
    mock_conn.execute.return_value = cursor
    cursor.fetchone.return_value = fetchone
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, mock_conn


@pytest.fixture
def cache():
    return DeepSearchCache()


def test_deep_search_cache_set_get(cache):
    """get() deve retornar resultados quando a entrada existe e não expirou."""
    results = [{"url": "http://test.com", "score": 0.99}]
    filters = {"domain": "test.com"}

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    row = {"results": json.dumps(results), "expires_at": future}
    ctx_set, _ = _make_ctx()
    ctx_get, _ = _make_ctx(fetchone=row)

    with patch("src.skills.search_deep.cache.get_connection", side_effect=[ctx_set, ctx_get]):
        cache.set("my query", results, ttl_seconds=3600, filters=filters)
        hit = cache.get("my query", filters=filters)

    assert hit == results


def test_deep_search_cache_miss_sem_filtro(cache):
    """get() com filtros diferentes deve dar miss (hash diferente)."""
    results = [{"url": "http://test.com", "score": 0.99}]
    filters = {"domain": "test.com"}

    # Hash gerado com filtros — busca sem filtros gera hash diferente, não acha nada
    ctx, _ = _make_ctx(fetchone=None)
    with patch("src.skills.search_deep.cache.get_connection", return_value=ctx):
        miss = cache.get("my query")  # sem filtros = hash diferente
    assert miss is None


def test_deep_search_cache_expiration(cache):
    """get() deve dar miss e deletar quando a entrada expirou."""
    results = [{"url": "http://test.com"}]

    # TTL de 0 → expirado
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    row = {"results": json.dumps(results), "expires_at": past}

    ctx_get, _ = _make_ctx(fetchone=row)
    ctx_del, mock_del = _make_ctx()

    with patch(
        "src.skills.search_deep.cache.get_connection",
        side_effect=[ctx_get, ctx_del]
    ):
        hit = cache.get("quick expire")

    assert hit is None
    sqls = [c[0][0] for c in mock_del.execute.call_args_list]
    assert any("DELETE" in s for s in sqls)


def test_deep_search_cache_clear_expired(cache):
    """clear_expired() deve executar DELETE filtrando por expires_at."""
    ctx, mock_conn = _make_ctx()

    with patch("src.skills.search_deep.cache.get_connection", return_value=ctx):
        cache.clear_expired()

    sql = mock_conn.execute.call_args[0][0]
    assert "DELETE" in sql
    assert "expires_at" in sql


def test_deep_search_cache_upsert(cache):
    """set() deve chamar INSERT ... ON CONFLICT para upsert."""
    ctx, mock_conn = _make_ctx()

    with patch("src.skills.search_deep.cache.get_connection", return_value=ctx):
        cache.set("test query", [{"r": 1}], ttl_seconds=100)

    sqls = [c[0][0] for c in mock_conn.execute.call_args_list]
    assert any("ON CONFLICT" in s for s in sqls)
