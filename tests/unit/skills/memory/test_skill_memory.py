import pytest
import os
from src.skills.memory.skill import MemorySkill

@pytest.fixture
def memory_skill(tmp_path):
    db_path = tmp_path / "test_skill_memory.db"
    return MemorySkill(db_path=str(db_path))

@pytest.mark.asyncio
async def test_remember_and_recall(memory_skill):
    session_id = "sess_1"
    
    # Test remember (short term)
    result = await memory_skill.run("remember", session_id=session_id, key="name", value="Gemini")
    assert result.success
    
    # Test recall (short term)
    result = await memory_skill.run("recall", session_id=session_id, key="name")
    assert result.success
    assert result.output == "Gemini"

@pytest.mark.asyncio
async def test_memorize_and_retrieve(memory_skill):
    session_id = "sess_2"
    
    # Test memorize (long term)
    result = await memory_skill.run("memorize", key="user_city", value="São Paulo", importance=0.9)
    assert result.success
    
    # Test retrieve (should find in long term)
    result = await memory_skill.run("retrieve", session_id=session_id, key="user_city")
    assert result.success
    assert result.output == "São Paulo"
    assert result.metadata["source"] == "long_term"

@pytest.mark.asyncio
async def test_remember_forever(memory_skill):
    session_id = "sess_3"
    
    # Salva no curto prazo
    await memory_skill.run("remember", session_id=session_id, key="temp_info", value="something")
    
    # Promove para longo prazo
    result = await memory_skill.run("remember_forever", session_id=session_id, key="temp_info", importance=1.0)
    assert result.success
    
    # Verifica no longo prazo (em outra sessão)
    result = await memory_skill.run("retrieve", session_id="sess_4", key="temp_info")
    assert result.success
    assert result.output == "something"
    assert result.metadata["source"] == "long_term"

@pytest.mark.asyncio
async def test_retrieve_priority(memory_skill):
    session_id = "sess_5"
    
    # Salva no longo prazo
    await memory_skill.run("memorize", key="shared_key", value="long_term_val")
    # Salva no curto prazo da sessão 5
    await memory_skill.run("remember", session_id=session_id, key="shared_key", value="short_term_val")
    
    # Retrieve deve priorizar curto prazo na mesma sessão
    result = await memory_skill.run("retrieve", session_id=session_id, key="shared_key")
    assert result.success
    assert result.output == "short_term_val"
    assert result.metadata["source"] == "short_term"
    
    # Retrieve em outra sessão deve pegar longo prazo
    result = await memory_skill.run("retrieve", session_id="sess_6", key="shared_key")
    assert result.success
    assert result.output == "long_term_val"
    assert result.metadata["source"] == "long_term"
