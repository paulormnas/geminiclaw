"""Limite de custo por sessão (v18.7-exploration-limits, seção 3; specs ``usage-limits`` e ``operation-metrics``)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cli.main import build_parser, build_usage_budget
from src.llm.pricing_check import require_priced_models, unpriced_models
from src.orchestration.autonomous_loop import AutonomousLoop
from src.orchestration.unlimited_mode import confirmation_prompt
from src.orchestration.usage import StopReason, UsageBudget, UsageTracker
from src.report.operation_metrics import CostResourcesReader, describe_stop_reason
from src.utils.configuration_error import ConfigurationError

pytestmark = pytest.mark.unit


def _budget(**kw) -> UsageBudget:
    base = dict(max_tokens=10_000_000, max_minutes=600, max_task_retries=3, max_connection_retries=5,
                closing_reserve_pct=0.05, max_cost_usd=2.0)
    return UsageBudget(**{**base, **kw})


def _tracker(budget: UsageBudget, costs: dict, **kw) -> UsageTracker:
    return UsageTracker(budget, "exec", token_reader=lambda: 0, connection_retry_reader=lambda: 0,
                        egress_reader=lambda: 0, cost_reader=lambda: costs, **kw)


# -- orçamento -------------------------------------------------------------------------------------------------


def test_orcamento_pela_cli_grava_o_custo_no_payload():
    args = build_parser().parse_args(["--max-tokens", "100000", "--max-minutes", "30", "--max-cost-usd", "3", "x"])
    budget = build_usage_budget(args)
    payload = budget.to_payload()
    assert budget.max_cost_usd == 3.0 and payload["max_cost_usd"] == 3.0
    assert payload["max_cost_usd_by_provider"] == {}


def test_custo_ausente_assume_o_padrao_de_config():
    from src import config

    assert _budget(max_cost_usd=None).max_cost_usd == config.SESSION_MAX_COST_USD


@pytest.mark.parametrize("value", [0, -1.0])
def test_custo_nao_positivo_falha(value):
    with pytest.raises(ValueError, match="max_cost_usd"):
        _budget(max_cost_usd=value)


def test_teto_por_provedor_nao_positivo_falha():
    with pytest.raises(ValueError, match="max_cost_usd_by_provider"):
        _budget(max_cost_usd_by_provider={"google": 0.0})


def test_opcoes_incompativeis_com_o_modo_sem_limite():
    with pytest.raises(ValueError, match="--max-cost-usd"):
        UsageBudget.from_config(unlimited=True, max_cost_usd=3.0)
    with pytest.raises(ValueError):
        UsageBudget(max_tokens=None, max_minutes=None, max_task_retries=3, max_connection_retries=5,
                    closing_reserve_pct=0.05, max_egress_bytes=None, unlimited=True, max_cost_usd=1.0)


def test_modo_sem_limite_nao_tem_custo():
    budget = UsageBudget.from_config(unlimited=True)
    assert budget.max_cost_usd is None and dict(budget.max_cost_usd_by_provider) == {}
    assert budget.to_payload()["max_cost_usd"] is None


# -- verificação de limites ---------------------------------------------------------------------------------------


def test_teto_total_atingido():
    """Scenario: Teto total atingido (1.91 ≥ 2.0 × 0.95)."""
    status = _tracker(_budget(), {"anthropic": 1.20, "openai": 0.71}).check()
    assert status.cost_exhausted and status.cost_exhausted_provider is None
    assert status.stop_reason == StopReason.COST and StopReason.COST.value == "limite_custo"
    assert round(status.cost_usd, 2) == 1.91 and status.should_close


def test_abaixo_do_teto_nao_fecha():
    status = _tracker(_budget(), {"anthropic": 1.0}).check()
    assert not status.cost_exhausted and status.stop_reason is None and status.cost_pct == 0.5


def test_teto_por_provedor():
    """Scenario: Teto por provedor."""
    budget = _budget(max_cost_usd=10.0, max_cost_usd_by_provider={"google": 1.0})
    status = _tracker(budget, {"google": 1.0, "anthropic": 0.2}).check()
    assert status.stop_reason == StopReason.COST and status.cost_exhausted_provider == "google"


def test_custo_none_de_um_provedor_conta_como_zero():
    status = _tracker(_budget(), {"ollama": None, "google": 0.5}).check()
    assert status.cost_usd == 0.5 and not status.cost_exhausted


def test_precedencia_sobre_a_cota_do_provedor():
    """Scenario: Precedência sobre a cota do provedor."""
    tracker = _tracker(_budget(), {"google": 1.95}, pending_stop=lambda: StopReason.PROVIDER_QUOTA)
    assert tracker.check().stop_reason == StopReason.COST
    tracker = _tracker(_budget(), {"google": 0.1}, pending_stop=lambda: StopReason.PROVIDER_QUOTA)
    assert tracker.check().stop_reason == StopReason.PROVIDER_QUOTA


def test_tokens_e_tempo_vem_antes_do_custo():
    tracker = UsageTracker(_budget(max_tokens=1000), "e", token_reader=lambda: 5000, connection_retry_reader=lambda: 0,
                           egress_reader=lambda: 0, cost_reader=lambda: {"g": 99.0})
    assert tracker.check().stop_reason == StopReason.TOKENS


def test_modo_sem_limite_ignora_o_custo():
    """Scenario: Tokens, tempo e custo não param."""
    budget = UsageBudget.from_config(unlimited=True)
    status = _tracker(budget, {"google": 1e6}).check()
    assert not status.cost_exhausted and status.cost_pct is None and status.stop_reason is None


def test_leitor_padrao_agrupa_o_custo_por_provedor():
    rows = [
        {"llm_provider": "google", "total_cost_usd": 0.5}, {"llm_provider": "google", "total_cost_usd": 0.25},
        {"llm_provider": "ollama", "total_cost_usd": None},
    ]
    with patch("src.observability.telemetry.get_telemetry") as tel:
        tel.return_value.get_token_summary.return_value = {"by_provider_model": rows}
        from src.orchestration.usage import _default_cost_reader

        assert _default_cost_reader("e") == {"google": 0.75, "ollama": None}


# -- preço dos modelos alcançáveis ---------------------------------------------------------------------------------


def _routing(roles: dict[str, str], locality: dict[str, str] | None = None, fallback: dict[str, str] | None = None):
    models = {m: SimpleNamespace(localidade=(locality or {}).get(m, "fora_do_no")) for m in
              set(roles.values()) | {f"{m.split('/')[0]}/{f}" for m, f in (fallback or {}).items()}}
    return SimpleNamespace(
        papeis={role: SimpleNamespace(id=model) for role, model in roles.items()},
        catalogo=SimpleNamespace(modelos=models),
        fallback_for=lambda model: (fallback or {}).get(model),
    )


def test_alocacao_com_modelo_sem_preco_impede_o_inicio():
    routing = _routing({"researcher": "google/gemini-4-argon", "developer": "openai/modelo-sem-preco"})
    with pytest.raises(ConfigurationError) as err:
        require_priced_models(routing, unlimited=False)
    assert "openai/modelo-sem-preco" in str(err.value) and "LLM_PRICING_OVERRIDES" in str(err.value)


def test_modelo_de_reserva_sem_preco_impede_o_inicio():
    routing = _routing({"researcher": "google/gemini-4-argon"}, fallback={"google/gemini-4-argon": "gemini-sem-preco"})
    with pytest.raises(ConfigurationError) as err:
        require_priced_models(routing, unlimited=False)
    assert "google/gemini-sem-preco" in str(err.value) and "LLM_PRICING_OVERRIDES" in str(err.value)


def test_modelo_local_sem_preco_inicia():
    routing = _routing({"researcher": "ollama/qwen", "developer": "ollama/outro"},
                       locality={"ollama/qwen": "no_no", "ollama/outro": "no_no"})
    assert unpriced_models(routing) == []
    require_priced_models(routing, unlimited=False)


def test_modo_sem_limite_dispensa_a_verificacao():
    require_priced_models(_routing({"researcher": "openai/modelo-sem-preco"}), unlimited=True)


def test_override_de_preco_libera_o_modelo(monkeypatch):
    monkeypatch.setenv("LLM_PRICING_OVERRIDES", '{"openai/modelo-sem-preco": [1.0, 2.0, 0.1]}')
    assert unpriced_models(_routing({"developer": "openai/modelo-sem-preco"})) == []


def test_chamada_sem_preco_emite_custo_nao_estimado_uma_vez_por_modelo():
    from src.llm import metering

    metering._unpriced_noted.clear()
    with patch("src.llm.metering.get_telemetry") as tel, patch("src.llm.session.current_session_routing",
                                                                 return_value=None):
        for _ in range(3):
            metering.note_unpriced_model("exec-1", "s", "openai", "modelo-x")
        metering.note_unpriced_model("exec-1", "s", "openai", "modelo-y")
    events = [c.kwargs["payload"]["modelo"] for c in tel.return_value.record_agent_event.call_args_list]
    assert events == ["openai/modelo-x", "openai/modelo-y"]
    metering._unpriced_noted.clear()


def test_chamada_de_modelo_local_nao_emite_o_evento():
    from src.llm import metering

    metering._unpriced_noted.clear()
    routing = _routing({"developer": "ollama/qwen"}, locality={"ollama/qwen": "no_no"})
    with patch("src.llm.metering.get_telemetry") as tel, patch("src.llm.session.current_session_routing",
                                                                 return_value=routing):
        metering.note_unpriced_model("exec-2", "s", "ollama", "qwen")
    tel.return_value.record_agent_event.assert_not_called()


# -- confirmação do modo sem limite -----------------------------------------------------------------------------


def test_texto_da_confirmacao_do_modo_sem_limite():
    """Scenario: Texto da confirmação."""
    text = confirmation_prompt(UsageBudget.from_config(unlimited=True), interval_minutes=10, token_step=100_000)
    assert "custo" in text and "não há parada automática garantida" in text
    assert "indefinidamente" in text and "wait_for_health" in text and "SANDBOX_MIN_FREE_BYTES" in text


# -- aviso G5 --------------------------------------------------------------------------------------------------


def _loop(budget: UsageBudget):
    orchestrator = MagicMock()
    orchestrator.output_manager = MagicMock()
    loop = AutonomousLoop(orchestrator)
    loop._usage_tracker = SimpleNamespace(budget=budget)
    loop._maybe_unlimited_notice = AsyncMock()
    return loop


@pytest.mark.asyncio
async def test_aviso_de_custo_por_percentual():
    """Scenario: Aviso de custo por percentual (80% de US$ 5 = US$ 4)."""
    rows = {"by_provider_model": [{"total_tokens": 10, "total_cost_usd": 4.0}]}
    loop = _loop(UsageBudget.from_config(max_cost_usd=5.0))
    with patch("src.orchestration.autonomous_loop.get_telemetry") as tel, \
            patch("src.orchestration.autonomous_loop.logger") as log:
        tel.return_value.get_token_summary.return_value = rows
        await loop._check_operational_thresholds("s")
    triggered = log.warning.call_args.kwargs["extra"]["triggered"]
    assert any("Custo estimado: 80%" in item for item in triggered)


@pytest.mark.asyncio
async def test_sem_aviso_de_custo_abaixo_do_percentual_e_no_modo_sem_limite():
    rows = {"by_provider_model": [{"total_tokens": 10, "total_cost_usd": 3.0}]}
    for budget in (UsageBudget.from_config(max_cost_usd=5.0), UsageBudget.from_config(unlimited=True)):
        loop = _loop(budget)
        with patch("src.orchestration.autonomous_loop.get_telemetry") as tel, \
                patch("src.orchestration.autonomous_loop.logger") as log:
            tel.return_value.get_token_summary.return_value = rows
            await loop._check_operational_thresholds("s")
        assert not log.warning.called


# -- métricas de operação ------------------------------------------------------------------------------------------


def test_custo_por_provedor_nas_metricas():
    """Scenario: Custo por provedor."""
    rows = {"by_provider_model": [
        {"llm_provider": "anthropic", "total_cost_usd": 1.2}, {"llm_provider": "google", "total_cost_usd": 0.4},
        {"llm_provider": "ollama", "total_cost_usd": None},
    ]}
    budget = {"max_cost_usd": 10, "max_cost_usd_by_provider": {"google": 2.0}}
    with patch("src.observability.telemetry.get_telemetry") as tel:
        tel.return_value.get_token_summary.return_value = rows
        tel.return_value.get_usage_by_task.return_value = []
        tel.return_value.get_hardware_peaks.return_value = {}
        tel.return_value.get_average_cpu.return_value = None
        out = CostResourcesReader(budget_loader=lambda sid: budget).read("s")
    assert out["custo_por_provedor"] == {"anthropic": 1.2, "google": 0.4, "ollama": None}
    assert out["custo_limite_usd"] == 10 and out["custo_limite_por_provedor"] == {"google": 2.0}


def test_descricao_dos_motivos_de_parada():
    """Scenario: Descrição dos motivos."""
    texts = {describe_stop_reason(r) for r in ("limite_custo", "saturacao", "limite_cota_provedor")}
    assert len(texts) == 3 and all(t and "(" in t for t in texts)
