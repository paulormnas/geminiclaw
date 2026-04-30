"""Testes unitários para MemorySkill (PostgreSQL via mock).

Usa mock de get_connection para as operações de longo prazo.
Curto prazo (ShortTermMemory) é in-memory e não precisa de mock.
"""

import pytest
from unittest.mock import MagicMock, patch
from src.skills.memory.skill import MemorySkill


def _make_ctx(fetchone=None, fetchall=None):
    """Cria context manager mock de conexão."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone
    mock_cursor.fetchall.return_value = fetchall or []
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, mock_conn


def _make_lt_row(key="user_city", value="São Paulo", importance=0.9):
    """Cria uma row mock da tabela long_term_memory."""
    import json
    return {
        "id": "uuid-1",
        "key": key,
        "value": value,
        "source": "agent",
        "importance": importance,
        "tags": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_used": "2026-01-01T00:00:00+00:00",
        "use_count": 0,
    }


@pytest.fixture
def skill():
    return MemorySkill()


@pytest.mark.asyncio
async def test_remember_and_recall(skill):
    """remember grava no curto prazo; recall recupera do curto prazo."""
    session_id = "sess_1"

    result = await skill.run("remember", session_id=session_id, key="name", value="Gemini")
    assert result.success

    result = await skill.run("recall", session_id=session_id, key="name")
    assert result.success
    assert result.output == "Gemini"


@pytest.mark.asyncio
async def test_memorize_and_retrieve(skill):
    """memorize grava no longo prazo; retrieve recupera do longo prazo."""
    session_id = "sess_2"
    row = _make_lt_row("user_city", "São Paulo")

    # memorize → INSERT (get_connection) + retrieve → SELECT + UPDATE (2x get_connection)
    ctx_write, _ = _make_ctx()
    ctx_read, _ = _make_ctx(fetchone=row)
    ctx_update, _ = _make_ctx()

    with patch("src.skills.memory.long_term.get_connection",
               side_effect=[ctx_write, ctx_read, ctx_update]):
        result = await skill.run("memorize", key="user_city", value="São Paulo", importance=0.9)
        assert result.success

        result = await skill.run("retrieve", session_id=session_id, key="user_city")

    assert result.success
    assert result.output == "São Paulo"
    assert result.metadata["source"] == "long_term"


@pytest.mark.asyncio
async def test_remember_forever(skill):
    """remember_forever promove do curto prazo para o longo prazo."""
    session_id = "sess_3"

    # Salva no curto prazo (sem mock — in-memory)
    await skill.run("remember", session_id=session_id, key="temp_info", value="something")

    # Promove para longo prazo (long_term.write → INSERT)
    ctx_write, _ = _make_ctx()
    with patch("src.skills.memory.long_term.get_connection", return_value=ctx_write):
        result = await skill.run("remember_forever", session_id=session_id,
                                 key="temp_info", importance=1.0)

    assert result.success


@pytest.mark.asyncio
async def test_retrieve_priority_curto_prazo(skill):
    """retrieve deve priorizar curto prazo quando disponível na sessão."""
    session_id = "sess_5"

    # Salva no curto prazo
    await skill.run("remember", session_id=session_id, key="shared_key", value="short_term_val")

    # retrieve: curto prazo encontrado, não consulta longo prazo
    result = await skill.run("retrieve", session_id=session_id, key="shared_key")
    assert result.success
    assert result.output == "short_term_val"
    assert result.metadata["source"] == "short_term"


@pytest.mark.asyncio
async def test_retrieve_fallback_longo_prazo(skill):
    """retrieve deve buscar longo prazo quando não há entrada no curto prazo."""
    row = _make_lt_row("shared_key", "long_term_val")
    ctx_read, _ = _make_ctx(fetchone=row)
    ctx_update, _ = _make_ctx()

    with patch("src.skills.memory.long_term.get_connection",
               side_effect=[ctx_read, ctx_update]):
        result = await skill.run("retrieve", session_id="sess_6", key="shared_key")

    assert result.success
    assert result.output == "long_term_val"
    assert result.metadata["source"] == "long_term"
