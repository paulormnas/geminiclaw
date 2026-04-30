"""Testes unitários para LongTermMemory (PostgreSQL via mock)."""

import pytest
import json
from unittest.mock import MagicMock, patch
from src.skills.memory.long_term import LongTermMemory


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


def _make_row(key="user_pref", value="likes_dark_mode", importance=0.8, tags=None, use_count=0):
    """Cria uma row mock da tabela long_term_memory."""
    return {
        "id": "uuid-1",
        "key": key,
        "value": value,
        "source": "agent_1",
        "importance": importance,
        "tags": tags or ["pref", "ui"],
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_used": "2026-01-01T00:00:00+00:00",
        "use_count": use_count,
    }


@pytest.fixture
def memory():
    return LongTermMemory()


@pytest.mark.unit
def test_write_and_read(memory):
    """write() deve inserir e read() deve retornar a entrada com use_count incrementado."""
    row = _make_row()
    ctx_write, _ = _make_ctx()
    ctx_read, _ = _make_ctx(fetchone=row)
    ctx_update, _ = _make_ctx()

    with patch("src.skills.memory.long_term.get_connection", side_effect=[ctx_write, ctx_read, ctx_update]):
        entry = memory.write("user_pref", "likes_dark_mode", "agent_1", importance=0.8, tags=["pref", "ui"])
        read_entry = memory.read("user_pref")

    assert entry.key == "user_pref"
    assert entry.value == "likes_dark_mode"
    assert entry.importance == 0.8
    assert "pref" in entry.tags

    assert read_entry is not None
    assert read_entry.value == "likes_dark_mode"


@pytest.mark.unit
def test_read_retorna_none_se_nao_encontrado(memory):
    """read() deve retornar None se a chave não existir."""
    ctx, _ = _make_ctx(fetchone=None)
    with patch("src.skills.memory.long_term.get_connection", return_value=ctx):
        result = memory.read("chave_inexistente")
    assert result is None


@pytest.mark.unit
def test_search_by_tags(memory):
    """search() deve retornar resultados filtrados por tags."""
    rows = [_make_row("k1", "v1", tags=["t1", "t2"]), _make_row("k2", "v2", tags=["t2", "t3"])]
    ctx, _ = _make_ctx(fetchall=rows)
    with patch("src.skills.memory.long_term.get_connection", return_value=ctx):
        results = memory.search(tags=["t2"])
    assert len(results) == 2


@pytest.mark.unit
def test_importance_update(memory):
    """update_importance() deve atualizar e retornar True."""
    row = {"id": "uuid-1", "importance": 0.5}
    ctx_read, _ = _make_ctx(fetchone=row)
    ctx_write, _ = _make_ctx()

    with patch("src.skills.memory.long_term.get_connection", side_effect=[ctx_read, ctx_write]):
        result = memory.update_importance("imp_test", 0.2)

    assert result is True


@pytest.mark.unit
def test_importance_clamp(memory):
    """update_importance() deve clampar o resultado entre 0.0 e 1.0 e chamar UPDATE."""
    # update_importance usa um único get_connection e dois conn.execute()
    mock_cursor_select = MagicMock()
    mock_cursor_select.fetchone.return_value = {"id": "uuid-1", "importance": 0.9}
    mock_cursor_update = MagicMock()

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [mock_cursor_select, mock_cursor_update]

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)

    with patch("src.skills.memory.long_term.get_connection", return_value=ctx):
        result = memory.update_importance("test", 0.5)  # 0.9 + 0.5 = 1.4 → clamped to 1.0

    assert result is True
    # Verifica que UPDATE foi chamado com importância clampada
    update_call = mock_conn.execute.call_args_list[1]  # segunda chamada = UPDATE
    sql = update_call[0][0]
    params = update_call[0][1]
    assert "UPDATE" in sql
    assert params[0] == 1.0


@pytest.mark.unit
def test_summarize_for_context(memory):
    """summarize_for_context() deve retornar string formatada com memórias importantes."""
    rows = [_make_row("high_imp", "very important", importance=0.9)]
    ctx, _ = _make_ctx(fetchall=rows)
    with patch("src.skills.memory.long_term.get_connection", return_value=ctx):
        summary = memory.summarize_for_context()
    assert "high_imp: very important" in summary


@pytest.mark.unit
def test_summarize_retorna_vazio_sem_memorias(memory):
    """summarize_for_context() deve retornar string vazia se não houver memórias."""
    ctx, _ = _make_ctx(fetchall=[])
    with patch("src.skills.memory.long_term.get_connection", return_value=ctx):
        summary = memory.summarize_for_context()
    assert summary == ""


@pytest.mark.unit
def test_forget(memory):
    """forget() deve executar DELETE e retornar rowcount."""
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)

    with patch("src.skills.memory.long_term.get_connection", return_value=ctx):
        count = memory.forget("to_delete")

    assert count == 1
    sql = mock_conn.execute.call_args[0][0]
    assert "DELETE" in sql
