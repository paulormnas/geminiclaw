import pytest
import os
from src.skills.search_quick.skill import QuickSearchSkill

@pytest.mark.integration
@pytest.mark.asyncio
async def test_quick_search_real_query():
    # Só roda se SKILL_QUICK_SEARCH_ENABLED estiver true ou se ignorarmos o .env
    skill = QuickSearchSkill(timeout=15)
    
    query = "Gemini AI Google DeepMind"
    result = await skill.run(query, max_results=3)
    
    assert result.success is True
    assert len(result.output) > 0
    assert result.metadata["source"] == "ddg"
    
    # Verificar se o campo dict foi preenchido
    for item in result.output:
        assert "title" in item
        assert "url" in item
        assert "snippet" in item
        assert "Gemini" in item["title"] or "Gemini" in item["snippet"]

@pytest.mark.integration
@pytest.mark.asyncio
async def test_quick_search_cache_integration():
    skill = QuickSearchSkill()
    query = "Python programming language"
    
    # Primeira vez: deve ir para o scraper
    result1 = await skill.run(query, max_results=3)
    assert result1.metadata["source"] == "ddg"
    
    # Segunda vez: deve vir do cache
    result2 = await skill.run(query, max_results=3)
    assert result2.metadata["source"] == "cache"
    assert result2.output == result1.output
