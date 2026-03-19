import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from agents.researcher.tools import search, reset_search_cache, get_search_cache


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """Reseta o cache antes de cada teste para garantir isolamento."""
    reset_search_cache(ttl_seconds=3600)


@pytest.mark.unit
@pytest.mark.asyncio
class TestSearchToolSuccess:
    """Testes de sucesso da ferramenta de busca."""

    async def test_search_returns_result(self) -> None:
        """search deve retornar stdout do Gemini CLI quando exit code 0."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (
            b"Resultado da busca sobre Python",
            b"",
        )
        mock_process.returncode = 0

        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_process):
            result = await search("Python frameworks")

        assert result == "Resultado da busca sobre Python"

    async def test_search_caches_result(self) -> None:
        """search deve armazenar resultado no cache após sucesso."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (
            b"Django e Flask",
            b"",
        )
        mock_process.returncode = 0

        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_process):
            await search("web frameworks python")

        # Verifica que o cache foi populado
        cache = get_search_cache()
        cached = cache.get("web frameworks python")
        assert cached == "Django e Flask"

    async def test_search_uses_cache_on_hit(self) -> None:
        """search deve retornar do cache sem chamar subprocesso."""
        # Popula o cache manualmente
        cache = get_search_cache()
        cache.set("cached query", "cached result")

        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock) as mock_exec:
            result = await search("cached query")

        assert result == "cached result"
        mock_exec.assert_not_called()


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

    async def test_search_nonzero_exit_code(self) -> None:
        """search deve retornar erro quando Gemini CLI retorna exit code != 0."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (
            b"",
            b"Error: API key invalid",
        )
        mock_process.returncode = 1

        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_process):
            result = await search("test query")

        assert "Erro" in result
        assert "código 1" in result

    async def test_search_timeout(self) -> None:
        """search deve tratar timeout do subprocesso."""
        mock_process = AsyncMock()
        mock_process.communicate.side_effect = asyncio.TimeoutError()
        mock_process.kill = MagicMock()

        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_process):
            result = await search("query lenta")

        assert "timeout" in result.lower()

    async def test_search_gemini_not_found(self) -> None:
        """search deve tratar caso onde Gemini CLI não está instalado."""
        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock,
                    side_effect=FileNotFoundError("gemini not found")):
            result = await search("test query")

        assert "não encontrado" in result.lower() or "not found" in result.lower()

    async def test_search_empty_stdout(self) -> None:
        """search deve retornar mensagem informativa quando stdout é vazio."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"")
        mock_process.returncode = 0

        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_process):
            result = await search("query sem resultado")

        assert "nenhum resultado" in result.lower()

    async def test_search_unexpected_exception(self) -> None:
        """search deve tratar exceções inesperadas."""
        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("unexpected")):
            result = await search("test query")

        assert "Erro" in result


@pytest.mark.unit
@pytest.mark.asyncio
class TestSearchCacheIntegration:
    """Testes de integração cache + ferramenta de busca."""

    async def test_cache_miss_then_hit(self) -> None:
        """Primeira chamada faz busca, segunda usa cache."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"result", b"")
        mock_process.returncode = 0

        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_process) as mock_exec:
            # Primeira chamada — cache miss
            result1 = await search("same query")
            assert result1 == "result"
            assert mock_exec.call_count == 1

            # Segunda chamada — cache hit
            result2 = await search("same query")
            assert result2 == "result"
            assert mock_exec.call_count == 1  # Não deve ter chamado novamente

    async def test_error_does_not_cache(self) -> None:
        """Resultados de erro não devem ser cacheados."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"error")
        mock_process.returncode = 1

        with patch("agents.researcher.tools.asyncio.create_subprocess_exec",
                    new_callable=AsyncMock, return_value=mock_process):
            await search("failing query")

        cache = get_search_cache()
        assert cache.get("failing query") is None
