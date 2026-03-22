import pytest
import time
from unittest.mock import patch
from src.skills.search_quick.cache import SearchCache, SearchResult

@pytest.fixture
def cache():
    return SearchCache(ttl=1)  # 1 segundo de TTL para testes

@pytest.mark.unit
class TestSearchCache:
    """Testes abrangentes do cache de resultados de busca (S1)."""

    def test_set_and_get_within_ttl(self, cache):
        """get retorna valor quando dentro do TTL."""
        results = [SearchResult(title="T", url="U", snippet="S")]
        cache.set("python frameworks", results)

        result = cache.get("python frameworks")
        assert result == results

    def test_get_returns_none_for_unknown_key(self, cache):
        """get retorna None para query não cacheada."""
        result = cache.get("chave inexistente")
        assert result is None

    def test_get_returns_none_after_expiration(self, cache):
        """get retorna None quando o TTL expirou."""
        cache.set("query expirada", [SearchResult(title="T", url="U", snippet="S")])

        # Manipula diretamente o timestamp da entrada para simular expiração
        # A chave é um hash SHA-256 no novo sistema
        key = cache._get_key("query expirada")
        entry = cache._cache[key]
        entry["timestamp"] = time.monotonic() - 2  # 2s atrás, TTL é 1s

        result = cache.get("query expirada")
        assert result is None

    def test_different_keys_return_different_results(self, cache):
        """Chaves diferentes retornam resultados diferentes."""
        res_a = [SearchResult(title="A", url="UA", snippet="SA")]
        res_b = [SearchResult(title="B", url="UB", snippet="SB")]
        cache.set("query a", res_a)
        cache.set("query b", res_b)

        assert cache.get("query a") == res_a
        assert cache.get("query b") == res_b

    def test_clear_removes_all_entries(self, cache):
        """clear remove todas as entradas do cache."""
        cache.set("q1", [])
        cache.set("q2", [])

        cache.clear()

        assert cache.get("q1") is None
        assert cache.get("q2") is None

    def test_query_normalization(self, cache):
        """Queries são normalizadas (lowercase + strip)."""
        results = [SearchResult(title="T", url="U", snippet="S")]
        cache.set("  Python Frameworks  ", results)

        assert cache.get("python frameworks") == results
        assert cache.get("  PYTHON FRAMEWORKS  ") == results

    def test_overwrite_existing_key(self, cache):
        """set sobrescreve valor existente para a mesma chave."""
        res1 = [SearchResult(title="Old", url="U", snippet="S")]
        res2 = [SearchResult(title="New", url="U", snippet="S")]
        cache.set("query", res1)
        cache.set("query", res2)

        assert cache.get("query") == res2

    def test_ttl_property(self):
        """Propriedade ttl retorna o valor configurado."""
        cache = SearchCache(ttl=300)
        assert cache.ttl == 300

    def test_default_ttl_from_config(self):
        """TTL padrão vem de SEARCH_CACHE_TTL_SECONDS do src.config."""
        from src.config import SEARCH_CACHE_TTL_SECONDS
        cache = SearchCache()
        assert cache.ttl == SEARCH_CACHE_TTL_SECONDS
