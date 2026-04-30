"""Testes unitários para src/history.py (PostgreSQL via mock)."""

import pytest
from unittest.mock import MagicMock, patch
from src.history import ExecutionHistory


def _make_ctx(fetchone=None, fetchall=None):
    """Cria context manager mock de conexão."""
    mock_conn = MagicMock()
    cursor = MagicMock()
    mock_conn.execute.return_value = cursor
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall or []
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, mock_conn


def _make_row(exec_id="exec-1", prompt="test", status="success"):
    return {
        "id": exec_id,
        "prompt": prompt,
        "plan_json": None,
        "status": status,
        "results_json": None,
        "artifacts_json": None,
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": None,
        "duration_seconds": None,
        "total_subtasks": 0,
        "succeeded": 0,
        "failed": 0,
    }


@pytest.fixture
def history():
    return ExecutionHistory()


@pytest.mark.unit
class TestExecutionHistoryRecord:
    def test_record_retorna_id(self, history):
        """record() deve retornar um ID não-vazio."""
        ctx, _ = _make_ctx()
        with patch("src.history.get_connection", return_value=ctx):
            exec_id = history.record(
                prompt="Test", status="success", started_at="2026-01-01T00:00:00Z"
            )
        assert exec_id != ""

    def test_record_chama_insert(self, history):
        """record() deve executar INSERT na tabela execution_history."""
        ctx, mock_conn = _make_ctx()
        with patch("src.history.get_connection", return_value=ctx):
            history.record(
                prompt="Test", status="success", started_at="2026-01-01T00:00:00Z"
            )
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO execution_history" in sql

    def test_record_retorna_vazio_em_erro(self, history):
        """record() deve retornar string vazia em caso de exceção."""
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=Exception("DB error"))
        ctx.__exit__ = MagicMock(return_value=False)

        with patch("src.history.get_connection", return_value=ctx):
            result = history.record("prompt", "error", "2026-01-01T00:00:00Z")
        assert result == ""


@pytest.mark.unit
class TestExecutionHistoryGet:
    def test_get_retorna_record(self, history):
        """get() deve retornar ExecutionRecord quando a row existe."""
        row = _make_row()
        ctx, _ = _make_ctx(fetchone=row)
        with patch("src.history.get_connection", return_value=ctx):
            record = history.get("exec-1")
        assert record is not None
        assert record.id == "exec-1"
        assert record.status == "success"

    def test_get_retorna_none_se_nao_encontrado(self, history):
        """get() deve retornar None se a row não existir."""
        ctx, _ = _make_ctx(fetchone=None)
        with patch("src.history.get_connection", return_value=ctx):
            result = history.get("inexistente")
        assert result is None


@pytest.mark.unit
class TestExecutionHistoryList:
    def test_list_recent_retorna_lista(self, history):
        """list_recent() deve retornar lista de ExecutionRecord."""
        rows = [_make_row("e1", "P1"), _make_row("e2", "P2")]
        ctx, mock_conn = _make_ctx(fetchall=rows)
        with patch("src.history.get_connection", return_value=ctx):
            records = history.list_recent(limit=2)
        assert len(records) == 2
        sql = mock_conn.execute.call_args[0][0]
        assert "LIMIT" in sql

    def test_search_usa_ilike(self, history):
        """search() deve usar ILIKE no SQL."""
        ctx, mock_conn = _make_ctx(fetchall=[])
        with patch("src.history.get_connection", return_value=ctx):
            history.search("gato")
        sql = mock_conn.execute.call_args[0][0]
        assert "ILIKE" in sql

    def test_list_recent_retorna_vazio_em_erro(self, history):
        """list_recent() deve retornar lista vazia em caso de exceção."""
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=Exception("DB error"))
        ctx.__exit__ = MagicMock(return_value=False)
        with patch("src.history.get_connection", return_value=ctx):
            result = history.list_recent()
        assert result == []
