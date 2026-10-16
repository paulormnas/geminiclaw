"""Testes do auxiliar compartilhado ``FakeRecordingProvider`` (v18.7-benchmark-fixes, tarefa 3.0)."""

from __future__ import annotations

import asyncio
import time

import pytest

from src.llm.base import LLMResponse
from src.llm.quota import ProviderQuotaExhausted
from tests.support.fake_recording_provider import FakeRecordingProvider, ScriptedError

pytestmark = pytest.mark.unit


def _run(coro):
    return asyncio.run(coro)


def test_registra_system_e_messages_por_chamada():
    provider = FakeRecordingProvider(script=["a", "b"])
    _run(provider.generate([{"role": "user", "content": "1"}], system="S1"))
    _run(provider.generate([{"role": "user", "content": "2"}], system="S2", tools=[{"type": "function"}]))
    assert [c.system for c in provider.calls] == ["S1", "S2"]
    assert provider.calls[1].messages == [{"role": "user", "content": "2"}] and provider.calls[1].tools


def test_respostas_roteirizadas_em_ordem_e_a_ultima_se_repete():
    provider = FakeRecordingProvider(script=["a", LLMResponse(text="b")])
    texts = [_run(provider.generate([])).text for _ in range(4)]
    assert texts == ["a", "b", "b", "b"]
    assert _run(FakeRecordingProvider().generate([])).text == "ok"


def test_latencia_simulada():
    provider = FakeRecordingProvider(latency_seconds=0.05)
    start = time.monotonic()
    _run(provider.generate([]))
    assert time.monotonic() - start >= 0.05


def test_erros_roteirizados():
    provider = FakeRecordingProvider(script=[
        FakeRecordingProvider.rate_limit_error(),
        FakeRecordingProvider.service_unavailable(),
        FakeRecordingProvider.spending_cap_error(),
        FakeRecordingProvider.quota_exhausted("anthropic", "claude", 400),
        "fim",
    ])
    errors = []
    for _ in range(4):
        with pytest.raises(Exception) as caught:
            _run(provider.generate([]))
        errors.append(caught.value)
    assert [getattr(e, "status_code", None) for e in errors] == [429, 503, 429, 400]
    assert "spending cap" in str(errors[2]) and "spending cap" not in str(errors[0])
    assert isinstance(errors[0], ScriptedError) and isinstance(errors[3], ProviderQuotaExhausted)
    assert _run(provider.generate([])).text == "fim"
