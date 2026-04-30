"""Testes unitários para src/session.py (PostgreSQL via mock).

Usa unittest.mock para simular get_connection sem precisar de banco real.
"""

import pytest
import json
from unittest.mock import MagicMock, patch, call
from src.session import SessionManager, Session


_SENTINEL = object()  # Sentinela para distinguir fetchone_result=None do padrão


def _make_mock_conn(fetchone_result=_SENTINEL, rows=None):
    """Cria um mock de conexão PostgreSQL."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    # Garante que fetchone() retorna exatamente o valor indicado (inclusive None)
    if fetchone_result is not _SENTINEL:
        mock_cursor.fetchone.return_value = fetchone_result
    if rows is not None:
        mock_cursor.fetchall.return_value = rows
    return mock_conn


def _session_row(session_id="sid-1", agent_id="agent-1", status="active", payload=None):
    """Cria um dicionário simulando uma row do banco."""
    return {
        "id": session_id,
        "agent_id": agent_id,
        "status": status,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "payload": json.dumps(payload or {}),
    }


def _make_ctx_with_fetchone(fetchone_result):
    """Cria context manager onde conn.execute().fetchone() retorna fetchone_result."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone_result
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, mock_conn


def _make_ctx_with_fetchall(rows):
    """Cria context manager onde conn.execute().fetchall() retorna rows."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, mock_conn


@pytest.fixture
def manager():
    return SessionManager()


@pytest.mark.unit
class TestSessionCreate:
    def test_create_insere_no_banco(self, manager):
        """create() deve chamar INSERT com os dados corretos."""
        ctx, mock_conn = _make_ctx_with_fetchone(None)

        # LongTermMemory é importédo no nível do módulo — patch direto em src.session
        with patch("src.session.get_connection", return_value=ctx), \
             patch("src.session.LongTermMemory") as mock_ltm:
            mock_ltm.return_value.summarize_for_context.return_value = ""
            session = manager.create("agent-1")

        assert session.agent_id == "agent-1"
        assert session.status == "active"
        mock_conn.execute.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO agent_sessions" in sql

    def test_create_inclui_lt_memory_no_payload(self, manager):
        """Se LongTermMemory retornar sumário, deve estar no payload."""
        ctx, _ = _make_ctx_with_fetchone(None)

        with patch("src.session.get_connection", return_value=ctx), \
             patch("src.session.LongTermMemory") as mock_ltm:
            mock_ltm.return_value.summarize_for_context.return_value = "Memória importante"
            session = manager.create("agent-1")

        assert "long_term_memory_summary" in session.payload


@pytest.mark.unit
class TestSessionGet:
    def test_get_retorna_sessao(self, manager):
        """get() deve retornar Session quando a row existe."""
        row = _session_row()
        ctx, _ = _make_ctx_with_fetchone(row)

        with patch("src.session.get_connection", return_value=ctx):
            session = manager.get("sid-1")

        assert session is not None
        assert session.id == "sid-1"
        assert session.agent_id == "agent-1"
        assert session.status == "active"

    def test_get_retorna_none_se_nao_encontrado(self, manager):
        """get() deve retornar None se a row não existir."""
        ctx, _ = _make_ctx_with_fetchone(None)

        with patch("src.session.get_connection", return_value=ctx):
            result = manager.get("inexistente")

        assert result is None


@pytest.mark.unit
class TestSessionUpdate:
    def test_update_chama_sql_update(self, manager):
        """update() deve executar UPDATE na tabela agent_sessions."""
        row = _session_row()
        ctx, mock_conn = _make_ctx_with_fetchone(row)

        with patch("src.session.get_connection", return_value=ctx):
            session = manager.update("sid-1", status="processing")

        assert session.status == "processing"
        sqls = [c[0][0] for c in mock_conn.execute.call_args_list]
        assert any("UPDATE agent_sessions" in s for s in sqls)

    def test_update_lanca_se_nao_encontrado(self, manager):
        """update() deve levantar ValueError se a sessão não existir."""
        ctx, _ = _make_ctx_with_fetchone(None)

        with patch("src.session.get_connection", return_value=ctx):
            with pytest.raises(ValueError, match="não encontrada"):
                manager.update("ghost", status="closed")


@pytest.mark.unit
class TestSessionList:
    def test_list_active_retorna_lista(self, manager):
        """list_active() deve retornar lista de sessões ativas."""
        rows = [_session_row("s1", "ag1"), _session_row("s2", "ag2")]
        ctx, _ = _make_ctx_with_fetchall(rows)

        with patch("src.session.get_connection", return_value=ctx):
            sessions = manager.list_active()

        assert len(sessions) == 2
        assert all(isinstance(s, Session) for s in sessions)

    def test_list_recent_respeita_limit(self, manager):
        """list_recent() deve passar o limit para o SQL."""
        ctx, mock_conn = _make_ctx_with_fetchall([])

        with patch("src.session.get_connection", return_value=ctx):
            manager.list_recent(limit=5)

        sql, params = mock_conn.execute.call_args[0]
        assert "LIMIT" in sql
        assert 5 in params
