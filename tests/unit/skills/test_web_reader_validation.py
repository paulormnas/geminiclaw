"""Testes unitários para V12.4 — WebReader: Validação de Schema e robots.txt 404.

Cobre:
  V12.4.1: URLs com schema != http/https são rejeitadas com mensagem clara.
  V12.4.2: robots.txt retornando 404 é tratado como permissão concedida (RFC 9309).
  V12.4.3: robots.txt 200 com bloqueio explícito é respeitado.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx


# ---------------------------------------------------------------------------
# V12.4.1 — Validação de schema de URL
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_webreader_rejeita_schema_file():
    """URL com schema file:// deve retornar erro claro sem fazer requisição."""
    from src.skills.web_reader.skill import WebReaderSkill

    skill = WebReaderSkill()
    result = await skill.run(url="file:///etc/passwd")

    assert result.success is False
    assert "file" in result.error.lower() or "schema" in result.error.lower()
    assert "python_interpreter" in result.error or "open()" in result.error


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webreader_rejeita_schema_ftp():
    """URL com schema ftp:// deve ser rejeitada."""
    from src.skills.web_reader.skill import WebReaderSkill

    skill = WebReaderSkill()
    result = await skill.run(url="ftp://servidor.com/arquivo.txt")

    assert result.success is False
    assert "ftp" in result.error.lower() or "schema" in result.error.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webreader_aceita_schema_http():
    """URL com schema http:// deve passar a validação de schema."""
    from src.skills.web_reader.skill import WebReaderSkill

    skill = WebReaderSkill()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>Conteúdo da página</body></html>"
    mock_response.raise_for_status = MagicMock()

    mock_robots = MagicMock()
    mock_robots.status_code = 404

    with patch.object(skill, "_can_fetch", AsyncMock(return_value=True)):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await skill.run(url="http://exemplo.com/pagina")

    assert result.success is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webreader_aceita_schema_https():
    """URL com schema https:// deve passar a validação de schema."""
    from src.skills.web_reader.skill import WebReaderSkill

    skill = WebReaderSkill()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>Conteúdo HTTPS</body></html>"
    mock_response.raise_for_status = MagicMock()

    with patch.object(skill, "_can_fetch", AsyncMock(return_value=True)):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await skill.run(url="https://exemplo.com/pagina")

    assert result.success is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_webreader_mensagem_de_erro_inclui_schema_correto():
    """A mensagem de erro deve conter o schema recebido para facilitar depuração."""
    from src.skills.web_reader.skill import WebReaderSkill

    skill = WebReaderSkill()
    result = await skill.run(url="data:text/html,<h1>hello</h1>")

    assert result.success is False
    # Deve mencionar o schema recebido ou a ferramenta correta
    assert "data" in result.error.lower() or "schema" in result.error.lower()


# ---------------------------------------------------------------------------
# V12.4.2 — robots.txt 404 permite acesso (RFC 9309)
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_robots_404_permite_acesso():
    """Se robots.txt retornar 404, a URL deve ser considerada acessível."""
    from src.skills.web_reader.skill import WebReaderSkill

    skill = WebReaderSkill()

    # Simula robots.txt retornando 404 para o domínio
    robots_response = MagicMock()
    robots_response.status_code = 404

    page_response = MagicMock()
    page_response.status_code = 200
    page_response.text = "<html><body>Página liberada</body></html>"
    page_response.raise_for_status = MagicMock()

    call_count = [0]

    async def mock_get(url, **kwargs):
        call_count[0] += 1
        if "robots.txt" in url:
            return robots_response
        return page_response

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client_cls.return_value = mock_client

        result = await skill.run(url="https://sem-robots.com/pagina")

    assert result.success is True, f"robots.txt 404 deve liberar acesso. Erro: {result.error}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_robots_200_com_bloqueio_bloqueia_acesso():
    """Se robots.txt retornar 200 com Disallow: /, a URL deve ser bloqueada."""
    from src.skills.web_reader.skill import WebReaderSkill

    skill = WebReaderSkill()

    robots_content = "User-agent: *\nDisallow: /"

    robots_response = MagicMock()
    robots_response.status_code = 200
    robots_response.text = robots_content

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=robots_response)
        mock_client_cls.return_value = mock_client

        result = await skill.run(url="https://bloqueado.com/pagina")

    assert result.success is False
    assert "robot" in result.error.lower() or "bloqueado" in result.error.lower()
