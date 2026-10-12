"""Modo sem limite do orçamento (v18.5-operation-metrics, tarefas 1.1–1.3, 3.2; cenários 8.1, 8.2, 8.6)."""

from __future__ import annotations

import pytest

from src.usage import LimitStatus, StopReason, UsageBudget, UsageTracker

pytestmark = pytest.mark.unit


def _unlimited(**kw) -> UsageBudget:
    return UsageBudget.from_config(unlimited=True, **kw)


def _tracker(budget: UsageBudget, *, tokens=0, minutes=0.0, conn=0, egress=0) -> UsageTracker:
    now = [0.0]
    tracker = UsageTracker(
        budget,
        "sess",
        token_reader=lambda: tokens,
        connection_retry_reader=lambda: conn,
        egress_reader=lambda: egress,
        clock=lambda: now[0],
    )
    now[0] = minutes * 60.0
    return tracker


def test_orcamento_limitado_exige_limites_positivos() -> None:
    for kw in ({"max_tokens": None}, {"max_minutes": None}, {"max_egress_bytes": None}, {"max_tokens": 0}):
        base = dict(max_tokens=10, max_minutes=1, max_task_retries=1, max_connection_retries=1,
                    closing_reserve_pct=0.1, max_egress_bytes=5)
        base.update(kw)
        with pytest.raises(ValueError):
            UsageBudget(**base)


def test_sem_limite_exige_limites_nulos_e_retentativas_positivas() -> None:
    with pytest.raises(ValueError):
        UsageBudget(max_tokens=10, max_minutes=None, max_task_retries=1, max_connection_retries=1,
                    closing_reserve_pct=0.1, max_egress_bytes=None, unlimited=True)
    with pytest.raises(ValueError):
        UsageBudget(max_tokens=None, max_minutes=None, max_task_retries=0, max_connection_retries=1,
                    closing_reserve_pct=0.1, max_egress_bytes=None, unlimited=True)


@pytest.mark.parametrize("kw", [{"max_tokens": 10}, {"max_minutes": 5}, {"max_egress_bytes": 9}])
def test_from_config_recusa_override_com_unlimited(kw) -> None:
    with pytest.raises(ValueError, match="incompatíveis com --unlimited"):
        UsageBudget.from_config(unlimited=True, **kw)


def test_to_payload_sem_limite() -> None:
    payload = _unlimited().to_payload()
    assert payload["unlimited"] is True
    assert payload["max_tokens"] is None and payload["max_minutes"] is None
    assert payload["max_egress_bytes"] is None and payload["exploration_token_ceiling"] is None
    assert payload["max_task_retries"] > 0 and payload["max_connection_retries"] > 0


def test_sem_limite_tokens_tempo_e_egresso_nao_fecham() -> None:
    status = _tracker(_unlimited(), tokens=10**12, minutes=10**6, egress=10**12).check()
    assert not (status.tokens_exhausted or status.time_exhausted or status.egress_exhausted)
    assert status.tokens_pct is None and status.minutes_pct is None
    assert status.should_close is False


def test_sem_limite_conexao_continua_fechando() -> None:
    budget = _unlimited()
    status = _tracker(budget, tokens=10**9, conn=budget.max_connection_retries).check()
    assert status.stop_reason == StopReason.CONNECTION


def test_sem_limite_tokens_hard_exhausted_falso_e_retentativas_valem() -> None:
    tracker = _tracker(_unlimited(), tokens=10**12)
    assert tracker.tokens_hard_exhausted() is False
    for _ in range(tracker.budget.max_task_retries):
        tracker.record_task_attempt("t")
    assert tracker.task_retries_exhausted("t") is True


def test_modo_limitado_egresso_fecha_com_limite_egresso() -> None:
    budget = UsageBudget.from_config(max_egress_bytes=100)
    assert _tracker(budget, egress=99).check().should_close is False
    assert _tracker(budget, egress=100).check().stop_reason == StopReason.EGRESS


def test_prioridade_tokens_tempo_egresso_conexao() -> None:
    def status(**kw) -> LimitStatus:
        base = dict(tokens_used=0, tokens_pct=0.0, tokens_exhausted=False, minutes_elapsed=0.0, minutes_pct=0.0,
                    time_exhausted=False, connection_retries=0, connection_retries_pct=0.0,
                    connection_retries_exhausted=False)
        base.update(kw)
        return LimitStatus(**base)

    todos = dict(tokens_exhausted=True, time_exhausted=True, egress_exhausted=True, connection_retries_exhausted=True)
    assert status(**todos).stop_reason == StopReason.TOKENS
    todos.pop("tokens_exhausted")
    assert status(**todos).stop_reason == StopReason.TIME
    todos.pop("time_exhausted")
    assert status(**todos).stop_reason == StopReason.EGRESS
    todos.pop("egress_exhausted")
    assert status(**todos).stop_reason == StopReason.CONNECTION
