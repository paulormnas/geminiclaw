import pytest
from unittest.mock import AsyncMock, MagicMock
from src.skills.search_deep.skill import DeepSearchSkill
from src.skills.base import SkillResult

@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_execution_flow():
    mock_indexer = MagicMock()
    mock_cache = MagicMock()
    
    # Simula miss no cache
    mock_cache.get.return_value = None
    
    # Simula resultados do indexer
    results = [{"content": "found", "url": "http://found.com", "title": "Found"}]
    mock_indexer.search = AsyncMock(return_value=results)
    
    skill = DeepSearchSkill(indexer=mock_indexer, cache=mock_cache)
    
    response = await skill.run(query="search for something")
    
    assert response.success
    assert response.output == results
    assert response.metadata["source"] == "index"
    
    # Verifica se salvou no cache
    assert mock_cache.set.called

@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_cache_hit():
    mock_indexer = MagicMock()
    mock_cache = MagicMock()
    
    # Simula hit no cache
    results = [{"content": "from cache"}]
    mock_cache.get.return_value = results
    
    skill = DeepSearchSkill(indexer=mock_indexer, cache=mock_cache)
    
    response = await skill.run(query="cached query")
    
    assert response.success
    assert response.output == results
    assert response.metadata["source"] == "cache"
    
    # Indexer não deve ter sido chamado
    assert not mock_indexer.search.called
