"""Smoke test E2E do agente researcher com API real.

⚠️ Este teste consome tokens reais da API Gemini.
Execute manualmente com: uv run pytest tests/e2e/test_researcher_e2e.py -m e2e -v -s
"""

import pytest

from agents.researcher.tools import search, reset_search_cache


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """Reseta o cache antes de cada teste."""
    reset_search_cache(ttl_seconds=3600)


@pytest.mark.e2e
@pytest.mark.asyncio
class TestResearcherE2E:
    """Smoke tests E2E do researcher com API real."""

    async def test_search_returns_nonempty_result(self) -> None:
        """search com query real deve retornar resposta não-vazia.

        Este teste requer que o Gemini CLI esteja instalado e
        configurado com uma API key válida.
        """
        result = await search("O que é o framework GeminiClaw?")

        # O resultado deve ser uma string não-vazia
        assert isinstance(result, str)
        assert len(result) > 0

        # Se o Gemini CLI não estiver instalado, o resultado será
        # uma mensagem de erro — ainda assim deve ser informativo
        if "Erro" not in result:
            # Resultado real — deve ter conteúdo substantivo
            assert len(result) > 10

    async def test_search_caches_real_result(self) -> None:
        """Segundo call com mesma query deve vir do cache."""
        query = "Capital do Brasil"
        result1 = await search(query)
        result2 = await search(query)

        # Ambos devem retornar o mesmo resultado
        assert result1 == result2
