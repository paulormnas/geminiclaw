import pytest
import sqlite_utils
from src.skills.search_deep.cache import DeepSearchCache

@pytest.fixture
def cache(tmp_path):
    db_path = tmp_path / "deep_search.db"
    return DeepSearchCache(db_path=str(db_path))

def test_deep_search_cache_set_get(cache):
    results = [{"url": "http://test.com", "score": 0.99}]
    filters = {"domain": "test.com"}
    
    cache.set("my query", results, ttl_seconds=3600, filters=filters)
    
    # Busca exata
    hit = cache.get("my query", filters=filters)
    assert hit == results
    
    # Busca sem filtro deve dar miss
    miss = cache.get("my query")
    assert miss is None
    
    # Busca com query diferente deve dar miss
    miss2 = cache.get("other query", filters=filters)
    assert miss2 is None

def test_deep_search_cache_expiration(cache):
    results = [{"url": "http://test.com"}]
    
    # Seta com TTL = 0 (expira imediatamente)
    cache.set("quick expire", results, ttl_seconds=0)
    
    # O get deve dar miss e limpar a entrada expirada
    hit = cache.get("quick expire")
    assert hit is None
    
    # Garantir que a entrada foi deletada do banco
    count = cache.db.execute("SELECT count(*) FROM deep_search_cache").fetchone()[0]
    assert count == 0

def test_deep_search_cache_clear_expired(cache):
    results = [{"url": "http://test.com"}]
    
    # TTL = -1 segundo
    cache.set("past", results, ttl_seconds=-1)
    # TTL = 1000 segundos
    cache.set("future", results, ttl_seconds=1000)
    
    cache.clear_expired()
    count = cache.db.execute("SELECT count(*) FROM deep_search_cache").fetchone()[0]
    assert count == 1 # Apenas o "future" sobreviveu
