import pytest
import shutil
import os
from src.skills.search_deep.cache import DeepSearchCache

@pytest.fixture
def cache():
    db_path = "/tmp/test_cache.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    c = DeepSearchCache(db_path=db_path)
    yield c
    
    if os.path.exists(db_path):
        os.remove(db_path)

@pytest.mark.unit
def test_cache_set_get(cache):
    query = "test query"
    results = [{"content": "hit", "url": "http://test.com"}]
    
    cache.set(query, results, ttl_seconds=60)
    
    cached = cache.get(query)
    assert cached == results
    
    # Diferente query
    assert cache.get("other") is None

@pytest.mark.unit
def test_cache_expiration(cache):
    import time
    query = "expiring query"
    results = [{"content": "gone"}]
    
    # Seta com TTL de 1 segundo
    cache.set(query, results, ttl_seconds=1)
    assert cache.get(query) == results
    
    # Espera 1.1s
    import asyncio
    time.sleep(1.1)
    
    assert cache.get(query) is None
