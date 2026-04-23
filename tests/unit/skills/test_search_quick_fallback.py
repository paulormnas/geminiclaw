import pytest
from unittest.mock import AsyncMock, patch
import os
from src.skills.search_quick.skill import QuickSearchSkill
from src.skills.search_quick.scraper import SearchResult

@pytest.fixture
def mock_search_results():
    return [
        SearchResult(title="Mock Title", url="https://mock.com", snippet="Mock snippet")
    ]

@pytest.fixture
def mock_env():
    with patch.dict(os.environ, {
        "QUICK_SEARCH_STRATEGY": "ddg,ddg_lite,brave",
        "BRAVE_API_KEY": "fake_key"
    }):
        yield

@pytest.mark.asyncio
async def test_quick_search_fallback_success_first_try(mock_env, mock_search_results):
    skill = QuickSearchSkill()
    
    # Mocking
    skill.backends["ddg"].search = AsyncMock(return_value=mock_search_results)
    skill.backends["ddg_lite"].search = AsyncMock()
    skill.backends["brave"].search = AsyncMock()
    
    result = await skill.run("test query")
    
    assert result.success is True
    assert result.metadata["source"] == "ddg"
    skill.backends["ddg"].search.assert_called_once()
    skill.backends["ddg_lite"].search.assert_not_called()
    skill.backends["brave"].search.assert_not_called()

@pytest.mark.asyncio
async def test_quick_search_fallback_success_second_try(mock_env, mock_search_results):
    skill = QuickSearchSkill()
    
    # ddg falha (Exception), ddg_lite sucesso
    skill.backends["ddg"].search = AsyncMock(side_effect=Exception("DDG Blocked"))
    skill.backends["ddg_lite"].search = AsyncMock(return_value=mock_search_results)
    skill.backends["brave"].search = AsyncMock()
    
    result = await skill.run("test query")
    
    assert result.success is True
    assert result.metadata["source"] == "ddg_lite"
    skill.backends["ddg"].search.assert_called_once()
    skill.backends["ddg_lite"].search.assert_called_once()
    skill.backends["brave"].search.assert_not_called()

@pytest.mark.asyncio
async def test_quick_search_fallback_success_brave(mock_env, mock_search_results):
    skill = QuickSearchSkill()
    
    # ddg e ddg_lite falham (retornam vazio ou erro)
    skill.backends["ddg"].search = AsyncMock(return_value=[]) # falha silenciosa (vazio)
    skill.backends["ddg_lite"].search = AsyncMock(side_effect=Exception("Timeout"))
    skill.backends["brave"].search = AsyncMock(return_value=mock_search_results)
    
    result = await skill.run("test query")
    
    assert result.success is True
    assert result.metadata["source"] == "brave"
    skill.backends["ddg"].search.assert_called_once()
    skill.backends["ddg_lite"].search.assert_called_once()
    skill.backends["brave"].search.assert_called_once()

@pytest.mark.asyncio
async def test_quick_search_fallback_all_fail(mock_env):
    skill = QuickSearchSkill()
    
    skill.backends["ddg"].search = AsyncMock(side_effect=Exception("Error 1"))
    skill.backends["ddg_lite"].search = AsyncMock(return_value=[])
    skill.backends["brave"].search = AsyncMock(side_effect=Exception("Error 3"))
    
    result = await skill.run("test query")
    
    assert result.success is False
    assert "Todos os backends falharam" in result.error
