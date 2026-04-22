import pytest
import asyncio
import time
from src.rate_limiter import AdaptiveRateLimiter

@pytest.fixture
def rate_limiter():
    # Usa valores curtos para facilitar o teste sem esperar muito
    return AdaptiveRateLimiter(requests_per_minute=60, cooldown_seconds=1, min_requests_per_minute=10)

@pytest.mark.asyncio
async def test_acquire_tokens_available(rate_limiter):
    # Deve ser imediato, pois inicializa com `requests_per_minute` tokens (60)
    start_time = time.monotonic()
    await rate_limiter.acquire()
    await rate_limiter.acquire()
    await rate_limiter.acquire()
    duration = time.monotonic() - start_time
    assert duration < 0.1  # Deve rodar quase instantaneamente

@pytest.mark.asyncio
async def test_acquire_waits_when_empty():
    # Taxa de 60 rpm = 1 request por segundo
    limiter = AdaptiveRateLimiter(requests_per_minute=60)
    limiter.tokens = 0.0  # Zera tokens
    limiter.last_update = time.monotonic()
    
    start_time = time.monotonic()
    await limiter.acquire()
    duration = time.monotonic() - start_time
    
    # Como estava zerado, precisou esperar 1 segundo (±0.1s de margem de erro)
    assert 0.9 <= duration <= 1.2

@pytest.mark.asyncio
async def test_report_429_applies_backoff_and_halves_rpm(rate_limiter):
    assert rate_limiter.current_rpm == 60
    
    await rate_limiter.report_429()
    
    assert rate_limiter.consecutive_429s == 1
    assert rate_limiter.current_rpm == 30
    assert rate_limiter.tokens == 0.0
    
    # Tentar adquirir agora deve sofrer o cooldown de 1s (cooldown base da fixture)
    start_time = time.monotonic()
    await rate_limiter.acquire()
    duration = time.monotonic() - start_time
    
    # Cooldown 1s + tempo de token novo
    assert duration >= 0.9

@pytest.mark.asyncio
async def test_report_success_restores_rpm(rate_limiter):
    await rate_limiter.report_429()
    assert rate_limiter.current_rpm == 30
    
    # Sucesso restaura 1 RPM
    await rate_limiter.report_success()
    assert rate_limiter.current_rpm == 31
    assert rate_limiter.consecutive_429s == 0
    
    # Vários sucessos restauram até o limite base
    for _ in range(50):
        await rate_limiter.report_success()
        
    assert rate_limiter.current_rpm == 60  # Não passa do base_rpm
