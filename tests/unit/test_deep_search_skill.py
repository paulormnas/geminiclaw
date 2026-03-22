import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.skills.search_deep.skill import DeepSearchSkill
from src.skills.base import SkillResult

@pytest.fixture
def mock_indexer():
    return AsyncMock()

@pytest.fixture
def mock_cache():
    return MagicMock()

@pytest.fixture
def skill(mock_indexer, mock_cache):
    return DeepSearchSkill(indexer=mock_indexer, cache=mock_cache)

@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_run_cache_hit(skill, mock_cache):
    mock_cache.get.return_value = [{"content": "cached"}]
    
    result = await skill.run("query")
    
    assert result.success
    assert result.output == [{"content": "cached"}]
    assert result.metadata["source"] == "cache"

@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_run_cache_miss(skill, mock_indexer, mock_cache):
    mock_cache.get.return_value = None
    mock_indexer.search.return_value = [{"content": "from index"}]
    
    result = await skill.run("query")
    
    assert result.success
    assert result.output == [{"content": "from index"}]
    assert result.metadata["source"] == "index"
    assert mock_cache.set.called

@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_run_error(skill, mock_indexer, mock_cache):
    mock_cache.get.return_value = None
    mock_indexer.search.side_effect = Exception("Search error")
    
    result = await skill.run("query")
    
    assert not result.success
    assert "Search error" in result.error
