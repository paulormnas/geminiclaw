"""Esgotamento de cota distinto de limite de taxa (v18.7-benchmark-fixes, specs ``llm-providers``)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import httpx2
import pytest
import respx

from src import config
from src.llm import quota
from src.llm.metering import bind_execution
from src.llm.providers.anthropic import AnthropicProvider
from src.llm.providers.google import GoogleProvider
from src.llm.providers.openai import OpenAIProvider
from src.llm.providers.openai_compatible import OpenAICompatibleProvider
from src.llm.quota import ProviderQuotaExhausted, is_quota_exhausted, quota_stop_for
from src.llm.rate_limiter import AdaptiveRateLimiter
from src.llm.retry import emit_connection_retry, is_retryable_error
from src.utils.agent_context import AgentContext, bind_agent_context
from tests.support.env_override import env_override
from tests.support.fake_recording_provider import PER_MINUTE_MESSAGE, SPENDING_CAP_MESSAGE, ScriptedError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    quota._recorded.clear()
    telemetry = MagicMock()
    monkeypatch.setattr("src.observability.telemetry.get_telemetry", lambda: telemetry)
    for module in ("google", "anthropic", "openai_compatible"):
        monkeypatch.setattr(f"src.llm.providers.{module}.emit_connection_retry", MagicMock())

        async def _instant(_seconds):
            return None

        monkeypatch.setattr(f"src.llm.providers.{module}.asyncio.sleep", _instant)
    bind_execution("sessao-teste", "sessao-teste")
    yield telemetry
    quota._recorded.clear()
    bind_execution("", "")


# --- classificação -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "status", "message", "expected"),
    [
        ("google", 429, "429 RESOURCE_EXHAUSTED ... exceeded its monthly spending cap", True),
        ("google", 429, PER_MINUTE_MESSAGE, False),
        ("google", 500, "spending cap", False),
        ("anthropic", 400, "Your credit balance is too low to access the Anthropic API", True),
        ("openai", 429, '{"error": {"code": "insufficient_quota"}}', True),
        ("openai", 429, '{"error": {"code": "rate_limit_exceeded"}}', False),
        ("openai_compatible", 429, "spending cap insufficient_quota", False),  # sem marcadores por padrão
        ("ollama", 429, "spending cap", False),
    ],
)
def test_classificacao_por_provedor(provider, status, message, expected):
    assert is_quota_exhausted(provider, status, message) is expected


def test_marcadores_configuraveis():
    """Scenario: Marcadores configuráveis (``LLM_QUOTA_MARKERS_GOOGLE="monthly budget,spending cap"``)."""
    with env_override({"LLM_QUOTA_MARKERS_GOOGLE": "monthly budget,spending cap"}) as load:
        module = load()
        assert module.QUOTA_MARKERS["google"] == ("monthly budget", "spending cap")
        assert is_quota_exhausted("google", 429, "your Monthly Budget is over")


@pytest.mark.parametrize("value", ["429", "limit", "x,  ,429"])
def test_marcador_curto_ou_numerico_e_recusado_na_inicializacao(value):
    from src.utils.configuration_error import ConfigurationError

    with env_override({"LLM_QUOTA_MARKERS_ANTHROPIC": value}) as load:
        with pytest.raises(ConfigurationError, match="LLM_QUOTA_MARKERS_ANTHROPIC"):
            load()


def test_lista_vazia_de_marcadores_e_aceita():
    with env_override({"LLM_QUOTA_MARKERS_OPENAI": ""}) as load:
        assert load().QUOTA_MARKERS["openai"] == ()


def test_is_retryable_error_recusa_cota_esgotada():
    exc = ProviderQuotaExhausted("google", "m", 429, SPENDING_CAP_MESSAGE)
    assert "429" in str(exc) and is_retryable_error(exc) is False
    assert is_retryable_error(ScriptedError(429, PER_MINUTE_MESSAGE)) is True


def test_detalhe_truncado_sem_segredos():
    exc = ProviderQuotaExhausted("openai", "m", 429, "sk-" + "a" * 40 + " AIza" + "b" * 30 + "\n" + "x" * 500)
    assert len(exc.detail) <= 300
    assert "sk-aaaa" not in exc.detail and "AIzabbbb" not in exc.detail and "\n" not in exc.detail


# --- provedores ----------------------------------------------------------------------------------------------------


def _google(fallback="gemini-reserva"):
    with patch("src.llm.providers.google.genai.Client") as client_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock()
        client_cls.return_value = client
        return GoogleProvider(api_key="chave", model="gemini-4-argon", fallback_model=fallback)


@pytest.mark.asyncio
async def test_teto_de_gasto_do_google():
    """Scenario: Teto de gasto do Google (uma chamada, nunca o modelo de reserva)."""
    provider = _google()
    provider._client.aio.models.generate_content.side_effect = ScriptedError(429, SPENDING_CAP_MESSAGE)
    with pytest.raises(ProviderQuotaExhausted) as caught:
        await provider.generate([{"role": "user", "content": "oi"}])
    assert caught.value.provider == "google" and caught.value.status_code == 429
    assert provider._client.aio.models.generate_content.await_count == 1
    assert quota_stop_for("sessao-teste") is caught.value


@pytest.mark.asyncio
async def test_limite_por_minuto_do_google_continua_transitorio():
    """Scenario: Limite por minuto do Google continua transitório."""
    provider = _google()
    ok = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(
            thought=False, function_call=None, text="ok", thought_signature=None)]), finish_reason="STOP")],
        usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0,
                                       total_token_count=2),
    )
    provider._client.aio.models.generate_content.side_effect = [ScriptedError(429, PER_MINUTE_MESSAGE), ok]
    response = await provider.generate([{"role": "user", "content": "oi"}])
    assert response.text == "ok"
    assert quota_stop_for("sessao-teste") is None


def _anthropic_error(status: int, message: str):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    cls = anthropic.BadRequestError if status == 400 else anthropic.RateLimitError
    return cls(message, response=httpx2.Response(status, request=request), body=None)


@pytest.mark.asyncio
async def test_saldo_esgotado_na_anthropic():
    """Scenario: Saldo esgotado na Anthropic (uma chamada e nenhum ``connection_retry``)."""
    provider = AnthropicProvider(api_key="sk-ant-teste", model="claude-sonnet-5-5")
    provider._client = MagicMock()
    provider._client.messages.create = AsyncMock(
        side_effect=_anthropic_error(400, "Your credit balance is too low to access the Anthropic API")
    )
    with pytest.raises(ProviderQuotaExhausted) as caught:
        await provider.generate([{"role": "user", "content": "oi"}])
    assert (caught.value.provider, caught.value.model, caught.value.status_code) == (
        "anthropic", "claude-sonnet-5-5", 400,
    )
    assert provider._client.messages.create.await_count == 1
    from src.llm.providers import anthropic as module

    module.emit_connection_retry.assert_not_called()


@pytest.mark.asyncio
async def test_429_da_anthropic_sem_marcador_continua_retentado():
    provider = AnthropicProvider(api_key="sk-ant-teste", model="claude-sonnet-5-5")
    provider._client = MagicMock()
    ok = SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn",
                         usage=SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0,
                                               cache_creation_input_tokens=0), stop_details=None)
    provider._client.messages.create = AsyncMock(side_effect=[_anthropic_error(429, "rate limit"), ok])
    assert (await provider.generate([{"role": "user", "content": "oi"}])).text == "ok"


BASE = "https://api.openai.com/v1"
OK_PAYLOAD = {
    "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


@pytest.mark.asyncio
async def test_cota_da_openai_no_corpo_do_429():
    """Scenario: Cota da OpenAI lida no corpo do 429 (sem retentativa)."""
    provider = OpenAIProvider(api_key="sk-test", model="gpt-6-luna")
    async with respx.mock:
        route = respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": {"code": "insufficient_quota"}})
        )
        with pytest.raises(ProviderQuotaExhausted) as caught:
            await provider.generate(messages=[{"role": "user", "content": "oi"}])
    assert caught.value.provider == "openai" and route.call_count == 1


@pytest.mark.asyncio
async def test_limite_de_taxa_da_openai_continua_transitorio():
    """Scenario: Limite de taxa da OpenAI continua transitório."""
    provider = OpenAIProvider(api_key="sk-test", model="gpt-6-luna")
    async with respx.mock:
        route = respx.post(f"{BASE}/chat/completions").mock(side_effect=[
            httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}}),
            httpx.Response(200, json=OK_PAYLOAD),
        ])
        response = await provider.generate(messages=[{"role": "user", "content": "oi"}])
    assert response.text == "ok" and route.call_count == 2


@pytest.mark.asyncio
async def test_openai_compatible_sem_marcadores_nao_classifica():
    provider = OpenAICompatibleProvider(base_url="http://srv:8000/v1", model="llama")
    async with respx.mock:
        route = respx.post("http://srv:8000/v1/chat/completions").mock(side_effect=[
            httpx.Response(429, json={"error": "insufficient_quota"}), httpx.Response(200, json=OK_PAYLOAD),
        ])
        assert (await provider.generate(messages=[{"role": "user", "content": "oi"}])).text == "ok"
    assert route.call_count == 2


# --- registro da sessão ----------------------------------------------------------------------------------------------


def test_evento_unico(_clean):
    """Scenario: Evento único (três chamadas simultâneas, um evento)."""
    for _ in range(3):
        quota.record_quota_exhausted(ProviderQuotaExhausted("google", "m", 429, SPENDING_CAP_MESSAGE))
    events = [c for c in _clean.record_agent_event.call_args_list if c.kwargs["event_type"] == "cota_provedor_esgotada"]
    assert len(events) == 1
    payload = events[0].kwargs["payload"]
    assert (payload["provedor"], payload["modelo"], payload["status"]) == ("google", "m", 429)
    assert events[0].kwargs["agent_id"] == "llm_provider:google" and len(payload["detalhe"]) <= 300


def test_registro_usa_o_contexto_do_agente(_clean, tmp_path):
    token = bind_agent_context(AgentContext(
        session_id="mestra-9", agent_session_id="a1", agent_id="developer", mode="auto", output_dir=tmp_path,
        model="m", execution_id="mestra-9",
    ))
    try:
        quota.record_quota_exhausted(ProviderQuotaExhausted("google", "m", 429, "x"))
    finally:
        from src.utils.agent_context import current_context

        current_context.reset(token)
    assert quota_stop_for("mestra-9") is not None and quota_stop_for("sessao-teste") is None
    assert _clean.record_agent_event.call_args.kwargs["payload"]["papel"] == "developer"


def test_nova_sessao_nao_herda_a_parada():
    """Scenario: Nova sessão não herda a parada."""
    quota.record_quota_exhausted(ProviderQuotaExhausted("google", "m", 429, "x"))
    quota.clear_quota_stop("sessao-teste")
    assert quota_stop_for("sessao-teste") is None and quota_stop_for("outra") is None


def test_falha_do_evento_nao_interrompe_o_registro(monkeypatch):
    def boom():
        raise RuntimeError("banco indisponível")

    monkeypatch.setattr("src.observability.telemetry.get_telemetry", boom)
    assert quota.record_quota_exhausted(ProviderQuotaExhausted("google", "m", 429, "x")) is True
    assert quota_stop_for("sessao-teste") is not None


# --- retentativas de conexão atribuídas à sessão ---------------------------------------------------------------------


def test_connection_retry_em_agente_em_processo(_clean, tmp_path, monkeypatch):
    """Scenario: Agente em processo (``execution_id`` do ``AgentContext``, sem variável de ambiente)."""
    monkeypatch.delenv("EXECUTION_ID", raising=False)
    monkeypatch.delenv("SESSION_ID", raising=False)
    token = bind_agent_context(AgentContext(
        session_id="sessao-mestra-1", agent_session_id="a1", agent_id="developer", mode="auto", output_dir=tmp_path,
        model="m", execution_id="sessao-mestra-1", task_name="treino",
    ))
    try:
        emit_connection_retry("llm_provider:google", "503")
    finally:
        from src.utils.agent_context import current_context

        current_context.reset(token)
    kwargs = _clean.record_connection_retry.call_args.kwargs
    assert kwargs["execution_id"] == "sessao-mestra-1" and kwargs["agent_id"] == "developer"
    assert kwargs["task_name"] == "treino"


def test_connection_retry_no_planejamento_fora_do_agent_context(_clean, monkeypatch):
    """Scenario: Planejamento fora do AgentContext (``bound_execution_id``)."""
    monkeypatch.delenv("EXECUTION_ID", raising=False)
    bind_execution("sessao-mestra-2", "sessao-mestra-2")
    emit_connection_retry("llm_provider:google", "503")
    assert _clean.record_connection_retry.call_args.kwargs["execution_id"] == "sessao-mestra-2"


def test_connection_retry_sem_nenhuma_fonte_vai_para_unknown(_clean, monkeypatch):
    monkeypatch.delenv("EXECUTION_ID", raising=False)
    monkeypatch.delenv("SESSION_ID", raising=False)
    bind_execution("", "")
    emit_connection_retry("llm_provider:google", "503")
    assert _clean.record_connection_retry.call_args.kwargs["execution_id"] == "unknown"


# --- limitador de taxa -----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teto_do_resfriamento():
    """Scenario: Teto do resfriamento (30, 60, 120, 240, 300, 300)."""
    limiter = AdaptiveRateLimiter(requests_per_minute=15, cooldown_seconds=30, max_cooldown_seconds=300)
    seen = []
    for _ in range(6):
        before = limiter.in_cooldown_until
        await limiter.report_429()
        seen.append(round(limiter.in_cooldown_until - __import__("time").monotonic()))
        assert before <= limiter.in_cooldown_until
    assert seen == [30, 60, 120, 240, 300, 300] and max(seen) <= 300


def test_limitador_usa_o_teto_da_configuracao():
    assert AdaptiveRateLimiter().max_cooldown_seconds == config.LLM_RATE_LIMIT_MAX_COOLDOWN_SECONDS == 300


@pytest.mark.asyncio
async def test_cota_nao_aciona_o_limitador(tmp_path):
    """Scenario: Cota não aciona o limitador (``error_category="cota_provedor"`` não chama ``report_429``)."""
    from src.agent_runtime.types import AgentResult, AgentTask
    from src.artifacts.output_manager import OutputManager
    from src.orchestration.orchestrator import Orchestrator
    from tests.support.session_fakes import FakeSessionManager

    result = AgentResult(
        agent_id="developer", session_id="s", status="error", response={}, error=SPENDING_CAP_MESSAGE,
        error_category="cota_provedor",
    )
    runtime = MagicMock()
    runtime.run = AsyncMock(return_value=result)
    orch = Orchestrator(
        session_manager=FakeSessionManager(), output_manager=OutputManager(str(tmp_path / "o"), str(tmp_path / "l")),
        agent_runtime=runtime,
    )
    orch.rate_limiter = MagicMock(acquire=AsyncMock(), report_429=AsyncMock(), report_success=AsyncMock())
    got = await orch._execute_agent(AgentTask(agent_id="developer", prompt="p"), "mestra")
    assert got.error_category == "cota_provedor"
    orch.rate_limiter.report_429.assert_not_called()

