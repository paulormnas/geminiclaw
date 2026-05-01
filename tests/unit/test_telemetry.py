"""Testes unitários para src/telemetry.py.

Verifica inserções no buffer, flush no banco (mocked) e queries de análise.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from src.telemetry import TelemetryCollector, _Buffer, get_telemetry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn_ctx(fetchone=None, fetchall=None) -> tuple[MagicMock, MagicMock]:
    """Cria um context manager mock para get_connection."""
    mock_conn = MagicMock()
    cursor = MagicMock()
    mock_conn.execute.return_value = cursor
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall or []
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, mock_conn


def _make_collector() -> TelemetryCollector:
    """Cria um TelemetryCollector com buffer_size grande (sem auto-flush nos testes)."""
    col = TelemetryCollector()
    col._buffer_size = 10_000  # evita flushes automáticos durante os testes
    return col


# ---------------------------------------------------------------------------
# Fase 1: Buffer — record_agent_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordAgentEvent:
    def test_adiciona_ao_buffer(self):
        """record_agent_event deve adicionar exatamente 1 item ao buffer."""
        col = _make_collector()
        col.record_agent_event(
            execution_id="exec1",
            session_id="sess1",
            agent_id="planner",
            event_type="spawn",
            task_name="search_papers",
        )
        assert len(col._buffer.agent_events) == 1

    def test_dados_corretos(self):
        """Verifica que todos os campos são preenchidos corretamente."""
        col = _make_collector()
        col.record_agent_event(
            execution_id="exec1",
            session_id="sess1",
            agent_id="validator",
            event_type="plan_validated",
            target_agent_id="planner",
            task_name="validate",
            payload={"status": "approved"},
            duration_ms=250,
        )
        row = col._buffer.agent_events[0]
        assert row.execution_id == "exec1"
        assert row.agent_id == "validator"
        assert row.event_type == "plan_validated"
        assert row.target_agent_id == "planner"
        assert row.task_name == "validate"
        assert row.duration_ms == 250
        assert "approved" in (row.payload_json or "")

    def test_multiplos_registros(self):
        """Múltiplas chamadas incrementam o buffer corretamente."""
        col = _make_collector()
        for i in range(5):
            col.record_agent_event(
                execution_id=f"exec{i}",
                session_id="sess",
                agent_id="base",
                event_type="complete",
            )
        assert len(col._buffer.agent_events) == 5


# ---------------------------------------------------------------------------
# Buffer — record_tool_usage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordToolUsage:
    def test_adiciona_ao_buffer(self):
        col = _make_collector()
        col.record_tool_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="base",
            tool_name="quick_search",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
            duration_ms=1000,
            success=True,
            result_summary="Found 5 results",
        )
        assert len(col._buffer.tool_usage) == 1

    def test_result_summary_truncado(self):
        """result_summary deve ser truncado em 500 caracteres."""
        col = _make_collector()
        long_result = "X" * 600
        col.record_tool_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="base",
            tool_name="deep_search",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
            duration_ms=500,
            success=True,
            result_summary=long_result,
        )
        row = col._buffer.tool_usage[0]
        assert len(row.result_summary) == 500

    def test_falha_registra_error_message(self):
        col = _make_collector()
        col.record_tool_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="base",
            tool_name="python_interpreter",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:00:01+00:00",
            duration_ms=100,
            success=False,
            error_message="SyntaxError: invalid syntax",
        )
        row = col._buffer.tool_usage[0]
        assert row.success is False
        assert "SyntaxError" in (row.error_message or "")


# ---------------------------------------------------------------------------
# Buffer — record_token_usage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordTokenUsage:
    def test_adiciona_ao_buffer(self):
        col = _make_collector()
        col.record_token_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="base",
            llm_provider="ollama",
            llm_model="qwen3.5:4b",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=2000,
        )
        assert len(col._buffer.token_usage) == 1

    def test_total_tokens_calculado(self):
        col = _make_collector()
        col.record_token_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="base",
            llm_provider="google",
            llm_model="gemini-2.0-flash",
            prompt_tokens=300,
            completion_tokens=150,
            latency_ms=1000,
        )
        row = col._buffer.token_usage[0]
        assert row.total_tokens == 450

    def test_campos_opcionais_sao_none_por_padrao(self):
        col = _make_collector()
        col.record_token_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="base",
            llm_provider="ollama",
            llm_model="qwen3.5:4b",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=500,
        )
        row = col._buffer.token_usage[0]
        assert row.task_name is None
        assert row.estimated_cost_usd is None
        assert row.context_window_used is None
        assert row.was_compressed is False


# ---------------------------------------------------------------------------
# Buffer — record_hardware_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecordHardwareSnapshot:
    def test_adiciona_ao_buffer(self):
        col = _make_collector()
        col.record_hardware_snapshot(
            execution_id="exec1",
            cpu_temp_c=55.0,
            mem_usage_pct=60.0,
        )
        assert len(col._buffer.hardware_snapshots) == 1

    def test_campos_opcionais(self):
        col = _make_collector()
        col.record_hardware_snapshot()  # sem argumentos — coleta periódica
        row = col._buffer.hardware_snapshots[0]
        assert row.execution_id is None
        assert row.cpu_temp_c is None
        assert row.timestamp  # timestamp gerado automaticamente


# ---------------------------------------------------------------------------
# Buffer total e flush
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuffer:
    def test_total_correto(self):
        buf = _Buffer()
        # adiciona 2 eventos, 1 tool, 1 token
        from src.telemetry import _AgentEventRow, _ToolUsageRow

        buf.agent_events.append(MagicMock(spec=_AgentEventRow))
        buf.agent_events.append(MagicMock(spec=_AgentEventRow))
        buf.tool_usage.append(MagicMock(spec=_ToolUsageRow))
        assert buf.total() == 3

    def test_buffer_vazio(self):
        buf = _Buffer()
        assert buf.total() == 0


@pytest.mark.unit
class TestFlush:
    def test_flush_limpa_buffer(self):
        """Após flush() o buffer deve ficar vazio."""
        col = _make_collector()
        col.record_agent_event(
            execution_id="exec1",
            session_id="sess1",
            agent_id="base",
            event_type="spawn",
        )
        assert col._buffer.total() > 0

        ctx, _ = _make_conn_ctx()
        with patch("src.telemetry.TelemetryCollector._write_snapshot") as mock_write:
            asyncio.get_event_loop().run_until_complete(col.flush())

        assert col._buffer.total() == 0

    def test_flush_chama_write_snapshot(self):
        """flush() deve chamar _write_snapshot com o snapshot correto."""
        col = _make_collector()
        col.record_agent_event(
            execution_id="exec1",
            session_id="sess1",
            agent_id="planner",
            event_type="plan_generated",
        )
        col.record_token_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="planner",
            llm_provider="ollama",
            llm_model="qwen3.5:4b",
            prompt_tokens=50,
            completion_tokens=20,
            latency_ms=900,
        )

        captured_snapshots = []

        def _fake_write(snapshot):
            captured_snapshots.append(snapshot)

        col._write_snapshot = _fake_write
        asyncio.get_event_loop().run_until_complete(col.flush())

        assert len(captured_snapshots) == 1
        snap = captured_snapshots[0]
        assert len(snap.agent_events) == 1
        assert len(snap.token_usage) == 1

    def test_flush_vazio_nao_chama_write(self):
        """flush() com buffer vazio não deve chamar _write_snapshot."""
        col = _make_collector()
        called = []
        col._write_snapshot = lambda s: called.append(s)
        asyncio.get_event_loop().run_until_complete(col.flush())
        assert len(called) == 0

    def test_write_snapshot_insere_agent_events(self):
        """_write_snapshot deve executar INSERT INTO agent_events."""
        col = _make_collector()
        col.record_agent_event(
            execution_id="exec1",
            session_id="sess1",
            agent_id="base",
            event_type="complete",
        )
        snap = col._buffer
        col._buffer = _Buffer()  # limpa buffer manualmente

        ctx, mock_conn = _make_conn_ctx()
        with patch("src.telemetry.get_connection", return_value=ctx):
            col._write_snapshot(snap)

        # Verifica que execute foi chamado ao menos uma vez
        assert mock_conn.execute.call_count >= 1
        # Verifica que o primeiro INSERT é para agent_events
        first_sql = mock_conn.execute.call_args_list[0][0][0]
        assert "INSERT INTO agent_events" in first_sql


# ---------------------------------------------------------------------------
# Queries de análise
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueries:
    def test_get_execution_timeline(self):
        """get_execution_timeline deve retornar lista de dicts."""
        col = _make_collector()
        rows = [
            {
                "agent_id": "planner",
                "event_type": "spawn",
                "task_name": None,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "duration_ms": None,
                "payload_json": None,
            }
        ]
        ctx, _ = _make_conn_ctx(fetchall=rows)
        with patch("src.telemetry.get_connection", return_value=ctx):
            timeline = col.get_execution_timeline("exec1")
        assert len(timeline) == 1
        assert timeline[0]["agent_id"] == "planner"

    def test_get_token_summary_retorna_dict(self):
        """get_token_summary deve retornar dict com 'by_provider_model'."""
        col = _make_collector()
        rows = [
            {
                "llm_provider": "ollama",
                "llm_model": "qwen3.5:4b",
                "total_prompt_tokens": 200,
                "total_completion_tokens": 100,
                "total_tokens": 300,
                "total_cost_usd": None,
                "avg_latency_ms": 1500.0,
                "calls": 3,
            }
        ]
        ctx, _ = _make_conn_ctx(fetchall=rows)
        with patch("src.telemetry.get_connection", return_value=ctx):
            summary = col.get_token_summary("exec1")
        assert "by_provider_model" in summary
        assert len(summary["by_provider_model"]) == 1

    def test_get_tool_summary_retorna_dict(self):
        """get_tool_summary deve retornar dict com 'by_tool'."""
        col = _make_collector()
        rows = [
            {
                "tool_name": "quick_search",
                "total_calls": 5,
                "successful": 4,
                "avg_duration_ms": 800.0,
                "max_duration_ms": 2000,
            }
        ]
        ctx, _ = _make_conn_ctx(fetchall=rows)
        with patch("src.telemetry.get_connection", return_value=ctx):
            summary = col.get_tool_summary("exec1")
        assert "by_tool" in summary

    def test_get_hardware_peaks_retorna_dict(self):
        """get_hardware_peaks deve retornar dict com pico de temp."""
        col = _make_collector()
        row = {
            "max_temp_c": 72.5,
            "max_cpu_pct": 88.0,
            "max_mem_pct": 75.0,
            "min_mem_available_mb": 512.0,
            "throttle_incidents": 0,
            "snapshot_count": 10,
        }
        ctx, _ = _make_conn_ctx(fetchone=row)
        with patch("src.telemetry.get_connection", return_value=ctx):
            peaks = col.get_hardware_peaks("exec1")
        assert peaks["max_temp_c"] == 72.5

    def test_queries_retornam_vazio_em_erro_db(self):
        """Queries devem retornar estrutura vazia em caso de erro no banco."""
        col = _make_collector()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(side_effect=Exception("DB offline"))
        ctx.__exit__ = MagicMock(return_value=False)
        with patch("src.telemetry.get_connection", return_value=ctx):
            assert col.get_execution_timeline("x") == []
            assert col.get_token_summary("x") == {}
            assert col.get_tool_summary("x") == {}
            assert col.get_hardware_peaks("x") == {}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetTelemetrySingleton:
    def test_retorna_mesma_instancia(self):
        """get_telemetry() deve retornar sempre a mesma instância."""
        import src.telemetry as tel_module

        tel_module._collector = None  # reset singleton
        t1 = get_telemetry()
        t2 = get_telemetry()
        assert t1 is t2

    def test_instancia_e_telemetry_collector(self):
        import src.telemetry as tel_module

        tel_module._collector = None
        t = get_telemetry()
        assert isinstance(t, TelemetryCollector)
