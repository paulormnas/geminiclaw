"""Tabela de preços por modelo e cálculo do custo estimado de cada chamada LLM.

Preços em USD por milhão de tokens (MTok), conforme a página de preços de cada provedor em
2026-09-30. Modelo ausente da tabela tem custo ``None`` (desconhecido), nunca zero: o relatório
mostra "n/d" em vez de esconder o gasto. Sobrescreva ou acrescente modelos com
``LLM_PRICING_OVERRIDES`` (JSON: ``{"provedor/modelo": [entrada, saida, entrada_em_cache]}``).

Regras de cobrança:
- ``prompt_tokens`` já inclui os tokens lidos do cache; a parte em cache usa o preço de cache;
- ``completion_tokens`` inclui os tokens de pensamento/raciocínio, cobrados como saída.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone

from src.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cached_input: float | None = None  # None = mesmo preço da entrada
    # Faixa de prompt longo (ex.: Claude Haiku 5.5 cobra mais caro acima de 100K tokens de entrada): quando
    # ``prompt_tokens`` passa de ``long_threshold`` vale ``long_price`` (a chamada inteira).
    long_threshold: int | None = None
    long_price: "Price | None" = None
    # Vigência: ``promo_until`` é o último dia (UTC) do preço promocional; ``after_promo`` vale depois.
    promo_until: date | None = None
    after_promo: "Price | None" = None


# Fontes: ai.google.dev/gemini-api/docs/pricing (Gemini 4 Argon com preço promocional até
# 2026-11-30; a partir de 2026-12-01 dobra; conferido em 2026-10-14), developers.openai.com/api/docs/pricing e a
# tabela de modelos da Anthropic. Modelos de maior porte ficam de fora de propósito.
PRICES: dict[str, Price] = {
    "google/gemini-4-argon": Price(
        2.0, 10.0, 0.10, promo_until=date(2026, 11, 30), after_promo=Price(4.0, 20.0, 0.20)
    ),
    "google/gemini-3.5-flash-lite": Price(0.30, 2.50, 0.03),
    "google/gemini-3.1-flash-lite": Price(0.25, 1.50, 0.025),
    "anthropic/claude-sonnet-5-5": Price(2.0, 10.0, 0.20),
    # OpenAI, tier Standard (contexto curto, até 272K tokens), developers.openai.com/api/docs/pricing, 2026-10-13.
    "openai/gpt-6-luna": Price(0.10, 0.50, 0.01),
    "openai/gpt-6.1-sol": Price(2.0, 10.0, 0.10, long_threshold=272_000, long_price=Price(4.0, 15.0, 0.20)),
    # Fonte secundária (a página oficial não foi consultada): Haiku 5.5 US$ 0,10 / 0,50 até 100K tokens de entrada e
    # US$ 0,50 / 2,50 acima. Confira a página do provedor antes de usar como cobrança.
    "anthropic/claude-haiku-5-5": Price(
        0.10, 0.50, 0.01, long_threshold=100_000, long_price=Price(0.50, 2.50, 0.05)
    ),
}

_warned: set[str] = set()


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _price_on(key: str, price: Price, today: date) -> Price:
    """Aplica a vigência: depois de ``promo_until`` vale ``after_promo``; sem ele, o último preço (com aviso)."""
    if price.promo_until is None or today <= price.promo_until:
        return price
    if price.after_promo is not None:
        return price.after_promo
    warn_key = f"vigencia:{key}"
    if warn_key not in _warned:
        _warned.add(warn_key)
        logger.warning(
            "Vigência do preço vencida sem preço posterior; usando o último preço conhecido",
            extra={"model": key, "promo_until": price.promo_until.isoformat()},
        )
    return price


def _overrides() -> dict[str, Price]:
    raw = os.environ.get("LLM_PRICING_OVERRIDES", "").strip()
    if not raw:
        return {}
    try:
        return {key.lower(): Price(*values) for key, values in json.loads(raw).items()}
    except (ValueError, TypeError) as exc:
        raise ValueError(f"LLM_PRICING_OVERRIDES inválida (JSON provedor/modelo -> [in, out, cache]): {exc}") from exc


def get_price(provider: str, model: str) -> Price | None:
    key = f"{provider}/{model}".lower()
    return _overrides().get(key) or PRICES.get(key)


def estimate_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    today: Callable[[], date] = _utc_today,
) -> float | None:
    """Custo estimado em USD da chamada, ou ``None`` se o modelo não tem preço conhecido."""
    price = get_price(provider, model)
    if price is None:
        key = f"{provider}/{model}"
        if key not in _warned:
            _warned.add(key)
            logger.warning("Preço desconhecido; configure LLM_PRICING_OVERRIDES", extra={"model": key})
        return None
    price = _price_on(f"{provider}/{model}", price, today())
    if price.long_price is not None and price.long_threshold is not None and prompt_tokens > price.long_threshold:
        price = price.long_price
    cached = min(max(cached_tokens, 0), prompt_tokens)
    cached_rate = price.input if price.cached_input is None else price.cached_input
    fresh_cost = (prompt_tokens - cached) * price.input
    return (fresh_cost + cached * cached_rate + completion_tokens * price.output) / 1_000_000
