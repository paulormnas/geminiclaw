"""Preço com vigência e preços do Gemini 4 Argon e do GPT-6.1 Sol (v18.6-models-gemini4-gpt6)."""

from __future__ import annotations

import logging
from datetime import date

import pytest

from src.llm import pricing

pytestmark = pytest.mark.unit


def _on(day: date):
    return lambda: day


def test_dentro_da_promocao() -> None:
    cost = pricing.estimate_cost("google", "gemini-4-argon", 1_000_000, 100_000, today=_on(date(2026, 11, 30)))
    assert cost == pytest.approx(3.0)


def test_depois_da_promocao() -> None:
    cost = pricing.estimate_cost("google", "gemini-4-argon", 1_000_000, 100_000, today=_on(date(2026, 12, 1)))
    assert cost == pytest.approx(6.0)


def test_contexto_longo_do_gpt_sol() -> None:
    cost = pricing.estimate_cost("openai", "gpt-6.1-sol", 300_000, 10_000)
    assert cost == pytest.approx(4.0 * 0.3 + 15.0 * 0.01)


def test_cache_do_gpt_sol() -> None:
    cost = pricing.estimate_cost("openai", "gpt-6.1-sol", 1_000, 0, cached_tokens=800)
    assert cost == pytest.approx((800 * 0.10 + 200 * 2.0) / 1e6)


def test_vigencia_vencida_sem_preco_posterior_avisa(monkeypatch, caplog) -> None:
    price = pricing.Price(1.0, 2.0, 0.1, promo_until=date(2020, 1, 1))
    monkeypatch.setitem(pricing.PRICES, "x/modelo-vencido", price)
    pricing._warned.discard("vigencia:x/modelo-vencido")
    with caplog.at_level(logging.WARNING):
        cost = pricing.estimate_cost("x", "modelo-vencido", 1_000_000, 0, today=_on(date(2026, 10, 14)))
    assert cost == pytest.approx(1.0)
    assert any("Vigência" in r.getMessage() for r in caplog.records)


def test_override_vence_a_vigencia(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PRICING_OVERRIDES", '{"google/gemini-4-argon": [1.0, 1.0, 1.0]}')
    cost = pricing.estimate_cost("google", "gemini-4-argon", 1_000_000, 0, today=_on(date(2027, 1, 1)))
    assert cost == pytest.approx(1.0)
