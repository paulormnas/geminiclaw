"""Busca rápida contra a web real (integração): pula se nenhum backend responde, em vez de falhar."""

import pytest

from src.skills.search_quick.skill import QuickSearchSkill

SOURCES = {"ddg", "ddg_lite", "brave"}


def _skip_if_no_backend(result) -> None:
    """Sem rede ou com todos os backends limitando a consulta, o teste não tem o que verificar."""
    if not result.success and "Todos os backends falharam" in (result.error or ""):
        pytest.skip(f"nenhum backend de busca respondeu agora: {result.error}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quick_search_real_query():
    skill = QuickSearchSkill(timeout=15)
    result = await skill.run("Gemini AI Google DeepMind", max_results=3)
    _skip_if_no_backend(result)

    assert result.success is True
    assert len(result.output) > 0
    assert result.metadata["source"] in SOURCES
    for item in result.output:
        assert "title" in item and "url" in item and "snippet" in item
        assert item["title"] or item["snippet"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quick_search_cache_integration():
    skill = QuickSearchSkill()
    query = "Python programming language"

    result1 = await skill.run(query, max_results=3)  # primeira vez: vai ao backend
    _skip_if_no_backend(result1)
    assert result1.metadata["source"] in SOURCES

    result2 = await skill.run(query, max_results=3)  # segunda vez: vem do cache
    assert result2.metadata["source"] == "cache"
    assert result2.output == result1.output
