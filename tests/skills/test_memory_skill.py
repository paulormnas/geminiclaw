import pytest
from src.skills.memory.short_term import ShortTermMemory
from src.skills.memory.skill import MemorySkill

@pytest.fixture
def memory():
    m = ShortTermMemory()
    return m

@pytest.mark.unit
def test_session_isolation(memory):
    """Testa se as memórias são isoladas corretamente por session_id."""
    memory.clear("session_1")
    memory.clear("session_2")
    
    memory.write("session_1", "key1", "value1", "source1")
    memory.write("session_2", "key2", "value2", "source2")
    
    assert memory.read("session_1", "key1").value == "value1"
    assert memory.read("session_1", "key2") is None
    
    assert memory.read("session_2", "key2").value == "value2"
    assert memory.read("session_2", "key1") is None

@pytest.mark.unit
def test_tag_search(memory):
    """Testa a busca por múltiplas tags."""
    session = "test_tags"
    memory.clear(session)
    
    memory.write(session, "k1", "v1", "s", tags=["tag1", "tag2"])
    memory.write(session, "k2", "v2", "s", tags=["tag1"])
    memory.write(session, "k3", "v3", "s", tags=["tag2"])
    
    # Busca por ambas as tags
    results = memory.search(session, ["tag1", "tag2"])
    assert len(results) == 1
    assert results[0].key == "k1"
    
    # Busca por uma tag
    results_tag1 = memory.search(session, ["tag1"])
    assert len(results_tag1) == 2
    assert set([r.key for r in results_tag1]) == {"k1", "k2"}

@pytest.mark.integration
@pytest.mark.asyncio
async def test_memory_skill_flow():
    """Testa o fluxo da MemorySkill (remember -> recall)."""
    skill = MemorySkill()
    session = "skill_test"
    
    # Gravar
    write_res = await skill.run(
        action="remember", 
        session_id=session, 
        key="fact", 
        value="Pi is 3.14", 
        tags=["math"]
    )
    assert write_res.success is True
    
    # Ler
    read_res = await skill.run(
        action="recall", 
        session_id=session, 
        key="fact"
    )
    assert read_res.success is True
    assert read_res.output == "Pi is 3.14"
    
    # Buscar por tags
    tag_res = await skill.run(
        action="recall_by_tags", 
        session_id=session, 
        tags=["math"]
    )
    assert tag_res.success is True
    assert "fact" in tag_res.output
