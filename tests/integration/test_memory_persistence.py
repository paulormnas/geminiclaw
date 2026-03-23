import pytest
import os
from src.session import SessionManager
from src.skills.memory.skill import MemorySkill

@pytest.fixture
def session_manager(tmp_path):
    sessions_db = tmp_path / "sessions.db"
    memory_db = tmp_path / "memory.db"
    return SessionManager(str(sessions_db), lt_memory_db_path=str(memory_db))

@pytest.mark.asyncio
async def test_persistence_between_sessions(session_manager):
    # 1. Cria Sessão A e registra memória de longo prazo
    session_a = session_manager.create("agent_test")
    
    skill = MemorySkill(db_path=session_manager.lt_memory_db_path)
    await skill.run("memorize", key="user_name", value="Paulo", importance=1.0)
    
    # 2. Cria Sessão B e verifica se a memória está no resumo (payload da sessão)
    session_b = session_manager.create("agent_test")
    
    assert "long_term_memory_summary" in session_b.payload
    assert "user_name: Paulo" in session_b.payload["long_term_memory_summary"]
    
    # 3. Verifica recuperação via skill na Sessão B
    result = await skill.run("retrieve", session_id=session_b.id, key="user_name")
    assert result.success
    assert result.output == "Paulo"
    assert result.metadata["source"] == "long_term"
