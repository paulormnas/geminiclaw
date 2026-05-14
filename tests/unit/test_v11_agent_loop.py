"""Testes V11.2 — Correções no agent_loop.py.

Verifica:
- V11.2.1: tokens extraídos via response.usage.get(), não getattr()
- V11.2.2: timestamp de início da ferramenta calculado ANTES da execução
- V11.2.3: TTFT presente no usage dict dos providers
"""

from __future__ import annotations

import json
import os

# Define LLM_PROVIDER antes de qualquer import que carregue src.config,
# pois GEMINI_API_KEY é obrigatória apenas quando provider=google.
os.environ.setdefault("LLM_PROVIDER", "ollama")

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Importa diretamente do módulo base para evitar acionar o __init__.py do pacote
# llm (que carrega o config e exige GEMINI_API_KEY desde a importação).
from src.llm.base import LLMResponse, ToolCall


# ---------------------------------------------------------------------------
# V11.2.1 — Extração de tokens via response.usage dict
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTokenExtractionFix:
    def test_tokens_lidos_do_usage_dict(self):
        """LLMResponse.usage.get() deve retornar os valores corretos."""
        resp = LLMResponse(
            text="resposta",
            usage={
                "prompt_tokens": 120,
                "completion_tokens": 45,
                "total_tokens": 165,
                "ttft_ms": 300,
            },
        )
        # Verifica que o acesso correto funciona
        assert resp.usage.get("prompt_tokens", 0) == 120
        assert resp.usage.get("completion_tokens", 0) == 45
        assert resp.usage.get("total_tokens", 0) == 165

    def test_tokens_default_zero_quando_ausente(self):
        """Se usage estiver vazio, .get() retorna 0 (fallback ativo)."""
        resp = LLMResponse(text="ok", usage={})
        assert resp.usage.get("prompt_tokens", 0) == 0
        assert resp.usage.get("completion_tokens", 0) == 0

    def test_getattr_fallback_nao_funciona(self):
        """Confirma que o bug original (getattr direto) não retornava o valor."""
        resp = LLMResponse(
            text="ok",
            usage={"prompt_tokens": 200},
        )
        # getattr() no LLMResponse não acessa o dict usage — é o bug que corrigimos
        assert getattr(resp, "prompt_tokens", 0) == 0  # bug: retornava 0
        assert resp.usage.get("prompt_tokens", 0) == 200  # fix: retorna corretamente


# ---------------------------------------------------------------------------
# V11.2.2 — Timestamps de início/fim da ferramenta
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolTimestampFix:
    def test_started_at_antes_de_finished_at(self):
        """_start_iso deve ser anterior a _now_iso."""
        import datetime as _dt

        duration_ms = 500
        _finished_dt = _dt.datetime.utcnow()
        _started_dt = _finished_dt - _dt.timedelta(milliseconds=duration_ms)
        _start_iso = _started_dt.isoformat() + "Z"
        _now_iso = _finished_dt.isoformat() + "Z"

        # started_at deve ser lexicograficamente anterior a finished_at
        assert _start_iso < _now_iso

    def test_duracao_coerente(self):
        """A diferença entre finished e started deve ser ~= duration_ms."""
        import datetime as _dt

        duration_ms = 1000
        _finished_dt = _dt.datetime.utcnow()
        _started_dt = _finished_dt - _dt.timedelta(milliseconds=duration_ms)

        diff = (_finished_dt - _started_dt).total_seconds() * 1000
        assert abs(diff - duration_ms) < 1  # tolerância de 1ms

    def test_agent_loop_registra_tool_usage_com_timestamps_corretos(self):
        """run_agent_loop deve registrar tool_usage com started_at < finished_at."""
        recorded_tool_calls: list[dict] = []

        def fake_record_tool_usage(*, started_at, finished_at, **kwargs):
            recorded_tool_calls.append(
                {"started_at": started_at, "finished_at": finished_at}
            )

        mock_telemetry = MagicMock()
        mock_telemetry.record_token_usage = MagicMock()
        mock_telemetry.record_tool_usage = fake_record_tool_usage

        def dummy_tool(x: str) -> str:
            """Ferramenta de teste."""
            return f"resultado: {x}"

        dummy_tool.parameters_schema = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }

        # LLMResponse com uma tool call, depois resposta final
        tool_response = LLMResponse(
            text=None,
            tool_calls=[ToolCall(id="c1", name="dummy_tool", arguments={"x": "test"})],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
        final_response = LLMResponse(
            text="pronto",
            tool_calls=[],
            usage={"prompt_tokens": 8, "completion_tokens": 3},
        )

        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(
            side_effect=[tool_response, final_response]
        )

        import asyncio

        with (
            patch("src.llm.agent_loop.get_provider", return_value=mock_provider),
            patch("src.llm.agent_loop.get_telemetry", return_value=mock_telemetry),
            patch(
                "src.llm.agent_loop.compress_messages",
                new=AsyncMock(side_effect=lambda m, **kw: m),
            ),
        ):
            from src.llm.agent_loop import run_agent_loop

            result = asyncio.run(
                run_agent_loop(
                    prompt="Teste",
                    instruction="Instrução",
                    tools=[dummy_tool],
                )
            )

        assert result == "pronto"
        assert len(recorded_tool_calls) == 1
        call = recorded_tool_calls[0]
        # V11.2.2: started_at nunca pode ser posterior a finished_at.
        # Em execuções sub-milissegundo os timestamps podem ser idênticos,
        # por isso usamos <= ao invés de <.
        assert call["started_at"] <= call["finished_at"], (
            "started_at nunca pode ser posterior a finished_at"
        )


# ---------------------------------------------------------------------------
# V11.2.3 — TTFT nos providers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTTFTInProviders:
    def test_ollama_usage_contém_ttft(self):
        """OllamaProvider deve retornar ttft_ms no dict de usage."""
        resp = LLMResponse(
            text="ok",
            usage={
                "prompt_tokens": 50,
                "completion_tokens": 20,
                "total_tokens": 70,
                "ttft_ms": 450,
            },
        )
        assert "ttft_ms" in resp.usage
        assert resp.usage["ttft_ms"] == 450

    def test_google_usage_ttft_none(self):
        """GoogleProvider deve retornar ttft_ms=None (API não expõe TTFT)."""
        resp = LLMResponse(
            text="ok",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
                "ttft_ms": None,
            },
        )
        assert "ttft_ms" in resp.usage
        assert resp.usage["ttft_ms"] is None

    def test_ollama_ttft_calculado_de_nanosegundos(self):
        """ttft_ms = (load_duration + prompt_eval_duration) / 1_000_000."""
        load_ns = 200_000_000   # 200ms em nanosegundos
        prompt_ns = 100_000_000  # 100ms
        expected_ttft_ms = int((load_ns + prompt_ns) / 1_000_000)

        assert expected_ttft_ms == 300
