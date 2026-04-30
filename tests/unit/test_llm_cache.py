"""Testes unitários para src/llm_cache.py (PostgreSQL via mock)."""

import pytest
import os
import time
from unittest.mock import MagicMock, patch

from src.llm_cache import LLMResponseCache


def _make_ctx(fetchone=None, fetchall=None):
    """Cria context manager mock de conexão."""
    mock_conn = MagicMock()
    cursor = MagicMock()
    mock_conn.execute.return_value = cursor
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall or []
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, mock_conn


@pytest.fixture(autouse=True)
def enable_cache(monkeypatch):
    """Garante que o cache está habilitado para cada teste."""
    monkeypatch.setenv("LLM_CACHE_ENABLED", "true")
    monkeypatch.setenv("LLM_CACHE_TTL_SECONDS", "3600")
    monkeypatch.setenv("LLM_CACHE_MAX_ENTRIES", "1000")


@pytest.fixture
def cache():
    return LLMResponseCache()


@pytest.mark.unit
class TestLLMCacheGet:
    def test_get_retorna_none_em_miss(self, cache):
        """get() deve retornar None quando a chave não existe."""
        ctx, _ = _make_ctx(fetchone=None)
        with patch("src.llm_cache.get_connection", return_value=ctx):
            result = cache.get("prompt", "model")
        assert result is None

    def test_get_retorna_resposta_em_hit(self, cache):
        """get() deve retornar a resposta cacheada quando a chave existe e está válida."""
        row = {"response": "Olá", "timestamp": time.time() - 10}
        ctx, _ = _make_ctx(fetchone=row)
        with patch("src.llm_cache.get_connection", return_value=ctx):
            result = cache.get("prompt", "model")
        assert result == "Olá"

    def test_get_retorna_none_se_expirado(self, cache):
        """get() deve retornar None e deletar se o registro expirou."""
        old_time = time.time() - 7200  # 2 horas atrás (TTL = 3600)
        row = {"response": "antiga", "timestamp": old_time}
        ctx, mock_conn = _make_ctx(fetchone=row)
        with patch("src.llm_cache.get_connection", return_value=ctx):
            result = cache.get("prompt", "model")
        assert result is None
        sqls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert any("DELETE" in s for s in sqls)

    def test_get_retorna_none_quando_desabilitado(self):
        """get() deve retornar None imediatamente quando cache está desabilitado."""
        os.environ["LLM_CACHE_ENABLED"] = "false"
        cache = LLMResponseCache()
        result = cache.get("prompt", "model")
        os.environ["LLM_CACHE_ENABLED"] = "true"
        assert result is None


@pytest.mark.unit
class TestLLMCacheSet:
    def test_set_chama_upsert(self, cache):
        """set() deve chamar INSERT ... ON CONFLICT."""
        count_row = {"cnt": 0}
        ctx, mock_conn = _make_ctx(fetchone=count_row)
        with patch("src.llm_cache.get_connection", return_value=ctx):
            cache.set("prompt", "model", "response")
        sqls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert any("ON CONFLICT" in s for s in sqls)

    def test_set_eviction_quando_excede_limite(self, cache):
        """set() deve executar DELETE quando count > max_entries."""
        cache.max_entries = 5
        count_row = {"cnt": 10}  # Acima do limite
        ctx, mock_conn = _make_ctx(fetchone=count_row)
        with patch("src.llm_cache.get_connection", return_value=ctx):
            cache.set("prompt", "model", "resp")
        sqls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert any("DELETE" in s for s in sqls)

    def test_set_nao_faz_nada_quando_desabilitado(self):
        """set() não deve chamar get_connection quando cache está desabilitado."""
        os.environ["LLM_CACHE_ENABLED"] = "false"
        cache = LLMResponseCache()
        with patch("src.llm_cache.get_connection") as mock_gc:
            cache.set("prompt", "model", "response")
        mock_gc.assert_not_called()
        os.environ["LLM_CACHE_ENABLED"] = "true"


@pytest.mark.unit
class TestLLMCacheStats:
    def test_stats_retorna_metricas(self, cache):
        """stats() deve retornar dicionário com hits, misses e hit_rate."""
        row = {"hits": 10, "misses": 5}
        ctx, _ = _make_ctx(fetchone=row)
        with patch("src.llm_cache.get_connection", return_value=ctx):
            s = cache.stats()
        assert s["hits"] == 10
        assert s["misses"] == 5
        assert s["hit_rate"] == pytest.approx(10 / 15, rel=1e-4)
        assert s["total_requests"] == 15

    def test_stats_retorna_disabled_quando_desabilitado(self):
        """stats() deve retornar enabled=False quando cache está desabilitado."""
        os.environ["LLM_CACHE_ENABLED"] = "false"
        cache = LLMResponseCache()
        result = cache.stats()
        os.environ["LLM_CACHE_ENABLED"] = "true"
        assert result == {"enabled": False}


@pytest.mark.unit
class TestLLMCacheHash:
    def test_hash_diferente_por_modelo(self, cache):
        """Prompts iguais com modelos diferentes devem gerar hashes diferentes."""
        h1 = cache._generate_hash("hello", "model-a")
        h2 = cache._generate_hash("hello", "model-b")
        assert h1 != h2

    def test_hash_consistente(self, cache):
        """O mesmo prompt+model sempre gera o mesmo hash."""
        h1 = cache._generate_hash("hello", "gemini")
        h2 = cache._generate_hash("hello", "gemini")
        assert h1 == h2

    def test_hash_normaliza_espacos(self, cache):
        """Prompt com espaços extras deve gerar o mesmo hash após strip."""
        h1 = cache._generate_hash("  hello  ", "model")
        h2 = cache._generate_hash("hello", "model")
        assert h1 == h2
