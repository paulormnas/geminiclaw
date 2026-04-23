import pytest
import os
import tempfile
from src.history import ExecutionHistory

@pytest.fixture
def memory_history():
    """Retorna um ExecutionHistory isolado."""
    # Usamos tempfile em vez de :memory: para garantir compatibilidade multithread/conexao se precisar
    fd, path = tempfile.mkstemp()
    os.close(fd)
    history = ExecutionHistory(db_path=path)
    yield history
    os.remove(path)

def test_record_and_get(memory_history):
    exec_id = memory_history.record(
        prompt="Test Prompt",
        status="success",
        started_at="2026-04-23T00:00:00Z",
        finished_at="2026-04-23T00:00:10Z",
        duration_seconds=10.0,
        plan_json='[{"task": "test"}]',
        results_json="[]",
        artifacts_json="[]",
        total_subtasks=1,
        succeeded=1,
        failed=0
    )
    
    assert exec_id
    
    record = memory_history.get(exec_id)
    assert record is not None
    assert record.id == exec_id
    assert record.prompt == "Test Prompt"
    assert record.status == "success"
    assert record.duration_seconds == 10.0
    assert record.total_subtasks == 1

def test_get_not_found(memory_history):
    assert memory_history.get("invalid_id") is None

def test_list_recent(memory_history):
    # Insere 3 registros com datas diferentes
    for i in range(3):
        memory_history.record(
            prompt=f"Prompt {i}",
            status="success",
            started_at=f"2026-04-23T00:0{i}:00Z",
            finished_at=f"2026-04-23T00:0{i}:10Z",
            duration_seconds=10.0
        )
        
    records = memory_history.list_recent(limit=2)
    assert len(records) == 2
    # O mais recente deve vir primeiro (i=2)
    assert records[0].prompt == "Prompt 2"
    assert records[1].prompt == "Prompt 1"

def test_search(memory_history):
    memory_history.record("Busca por gatos", "success", "2026-04-23T00:00:00Z")
    memory_history.record("Busca por cachorros", "success", "2026-04-23T00:01:00Z")
    
    results = memory_history.search("gato")
    assert len(results) == 1
    assert results[0].prompt == "Busca por gatos"
    
    results_vazio = memory_history.search("passarinhos")
    assert len(results_vazio) == 0
