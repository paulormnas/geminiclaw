"""Testes V11.4.1 — Payload Offloading no TelemetryCollector.

Verifica que payloads extensos (> 1000 chars) são salvos em arquivo
.json.gz e que o banco recebe apenas o caminho relativo.
"""

from __future__ import annotations

import gzip
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.telemetry import TelemetryCollector, _PAYLOAD_INLINE_LIMIT


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_collector() -> TelemetryCollector:
    col = TelemetryCollector()
    col._buffer_size = 10_000
    return col


# ---------------------------------------------------------------------------
# _offload_payload
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOffloadPayload:
    def test_payload_curto_retornado_inline(self, tmp_path: Path):
        """Payloads <= _PAYLOAD_INLINE_LIMIT chars devem ser retornados sem offload."""
        col = _make_collector()
        short = "x" * _PAYLOAD_INLINE_LIMIT
        result = col._offload_payload(short, "sess-abc", "args")
        assert result == short
        # Nenhum arquivo deve ter sido criado
        assert not (tmp_path / "logs").exists()

    def test_payload_longo_salvo_em_arquivo(self, tmp_path: Path, monkeypatch):
        """Payloads > _PAYLOAD_INLINE_LIMIT devem ser salvos em .json.gz."""
        col = _make_collector()
        long_payload = "y" * (_PAYLOAD_INLINE_LIMIT + 1)

        # Redireciona Path("logs/...") para tmp_path
        monkeypatch.chdir(tmp_path)

        result = col._offload_payload(long_payload, "sess-xyz", "result")

        assert result.startswith("file://logs/sess-xyz/payloads/")
        assert result.endswith("_result.json.gz")

        # Arquivo deve existir e conteúdo deve ser o payload original
        relative = result.replace("file://", "")
        file_path = tmp_path / relative
        assert file_path.exists(), f"Arquivo offloaded não encontrado: {file_path}"

        with gzip.open(file_path, "rt", encoding="utf-8") as fh:
            content = fh.read()
        assert content == long_payload

    def test_multiplos_offloads_criam_arquivos_distintos(self, tmp_path: Path, monkeypatch):
        """Cada chamada a _offload_payload deve criar um arquivo com UUID único."""
        col = _make_collector()
        monkeypatch.chdir(tmp_path)
        long_payload = "z" * (_PAYLOAD_INLINE_LIMIT + 100)

        ref1 = col._offload_payload(long_payload, "sess1", "args")
        ref2 = col._offload_payload(long_payload, "sess1", "args")

        assert ref1 != ref2, "Referências de arquivos distintos devem ser únicas"


# ---------------------------------------------------------------------------
# record_tool_usage com offloading
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolUsageWithOffloading:
    def test_argumentos_longos_sao_offloaded(self, tmp_path: Path, monkeypatch):
        """Argumentos > 1000 chars devem ser offloaded."""
        col = _make_collector()
        monkeypatch.chdir(tmp_path)

        big_args = {"data": "A" * 2000}
        col.record_tool_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="agent",
            tool_name="python_interpreter",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            duration_ms=1000,
            success=True,
            arguments=big_args,
        )

        row = col._buffer.tool_usage[0]
        assert row.arguments_json is not None
        assert row.arguments_json.startswith("file://"), (
            "Argumentos longos devem ser referenciados por caminho"
        )

    def test_argumentos_curtos_ficam_inline(self, tmp_path: Path, monkeypatch):
        """Argumentos <= 1000 chars devem ficar inline."""
        col = _make_collector()
        monkeypatch.chdir(tmp_path)

        small_args = {"query": "busca simples"}
        col.record_tool_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="agent",
            tool_name="quick_search",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            duration_ms=200,
            success=True,
            arguments=small_args,
        )

        row = col._buffer.tool_usage[0]
        assert row.arguments_json is not None
        assert not row.arguments_json.startswith("file://"), (
            "Argumentos curtos devem ficar inline"
        )
        parsed = json.loads(row.arguments_json)
        assert parsed["query"] == "busca simples"

    def test_resultado_longo_offloaded(self, tmp_path: Path, monkeypatch):
        """Resultados > 1000 chars devem ser offloaded."""
        col = _make_collector()
        monkeypatch.chdir(tmp_path)

        big_result = "resultado " * 200  # ~2000 chars
        col.record_tool_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="agent",
            tool_name="deep_search",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:02Z",
            duration_ms=2000,
            success=True,
            result_summary=big_result,
        )

        row = col._buffer.tool_usage[0]
        assert row.result_summary is not None
        assert row.result_summary.startswith("file://"), (
            "Resultado longo deve ser referenciado por caminho"
        )

    def test_resultado_curto_truncado_em_500(self):
        """Resultados <= 1000 chars devem ser truncados em 500 chars inline."""
        col = _make_collector()
        result_600 = "r" * 600

        col.record_tool_usage(
            execution_id="exec1",
            session_id="sess1",
            agent_id="agent",
            tool_name="quick_search",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            duration_ms=100,
            success=True,
            result_summary=result_600,
        )

        row = col._buffer.tool_usage[0]
        assert row.result_summary is not None
        assert len(row.result_summary) == 500, (
            "Inline result deve ser truncado em 500 chars"
        )
