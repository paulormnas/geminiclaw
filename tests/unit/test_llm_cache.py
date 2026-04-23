import pytest
import sqlite3
import os
import time
from unittest.mock import patch

from src.llm_cache import LLMResponseCache

import tempfile

@pytest.fixture
def memory_cache():
    """Retorna um cache em arquivo temporário limpo."""
    os.environ["LLM_CACHE_ENABLED"] = "true"
    os.environ["LLM_CACHE_TTL_SECONDS"] = "3600"
    os.environ["LLM_CACHE_MAX_ENTRIES"] = "1000"
    fd, path = tempfile.mkstemp()
    os.close(fd)
    cache = LLMResponseCache(db_path=path)
    yield cache
    os.remove(path)

def test_cache_miss_empty(memory_cache):
    assert memory_cache.get("Hello", "gemini-3-flash") is None
    stats = memory_cache.stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 0

def test_cache_set_and_get(memory_cache):
    prompt = "Translate Hello to Portuguese"
    model = "gemini-3-flash"
    response = "Olá"
    
    memory_cache.set(prompt, model, response)
    
    cached = memory_cache.get(prompt, model)
    assert cached == response
    
    stats = memory_cache.stats()
    assert stats["hits"] == 1

def test_cache_different_model_miss(memory_cache):
    prompt = "Translate Hello to Portuguese"
    response = "Olá"
    
    memory_cache.set(prompt, "gemini-3-flash", response)
    
    # Modelo diferente deve dar miss
    cached = memory_cache.get(prompt, "gemini-3-pro")
    assert cached is None
    
def test_cache_ttl_expiration(memory_cache):
    prompt = "Test TTL"
    model = "gemini-3-flash"
    
    memory_cache.set(prompt, model, "response")
    
    # Mock time.time para simular passagem de 3601 segundos
    with patch("time.time", return_value=time.time() + 3601):
        cached = memory_cache.get(prompt, model)
        assert cached is None # Deve expirar e retornar None

def test_cache_max_entries_eviction(memory_cache):
    # Força max_entries para 5 para testar eviction
    memory_cache.max_entries = 5
    
    for i in range(10):
        # Pequeno sleep ou avanço de tempo para garantir ordenação por timestamp
        with patch("time.time", return_value=time.time() + i):
            memory_cache.set(f"Prompt {i}", "model", f"Response {i}")
            
    # Como o max_entries é 5, inserimos 10, então os primeiros 5 (0 a 4) foram removidos
    assert memory_cache.get("Prompt 0", "model") is None
    assert memory_cache.get("Prompt 4", "model") is None
    assert memory_cache.get("Prompt 5", "model") == "Response 5"
    assert memory_cache.get("Prompt 9", "model") == "Response 9"
    
    # Contar diretamente no banco para garantir
    with memory_cache._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM llm_cache")
        count = cursor.fetchone()[0]
        assert count == 5
