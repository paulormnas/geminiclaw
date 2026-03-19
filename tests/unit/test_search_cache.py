import pytest
import time
from unittest.mock import patch

from agents.researcher.cache import SearchCache


@pytest.mark.unit
class TestSearchCache:
    """Testes do cache de resultados de busca."""

    def test_set_and_get_within_ttl(self) -> None:
        """get retorna valor quando dentro do TTL."""
        cache = SearchCache(ttl_seconds=60)
        cache.set("python frameworks", "Django, Flask, FastAPI")

        result = cache.get("python frameworks")
        assert result == "Django, Flask, FastAPI"

    def test_get_returns_none_for_unknown_key(self) -> None:
        """get retorna None para query não cacheada."""
        cache = SearchCache(ttl_seconds=60)
        result = cache.get("chave inexistente")
        assert result is None

    def test_get_returns_none_after_expiration(self) -> None:
        """get retorna None quando o TTL expirou."""
        cache = SearchCache(ttl_seconds=1)
        cache.set("query expirada", "resultado")

        # Manipula diretamente o created_at da entrada para simular expiração
        normalized = "query expirada"
        entry = cache._store[normalized]
        entry.created_at = time.monotonic() - 2  # 2s atrás, TTL é 1s

        result = cache.get("query expirada")
        assert result is None

    def test_different_keys_return_different_results(self) -> None:
        """Chaves diferentes retornam resultados diferentes."""
        cache = SearchCache(ttl_seconds=60)
        cache.set("query a", "resultado a")
        cache.set("query b", "resultado b")

        assert cache.get("query a") == "resultado a"
        assert cache.get("query b") == "resultado b"

    def test_clear_removes_all_entries(self) -> None:
        """clear remove todas as entradas do cache."""
        cache = SearchCache(ttl_seconds=60)
        cache.set("q1", "r1")
        cache.set("q2", "r2")

        cache.clear()

        assert cache.get("q1") is None
        assert cache.get("q2") is None

    def test_query_normalization(self) -> None:
        """Queries são normalizadas (lowercase + strip)."""
        cache = SearchCache(ttl_seconds=60)
        cache.set("  Python Frameworks  ", "resultado")

        assert cache.get("python frameworks") == "resultado"
        assert cache.get("  PYTHON FRAMEWORKS  ") == "resultado"

    def test_overwrite_existing_key(self) -> None:
        """set sobrescreve valor existente para a mesma chave."""
        cache = SearchCache(ttl_seconds=60)
        cache.set("query", "resultado antigo")
        cache.set("query", "resultado novo")

        assert cache.get("query") == "resultado novo"

    def test_ttl_property(self) -> None:
        """Propriedade ttl retorna o valor configurado."""
        cache = SearchCache(ttl_seconds=300)
        assert cache.ttl == 300

    def test_default_ttl_from_config(self) -> None:
        """TTL padrão vem de SEARCH_CACHE_TTL_SECONDS."""
        from src.config import SEARCH_CACHE_TTL_SECONDS
        cache = SearchCache()
        assert cache.ttl == SEARCH_CACHE_TTL_SECONDS
