import pytest
import sqlite3
import os
import concurrent.futures
from src.session import SessionManager, init_db

@pytest.fixture
def db_path(tmp_path):
    """Fixture para um caminho de banco de dados temporário."""
    return str(tmp_path / "test_sessions.db")

@pytest.fixture
def session_manager(db_path):
    """Fixture para o SessionManager."""
    return SessionManager(db_path)

@pytest.mark.unit
def test_session_crud(session_manager):
    """Testa o fluxo CRUD completo de uma sessão."""
    agent_id = "test_agent"
    
    # Create
    session = session_manager.create(agent_id)
    assert session.agent_id == agent_id
    assert session.status == "active"
    assert session.payload == {}
    
    # Get
    retrieved = session_manager.get(session.id)
    assert retrieved.id == session.id
    assert retrieved.agent_id == agent_id
    
    # Update
    new_payload = {"key": "value"}
    updated = session_manager.update(session.id, status="processing", payload=new_payload)
    assert updated.status == "processing"
    assert updated.payload == new_payload
    
    # Close
    session_manager.close(session.id)
    closed = session_manager.get(session.id)
    assert closed.status == "closed"

@pytest.mark.unit
def test_list_active(session_manager):
    """Testa a listagem de sessões ativas."""
    session_manager.create("agent_1")
    session_manager.create("agent_2")
    session_3 = session_manager.create("agent_3")
    session_manager.close(session_3.id)
    
    active_sessions = session_manager.list_active()
    assert len(active_sessions) == 2
    for s in active_sessions:
        assert s.status == "active"

@pytest.mark.unit
def test_update_non_existent_raises_error(session_manager):
    """Testa se atualizar uma sessão inexistente lança erro."""
    with pytest.raises(ValueError) as excinfo:
        session_manager.update("non_existent_id", status="closed")
    assert "não encontrada" in str(excinfo.value)

@pytest.mark.unit
def test_concurrency_writes(db_path):
    """Testa a robustez de escritas simultâneas."""
    manager = SessionManager(db_path)
    num_threads = 10
    num_creates_per_thread = 5
    total_creates = num_threads * num_creates_per_thread
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        # Envia múltiplas chamadas de criação diretamente para o executor
        futures = [
            executor.submit(manager.create, f"agent_{i}") 
            for i in range(total_creates)
        ]
        concurrent.futures.wait(futures)
        
    active_sessions = manager.list_active()
    assert len(active_sessions) == total_creates

