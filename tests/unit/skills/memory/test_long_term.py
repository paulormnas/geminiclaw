import pytest
import sqlite3
import os
from pathlib import Path
from src.skills.memory.long_term import LongTermMemory, LongTermMemoryEntry

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_memory.db"
    return str(db_path)

@pytest.fixture
def memory(temp_db):
    return LongTermMemory(temp_db)

def test_write_and_read(memory):
    key = "user_pref"
    value = "likes_dark_mode"
    source = "agent_1"
    
    entry = memory.write(key, value, source, importance=0.8, tags=["pref", "ui"])
    assert entry.key == key
    assert entry.value == value
    assert entry.importance == 0.8
    assert "pref" in entry.tags
    
    read_entry = memory.read(key)
    assert read_entry is not None
    assert read_entry.value == value
    assert read_entry.use_count == 1

def test_search_by_tags(memory):
    memory.write("k1", "v1", "s", tags=["t1", "t2"])
    memory.write("k2", "v2", "s", tags=["t2", "t3"])
    memory.write("k3", "v3", "s", tags=["t1"])
    
    results = memory.search(tags=["t2"])
    assert len(results) == 2
    
    results = memory.search(tags=["t1", "t2"])
    assert len(results) == 3

def test_importance_update(memory):
    memory.write("imp_test", "val", "s", importance=0.5)
    memory.update_importance("imp_test", 0.2)
    
    entry = memory.read("imp_test")
    assert entry.importance == pytest.approx(0.7)
    
    memory.update_importance("imp_test", -1.0) # Deve limitar em 0.0
    entry = memory.read("imp_test")
    assert entry.importance == 0.0

def test_summarize_for_context(memory):
    memory.write("high_imp", "very important", "s", importance=0.9)
    memory.write("low_imp", "not so much", "s", importance=0.4)
    
    summary = memory.summarize_for_context()
    assert "high_imp: very important" in summary
    assert "low_imp" not in summary

def test_forget(memory):
    memory.write("to_delete", "val", "s")
    assert memory.read("to_delete") is not None
    
    count = memory.forget("to_delete")
    assert count == 1
    assert memory.read("to_delete") is None
