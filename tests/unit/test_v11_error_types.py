"""Testes V11.4.2 — ErrorType Enum com armazenamento em string no banco.

Verifica que:
- ErrorType é um Enum Python com valores string legíveis
- O banco recebe apenas a string .value (não o nome do Enum)
- from_str() converte corretamente e retorna UNKNOWN para valores desconhecidos
- record_subtask_metrics() aceita a string e não serializa o objeto Enum
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.telemetry import ErrorType, TelemetryCollector, _Buffer


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_collector() -> TelemetryCollector:
    col = TelemetryCollector()
    col._buffer_size = 10_000
    return col


# ---------------------------------------------------------------------------
# ErrorType — comportamento do Enum
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestErrorTypeEnum:
    def test_valores_sao_strings_legíveis(self):
        """Os valores do Enum devem ser strings uppercase (não nomes de classe)."""
        assert ErrorType.TIMEOUT.value == "TIMEOUT"
        assert ErrorType.AUTH_FAILURE.value == "AUTH_FAILURE"
        assert ErrorType.OOM_KILLED.value == "OOM_KILLED"
        assert ErrorType.INVALID_FORMAT.value == "INVALID_FORMAT"
        assert ErrorType.TOOL_ERROR.value == "TOOL_ERROR"
        assert ErrorType.LLM_ERROR.value == "LLM_ERROR"
        assert ErrorType.NETWORK_ERROR.value == "NETWORK_ERROR"
        assert ErrorType.UNKNOWN.value == "UNKNOWN"

    def test_from_str_converte_string_valida(self):
        """from_str() deve retornar o membro correspondente para strings válidas."""
        assert ErrorType.from_str("TIMEOUT") == ErrorType.TIMEOUT
        assert ErrorType.from_str("AUTH_FAILURE") == ErrorType.AUTH_FAILURE
        assert ErrorType.from_str("OOM_KILLED") == ErrorType.OOM_KILLED

    def test_from_str_retorna_none_para_none(self):
        """from_str(None) deve retornar None."""
        assert ErrorType.from_str(None) is None

    def test_from_str_retorna_unknown_para_valor_desconhecido(self):
        """from_str() deve retornar ErrorType.UNKNOWN para strings não reconhecidas."""
        result = ErrorType.from_str("ERRO_ESTRANHO_QUALQUER")
        assert result == ErrorType.UNKNOWN

    def test_from_str_case_insensitive(self):
        """from_str() deve aceitar strings em qualquer capitalização."""
        assert ErrorType.from_str("timeout") == ErrorType.TIMEOUT
        assert ErrorType.from_str("Oom_Killed") == ErrorType.OOM_KILLED

    def test_valor_e_uma_string_simples(self):
        """O valor do Enum deve ser diretamente inserível no banco como string."""
        error_str = ErrorType.TIMEOUT.value
        assert isinstance(error_str, str)
        # Simula o que o banco recebe: a string pura
        assert error_str == "TIMEOUT"


# ---------------------------------------------------------------------------
# record_subtask_metrics — error_type como string
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubtaskMetricsErrorType:
    def test_error_type_string_registrado_no_buffer(self):
        """record_subtask_metrics deve aceitar a string de ErrorType."""
        col = _make_collector()
        col.record_subtask_metrics(
            subtask_id="sub1",
            execution_id="exec1",
            task_name="task_a",
            agent_id="planner",
            status="failure",
            created_at="2026-01-01T00:00:00Z",
            error_type=ErrorType.TIMEOUT.value,  # string, não o Enum
        )

        row = col._buffer.subtask_metrics[0]
        # O campo no dataclass deve ser a string pura
        assert row.error_type == "TIMEOUT"
        assert isinstance(row.error_type, str)

    def test_error_type_none_quando_sucesso(self):
        """Subtarefas bem-sucedidas devem ter error_type=None."""
        col = _make_collector()
        col.record_subtask_metrics(
            subtask_id="sub2",
            execution_id="exec1",
            task_name="task_b",
            agent_id="researcher",
            status="success",
            created_at="2026-01-01T00:00:00Z",
        )

        row = col._buffer.subtask_metrics[0]
        assert row.error_type is None

    def test_banco_recebe_string_nao_objeto_enum(self):
        """_write_snapshot deve inserir a string no banco, não o objeto ErrorType."""
        col = _make_collector()
        col.record_subtask_metrics(
            subtask_id="sub3",
            execution_id="exec1",
            task_name="task_c",
            agent_id="validator",
            status="failure",
            created_at="2026-01-01T00:00:00Z",
            error_type=ErrorType.LLM_ERROR.value,
        )

        snap = col._buffer
        col._buffer = _Buffer()

        captured_params: list[tuple] = []

        def fake_execute(sql, params=None):
            if params:
                captured_params.append(params)
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = None
            mock_cursor.fetchall.return_value = []
            return mock_cursor

        mock_conn = MagicMock()
        mock_conn.execute = fake_execute
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_conn)
        ctx.__exit__ = MagicMock(return_value=False)

        with patch("src.telemetry.get_connection", return_value=ctx):
            col._write_snapshot(snap)

        # Encontra o INSERT de subtask_metrics nos parâmetros capturados
        subtask_params = None
        for params in captured_params:
            # O INSERT de subtask_metrics tem 14 campos; o error_type é o último
            if len(params) == 14:
                subtask_params = params
                break

        assert subtask_params is not None, "INSERT de subtask_metrics não encontrado"
        # error_type é o último parâmetro
        error_type_value = subtask_params[-1]
        assert error_type_value == "LLM_ERROR", (
            f"Esperava 'LLM_ERROR', recebeu: {error_type_value!r}"
        )
        assert isinstance(error_type_value, str), "error_type deve ser string pura no banco"


# ---------------------------------------------------------------------------
# Assinatura lean de record_subtask_metrics (V11.3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubtaskMetricsLeanSchema:
    def test_campos_removidos_nao_sao_parametros(self):
        """record_subtask_metrics não deve aceitar campos da V10 removidos."""
        import inspect

        from src.telemetry import TelemetryCollector

        sig = inspect.signature(TelemetryCollector.record_subtask_metrics)
        params = set(sig.parameters.keys())

        removed_fields = {
            "cpu_usage_avg",
            "mem_usage_peak_mb",
            "temp_delta_c",
            "waiting_time_ms",
            "total_tokens",
            "tools_used_count",
        }

        present = removed_fields & params
        assert not present, (
            f"Campos removidos pelo V11.3 ainda presentes na assinatura: {present}"
        )

    def test_campos_mantidos_presentes(self):
        """Campos essenciais devem permanecer na assinatura."""
        import inspect

        from src.telemetry import TelemetryCollector

        sig = inspect.signature(TelemetryCollector.record_subtask_metrics)
        params = set(sig.parameters.keys())

        required_fields = {
            "subtask_id",
            "execution_id",
            "task_name",
            "agent_id",
            "status",
            "created_at",
            "total_cost_usd",
            "llm_calls_count",
            "retry_count",
            "error_type",
        }

        missing = required_fields - params
        assert not missing, f"Campos obrigatórios ausentes da assinatura: {missing}"
