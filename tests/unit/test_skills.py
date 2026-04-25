import pytest
from src.skills.base import BaseSkill, SkillResult
from src.skills import SkillRegistry

class MockSkill(BaseSkill):
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    async def run(self, **kwargs) -> SkillResult:
        return SkillResult(success=True, output="mock output")

@pytest.fixture
def registry():
    return SkillRegistry()

@pytest.mark.unit
def test_register_skill(registry):
    skill = MockSkill("test_skill", "A test skill")
    registry.register(skill)
    
    assert registry.get("test_skill") == skill

@pytest.mark.unit
def test_register_duplicate_skill(registry):
    skill1 = MockSkill("test_skill", "First description")
    skill2 = MockSkill("test_skill", "Second description")
    
    registry.register(skill1)
    with pytest.raises(ValueError, match="já está registrada"):
        registry.register(skill2)

@pytest.mark.unit
def test_get_nonexistent_skill(registry):
    assert registry.get("nonexistent") is None

@pytest.mark.unit
def test_list_available_skills(registry):
    skill1 = MockSkill("skill1", "Desc 1")
    skill2 = MockSkill("skill2", "Desc 2")
    
    registry.register(skill1)
    registry.register(skill2)
    
    available = registry.list_available()
    assert len(available) == 2
    assert {"name": "skill1", "description": "Desc 1"} in available
    assert {"name": "skill2", "description": "Desc 2"} in available

@pytest.mark.unit
def test_as_tools_returns_list(registry):
    # Por agora retorna lista vazia até implementação completa
    assert isinstance(registry.as_tools(), list)
