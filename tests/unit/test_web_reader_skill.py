"""Testes unitários para a skill WebReader."""

import pytest
import respx
import httpx
from bs4 import BeautifulSoup

from src.skills.web_reader.skill import WebReaderSkill

# ---------------------------------------------------------------------------
# Fixtures e Constantes
# ---------------------------------------------------------------------------

TEST_URL = "http://example.com/page"
TEST_ROBOTS_URL = "http://example.com/robots.txt"

HTML_CONTENT = """
<html>
    <head>
        <title>Test Page</title>
        <style>.hidden { display: none; }</style>
        <script>alert("Hello!");</script>
    </head>
    <body>
        <header>Menu Principal</header>
        <nav><ul><li>Link 1</li></ul></nav>
        <main>
            <h1>Conteúdo Real</h1>
            <p>Este é o texto que queremos extrair.</p>
        </main>
        <aside>Publicidade</aside>
        <footer>Rodapé</footer>
    </body>
</html>
"""

# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------

@pytest.fixture
def web_reader():
    return WebReaderSkill()

@pytest.mark.unit
@pytest.mark.asyncio
async def test_web_reader_success(web_reader: WebReaderSkill) -> None:
    """Testa a extração correta de texto ignorando scripts, styles, etc."""
    with respx.mock:
        # Mock do robots.txt permitindo tudo
        respx.get(TEST_ROBOTS_URL).respond(status_code=200, text="User-agent: *\nAllow: /")
        # Mock da página principal
        respx.get(TEST_URL).respond(status_code=200, text=HTML_CONTENT)

        result = await web_reader.run(TEST_URL)

        assert result.success is True
        text = result.output
        
        # Elementos indesejados não devem estar no texto
        assert "Menu Principal" not in text
        assert "Link 1" not in text
        assert "Publicidade" not in text
        assert "Rodapé" not in text
        assert "alert(" not in text
        assert ".hidden" not in text

        # Conteúdo principal deve estar
        assert "Test Page" in text
        assert "Conteúdo Real" in text
        assert "Este é o texto que queremos extrair." in text

@pytest.mark.unit
@pytest.mark.asyncio
async def test_web_reader_truncation(web_reader: WebReaderSkill) -> None:
    """Testa se o conteúdo longo é truncado corretamente."""
    long_html = "<html><body><p>" + ("a" * 10000) + "</p></body></html>"
    with respx.mock:
        respx.get(TEST_ROBOTS_URL).respond(status_code=200, text="User-agent: *\nAllow: /")
        respx.get(TEST_URL).respond(status_code=200, text=long_html)

        result = await web_reader.run(TEST_URL, max_chars=5000)

        assert result.success is True
        text = result.output
        assert len(text) == 5000 + len("... [CONTEÚDO TRUNCADO]")
        assert text.endswith("... [CONTEÚDO TRUNCADO]")

@pytest.mark.unit
@pytest.mark.asyncio
async def test_web_reader_cache(web_reader: WebReaderSkill) -> None:
    """Testa se a leitura usa o cache."""
    with respx.mock:
        respx.get(TEST_ROBOTS_URL).respond(status_code=200, text="User-agent: *\nAllow: /")
        route = respx.get(TEST_URL).respond(status_code=200, text="<html><body><p>Cache test</p></body></html>")

        # Primeira chamada bate na API
        result1 = await web_reader.run(TEST_URL)
        assert result1.success is True
        assert "Cache test" in result1.output
        assert route.call_count == 1

        # Segunda chamada deve pegar do cache
        result2 = await web_reader.run(TEST_URL)
        assert result2.success is True
        assert "Cache test" in result2.output
        assert route.call_count == 1  # count não mudou

@pytest.mark.unit
@pytest.mark.asyncio
async def test_web_reader_robots_disallow(web_reader: WebReaderSkill) -> None:
    """Testa bloqueio pelo robots.txt."""
    with respx.mock:
        respx.get(TEST_ROBOTS_URL).respond(status_code=200, text="User-agent: *\nDisallow: /page")
        
        result = await web_reader.run(TEST_URL)

        assert result.success is False
        assert "bloqueado pelo robots.txt" in result.error

@pytest.mark.unit
@pytest.mark.asyncio
async def test_web_reader_http_error(web_reader: WebReaderSkill) -> None:
    """Testa tratamento de erro HTTP."""
    with respx.mock:
        respx.get(TEST_ROBOTS_URL).respond(status_code=200, text="User-agent: *\nAllow: /")
        respx.get(TEST_URL).respond(status_code=404, text="Not Found")

        result = await web_reader.run(TEST_URL)

        assert result.success is False
        assert "Erro HTTP 404" in result.error
