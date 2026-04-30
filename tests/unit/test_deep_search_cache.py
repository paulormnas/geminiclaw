"""Testes unitários para src/skills/search_deep/cache.py (PostgreSQL via mock)."""

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


@pytest.mark.unit
class TestDeepSearchCacheGet:
    def test_get_retorna_none_se_nao_encontrado(self, cache):
        """get() deve retornar None se a query não estiver no cache."""
        ctx, _ = _make_ctx(fetchone=None)
        with patch("src.skills.search_deep.cache.get_connection", return_value=ctx):
            result = cache.get("query inexistente")
        assert result is None

    def test_get_retorna_resultados_validos(self, cache):
        """get() deve retornar resultados quando a entrada existe e não expirou."""
        results = [{"url": "http://test.com", "content": "ok"}]
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        row = {"results": json.dumps(results), "expires_at": future}
        ctx, _ = _make_ctx(fetchone=row)
        with patch("src.skills.search_deep.cache.get_connection", return_value=ctx):
            result = cache.get("query")
        assert result == results

    def test_get_retorna_none_e_deleta_se_expirado(self, cache):
        """get() deve retornar None e deletar a entrada se expirou."""
        results = [{"url": "http://old.com"}]
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        row = {"results": json.dumps(results), "expires_at": past}

        # Primeiro get_connection retorna a row, segundo executa o DELETE
        ctx1, _ = _make_ctx(fetchone=row)
        ctx2, mock_conn2 = _make_ctx()

        with patch(
            "src.skills.search_deep.cache.get_connection",
            side_effect=[ctx1, ctx2]
        ):
            result = cache.get("query expirada")

        assert result is None
        sqls = [c[0][0] for c in mock_conn2.execute.call_args_list]
        assert any("DELETE" in s for s in sqls)


@pytest.mark.unit
class TestDeepSearchCacheSet:
    def test_set_chama_upsert(self, cache):
        """set() deve chamar INSERT ... ON CONFLICT."""
        ctx, mock_conn = _make_ctx()
        with patch("src.skills.search_deep.cache.get_connection", return_value=ctx):
            cache.set("query", [{"r": 1}], ttl_seconds=3600)
        sqls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert any("ON CONFLICT" in s for s in sqls)

    def test_set_inclui_query_e_results(self, cache):
        """set() deve passar a query e resultados corretamente para o SQL."""
        ctx, mock_conn = _make_ctx()
        results = [{"url": "http://example.com"}]
        with patch("src.skills.search_deep.cache.get_connection", return_value=ctx):
            cache.set("minha query", results, ttl_seconds=100)
        params = mock_conn.execute.call_args[0][1]
        assert "minha query" in params
        assert json.dumps(results) in params


@pytest.mark.unit
class TestDeepSearchCacheHash:
    def test_hash_e_consistente(self, cache):
        """A mesma query deve sempre gerar o mesmo hash."""
        h1 = cache._generate_hash("test query")
        h2 = cache._generate_hash("test query")
        assert h1 == h2

    def test_hash_diferente_por_filtros(self, cache):
        """Query com filtros diferentes devem gerar hashes diferentes."""
        h1 = cache._generate_hash("query", filters={"domain": "a"})
        h2 = cache._generate_hash("query", filters={"domain": "b"})
        assert h1 != h2

    def test_hash_normaliza_case(self, cache):
        """O hash deve ser insensível a maiúsculas/minúsculas (strip().lower())."""
        h1 = cache._generate_hash("  QUERY  ")
        h2 = cache._generate_hash("query")
        assert h1 == h2


@pytest.mark.unit
class TestDeepSearchCacheClearExpired:
    def test_clear_expired_chama_delete(self, cache):
        """clear_expired() deve executar DELETE com filtro de expires_at."""
        ctx, mock_conn = _make_ctx()
        with patch("src.skills.search_deep.cache.get_connection", return_value=ctx):
            cache.clear_expired()
        sql = mock_conn.execute.call_args[0][0]
        assert "DELETE" in sql
        assert "expires_at" in sql
