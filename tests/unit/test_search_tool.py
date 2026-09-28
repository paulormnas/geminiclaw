from unittest.mock import AsyncMock, patch

import pytest

from agents.researcher.tools import get_search_cache, reset_search_cache, search
from src.skills.base import SkillResult


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """Reseta o cache antes de cada teste para garantir isolamento."""
    reset_search_cache(ttl_seconds=3600)
    import agents.researcher.tools as tools_module

    tools_module._quick_search_skill = None


def _mock_skill_run(result: SkillResult) -> AsyncMock:
    return AsyncMock(return_value=result)


@pytest.mark.unit
@pytest.mark.asyncio
class TestSearchToolSuccess:
    """Testes de sucesso da ferramenta de busca (Roadmap V16/ADR 014: via search_quick, sem subprocesso)."""

    async def test_search_returns_result(self) -> None:
        """search deve retornar texto formatado a partir dos resultados de search_quick."""
        results = [{"title": "Python frameworks", "url": "https://example.com", "snippet": "Django e Flask"}]
        with patch(
            "agents.researcher.tools.QuickSearchSkill.run",
            new=_mock_skill_run(SkillResult(success=True, output=results)),
        ):
            result = await search("Python frameworks")

        assert "Python frameworks" in result
        assert "https://example.com" in result
        assert "Django e Flask" in result

    async def test_search_caches_result(self) -> None:
        """search deve armazenar resultado no cache após sucesso."""
        results = [{"title": "Web frameworks", "url": "https://example.com/web", "snippet": "Django e Flask"}]
        with patch(
            "agents.researcher.tools.QuickSearchSkill.run",
            new=_mock_skill_run(SkillResult(success=True, output=results)),
        ):
            await search("web frameworks python")

        cache = get_search_cache()
        cached = cache.get("web frameworks python")
        assert cached is not None
        assert "Web frameworks" in cached

    async def test_search_uses_cache_on_hit(self) -> None:
        """search deve retornar do cache sem chamar a skill de busca."""
        cache = get_search_cache()
        cache.set("cached query", "cached result")

        mock_run = _mock_skill_run(SkillResult(success=True, output=[]))
        with patch("agents.researcher.tools.QuickSearchSkill.run", new=mock_run):
            result = await search("cached query")

        assert result == "cached result"
        mock_run.assert_not_called()

    async def test_search_does_not_spawn_subprocess(self) -> None:
        """Requirement 'Busca do Researcher sem subprocesso de fornecedor' (Spec agent-runtime)."""
        results = [{"title": "T", "url": "https://example.com", "snippet": "S"}]
        with (
            patch(
                "agents.researcher.tools.QuickSearchSkill.run",
                new=_mock_skill_run(SkillResult(success=True, output=results)),
            ),
            patch("asyncio.create_subprocess_exec") as mock_subprocess,
        ):
            await search("qualquer busca técnica")

        mock_subprocess.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
class TestSearchToolErrors:
    """Testes de erro da ferramenta de busca."""

    async def test_search_empty_query(self) -> None:
        """search com query vazia deve retornar mensagem de erro."""
        result = await search("")
        assert "Erro" in result

        result = await search("   ")
        assert "Erro" in result

    async def test_search_skill_error(self) -> None:
        """search deve retornar erro quando a skill search_quick falha."""
        with patch(
            "agents.researcher.tools.QuickSearchSkill.run",
            new=_mock_skill_run(SkillResult(success=False, output=[], error="todos os backends falharam")),
        ):
            result = await search("test query")

        assert "Erro" in result
        assert "todos os backends falharam" in result

    async def test_search_empty_results(self) -> None:
        """search deve retornar mensagem informativa quando não há resultados."""
        with patch(
            "agents.researcher.tools.QuickSearchSkill.run",
            new=_mock_skill_run(SkillResult(success=True, output=[])),
        ):
            result = await search("query sem resultado")

        assert "nenhum resultado" in result.lower()

    async def test_search_unexpected_exception(self) -> None:
        """search deve tratar exceções inesperadas."""
        with patch(
            "agents.researcher.tools.QuickSearchSkill.run",
            new=AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            result = await search("test query")

        assert "Erro" in result


@pytest.mark.unit
@pytest.mark.asyncio
class TestSearchCacheIntegration:
    """Testes de integração cache + ferramenta de busca."""

    async def test_cache_miss_then_hit(self) -> None:
        """Primeira chamada faz busca, segunda usa cache."""
        results = [{"title": "T", "url": "https://example.com", "snippet": "result"}]
        mock_run = _mock_skill_run(SkillResult(success=True, output=results))
        with patch("agents.researcher.tools.QuickSearchSkill.run", new=mock_run):
            result1 = await search("same query")
            assert "result" in result1
            assert mock_run.call_count == 1

            result2 = await search("same query")
            assert result2 == result1
            assert mock_run.call_count == 1  # Não deve ter chamado novamente

    async def test_error_does_not_cache(self) -> None:
        """Resultados de erro não devem ser cacheados."""
        with patch(
            "agents.researcher.tools.QuickSearchSkill.run",
            new=_mock_skill_run(SkillResult(success=False, output=[], error="falha")),
        ):
            await search("failing query")

        cache = get_search_cache()
        assert cache.get("failing query") is None
