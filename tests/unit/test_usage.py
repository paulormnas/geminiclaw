"""Testes unitários para Roadmap V18 / Spec `usage-limits` (src/usage.py).

Cobre:
  - UsageBudget: validação, `exploration_token_ceiling`, `to_payload`, `from_config`
    (defaults de `src/config.py` e overrides explícitos, ex: opções da CLI).
  - UsageTracker: contabilização de tokens/tempo/retentativas de conexão via
    leitores injetáveis (sem tocar telemetria/banco real), retentativas por
    tarefa (cumulativas), abandono de tarefa, e a prioridade de `StopReason`
    (tokens > tempo > conexão) descrita em design.md §2-3.
"""

from unittest.mock import patch

import pytest

from src.usage import LimitStatus, StopReason, UsageBudget, UsageTracker

# ---------------------------------------------------------------------------
# UsageBudget
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUsageBudgetValidation:
    def test_valores_validos_nao_levantam(self):
        budget = UsageBudget(
            max_tokens=1000, max_minutes=10, max_task_retries=3,
            max_connection_retries=5, closing_reserve_pct=0.1,
        )
        assert budget.max_tokens == 1000

    @pytest.mark.parametrize(
        "field,value",
        [
            ("max_tokens", 0),
            ("max_tokens", -1),
            ("max_minutes", 0),
            ("max_minutes", -1),
            ("max_task_retries", 0),
            ("max_connection_retries", 0),
        ],
    )
    def test_valores_nao_positivos_levantam_value_error(self, field, value):
        kwargs = dict(
            max_tokens=1000, max_minutes=10, max_task_retries=3,
            max_connection_retries=5, closing_reserve_pct=0.1,
        )
        kwargs[field] = value
        with pytest.raises(ValueError):
            UsageBudget(**kwargs)

    @pytest.mark.parametrize("pct", [-0.1, 1.0, 1.5])
    def test_closing_reserve_pct_fora_do_intervalo_levanta(self, pct):
        with pytest.raises(ValueError):
            UsageBudget(
                max_tokens=1000, max_minutes=10, max_task_retries=3,
                max_connection_retries=5, closing_reserve_pct=pct,
            )

    def test_closing_reserve_pct_zero_e_valido(self):
        budget = UsageBudget(
            max_tokens=1000, max_minutes=10, max_task_retries=3,
            max_connection_retries=5, closing_reserve_pct=0.0,
        )
        assert budget.closing_reserve_pct == 0.0


@pytest.mark.unit
class TestUsageBudgetDerived:
    def test_exploration_token_ceiling_desconta_reserva(self):
        budget = UsageBudget(
            max_tokens=100_000, max_minutes=10, max_task_retries=3,
            max_connection_retries=5, closing_reserve_pct=0.05,
        )
        assert budget.exploration_token_ceiling == 95_000

    def test_exploration_token_ceiling_sem_reserva_igual_a_max_tokens(self):
        budget = UsageBudget(
            max_tokens=100_000, max_minutes=10, max_task_retries=3,
            max_connection_retries=5, closing_reserve_pct=0.0,
        )
        assert budget.exploration_token_ceiling == 100_000

    def test_to_payload_inclui_todos_os_campos(self):
        budget = UsageBudget(
            max_tokens=100_000, max_minutes=10.5, max_task_retries=3,
            max_connection_retries=5, closing_reserve_pct=0.05,
        )
        payload = budget.to_payload()
        assert payload == {
            "max_tokens": 100_000,
            "max_minutes": 10.5,
            "max_task_retries": 3,
            "max_connection_retries": 5,
            "closing_reserve_pct": 0.05,
            "exploration_token_ceiling": 95_000,
        }

    def test_budget_e_imutavel(self):
        budget = UsageBudget(
            max_tokens=1000, max_minutes=10, max_task_retries=3,
            max_connection_retries=5, closing_reserve_pct=0.1,
        )
        with pytest.raises(Exception):
            budget.max_tokens = 2000


@pytest.mark.unit
class TestUsageBudgetFromConfig:
    def test_usa_defaults_de_config_quando_sem_overrides(self):
        with patch("src.config.SESSION_MAX_TOKENS", 111), \
             patch("src.config.SESSION_MAX_MINUTES", 22.0), \
             patch("src.config.SESSION_MAX_TASK_RETRIES", 3), \
             patch("src.config.SESSION_MAX_CONNECTION_RETRIES", 4), \
             patch("src.config.SESSION_CLOSING_RESERVE_PCT", 0.05):
            budget = UsageBudget.from_config()
        assert budget.max_tokens == 111
        assert budget.max_minutes == 22.0
        assert budget.max_task_retries == 3
        assert budget.max_connection_retries == 4
        assert budget.closing_reserve_pct == 0.05

    def test_overrides_explicitos_sobrescrevem_config(self):
        with patch("src.config.SESSION_MAX_TOKENS", 111), \
             patch("src.config.SESSION_MAX_MINUTES", 22.0), \
             patch("src.config.SESSION_MAX_TASK_RETRIES", 3), \
             patch("src.config.SESSION_MAX_CONNECTION_RETRIES", 4), \
             patch("src.config.SESSION_CLOSING_RESERVE_PCT", 0.05):
            budget = UsageBudget.from_config(
                max_tokens=999,
                max_minutes=5.0,
                max_task_retries=1,
                max_connection_retries=2,
                closing_reserve_pct=0.2,
            )
        assert budget.max_tokens == 999
        assert budget.max_minutes == 5.0
        assert budget.max_task_retries == 1
        assert budget.max_connection_retries == 2
        assert budget.closing_reserve_pct == 0.2

    def test_override_parcial_mistura_config_e_explicito(self):
        with patch("src.config.SESSION_MAX_TOKENS", 111), \
             patch("src.config.SESSION_MAX_MINUTES", 22.0), \
             patch("src.config.SESSION_MAX_TASK_RETRIES", 3), \
             patch("src.config.SESSION_MAX_CONNECTION_RETRIES", 4), \
             patch("src.config.SESSION_CLOSING_RESERVE_PCT", 0.05):
            budget = UsageBudget.from_config(max_task_retries=7)
        assert budget.max_tokens == 111  # veio do config
        assert budget.max_task_retries == 7  # override explícito


# ---------------------------------------------------------------------------
# UsageTracker — tokens, tempo, conexão (leitores/clock injetáveis)
# ---------------------------------------------------------------------------


def _budget(**overrides) -> UsageBudget:
    defaults = dict(
        max_tokens=1000,
        max_minutes=10.0,
        max_task_retries=3,
        max_connection_retries=5,
        closing_reserve_pct=0.1,
    )
    defaults.update(overrides)
    return UsageBudget(**defaults)


@pytest.mark.unit
class TestUsageTrackerCheck:
    def test_nenhum_limite_atingido_no_inicio(self):
        tracker = UsageTracker(
            _budget(),
            execution_id="exec1",
            token_reader=lambda: 0,
            connection_retry_reader=lambda: 0,
            clock=lambda: 0.0,
        )
        status = tracker.check()
        assert not status.should_close
        assert status.stop_reason is None
        assert status.tokens_used == 0
        assert status.minutes_elapsed == 0.0

    def test_tokens_exhausted_respeita_reserva_de_fechamento(self):
        # max_tokens=1000, reserva=10% -> teto de exploração = 900
        budget = _budget(max_tokens=1000, closing_reserve_pct=0.1)
        tracker = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 899,
            connection_retry_reader=lambda: 0,
            clock=lambda: 0.0,
        )
        assert not tracker.check().tokens_exhausted

        tracker_no_budget = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 900,
            connection_retry_reader=lambda: 0,
            clock=lambda: 0.0,
        )
        status = tracker_no_budget.check()
        assert status.tokens_exhausted
        assert status.should_close
        assert status.stop_reason == StopReason.TOKENS

    def test_tokens_hard_exhausted_ignora_reserva(self):
        budget = _budget(max_tokens=1000, closing_reserve_pct=0.1)
        # 950 já esgotou o teto de exploração (900) mas não o total (1000)
        tracker = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 950,
            connection_retry_reader=lambda: 0,
            clock=lambda: 0.0,
        )
        assert tracker.check().tokens_exhausted
        assert not tracker.tokens_hard_exhausted()

        tracker_hard = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 1000,
            connection_retry_reader=lambda: 0,
            clock=lambda: 0.0,
        )
        assert tracker_hard.tokens_hard_exhausted()

    def test_time_exhausted_quando_elapsed_atinge_max_minutes(self):
        budget = _budget(max_minutes=10.0)
        # clock: primeira chamada (construção) = 0, chamadas subsequentes = 600s (10min)
        clock_calls = iter([0.0, 600.0])
        tracker = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 0,
            connection_retry_reader=lambda: 0,
            clock=lambda: next(clock_calls),
        )
        status = tracker.check()
        assert status.time_exhausted
        assert status.should_close
        assert status.stop_reason == StopReason.TIME

    def test_time_nao_exhausted_antes_do_limite(self):
        budget = _budget(max_minutes=10.0)
        clock_calls = iter([0.0, 599.0])
        tracker = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 0,
            connection_retry_reader=lambda: 0,
            clock=lambda: next(clock_calls),
        )
        assert not tracker.check().time_exhausted

    def test_connection_retries_exhausted(self):
        budget = _budget(max_connection_retries=5)
        tracker = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 0,
            connection_retry_reader=lambda: 5,
            clock=lambda: 0.0,
        )
        status = tracker.check()
        assert status.connection_retries_exhausted
        assert status.should_close
        assert status.stop_reason == StopReason.CONNECTION

    def test_connection_retries_abaixo_do_limite_nao_fecha(self):
        budget = _budget(max_connection_retries=5)
        tracker = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 0,
            connection_retry_reader=lambda: 4,
            clock=lambda: 0.0,
        )
        assert not tracker.check().should_close

    def test_prioridade_tokens_sobre_tempo_e_conexao(self):
        """design.md §2-3: quando múltiplos limites são atingidos simultaneamente,
        a prioridade de `stop_reason` é tokens > tempo > conexão."""
        budget = _budget(max_tokens=1000, max_minutes=10.0, max_connection_retries=5, closing_reserve_pct=0.0)
        clock_calls = iter([0.0, 600.0])
        tracker = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 1000,
            connection_retry_reader=lambda: 5,
            clock=lambda: next(clock_calls),
        )
        status = tracker.check()
        assert status.tokens_exhausted and status.time_exhausted and status.connection_retries_exhausted
        assert status.stop_reason == StopReason.TOKENS

    def test_prioridade_tempo_sobre_conexao_quando_tokens_ok(self):
        budget = _budget(max_tokens=1000, max_minutes=10.0, max_connection_retries=5, closing_reserve_pct=0.0)
        clock_calls = iter([0.0, 600.0])
        tracker = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 0,
            connection_retry_reader=lambda: 5,
            clock=lambda: next(clock_calls),
        )
        status = tracker.check()
        assert status.stop_reason == StopReason.TIME

    def test_pct_calculados_corretamente(self):
        budget = _budget(max_tokens=1000, max_minutes=10.0, max_connection_retries=4, closing_reserve_pct=0.0)
        clock_calls = iter([0.0, 300.0])  # 5min de 10min = 50%
        tracker = UsageTracker(
            budget, execution_id="exec1",
            token_reader=lambda: 250,  # 25% de 1000
            connection_retry_reader=lambda: 1,  # 25% de 4
            clock=lambda: next(clock_calls),
        )
        status = tracker.check()
        assert status.tokens_pct == pytest.approx(0.25)
        assert status.minutes_pct == pytest.approx(0.5)
        assert status.connection_retries_pct == pytest.approx(0.25)


@pytest.mark.unit
class TestUsageTrackerElapsedMinutes:
    def test_elapsed_minutes_usa_clock_injetado(self):
        clock_calls = iter([100.0, 100.0 + 120.0])  # construção, depois +2min
        tracker = UsageTracker(
            _budget(), execution_id="exec1", clock=lambda: next(clock_calls),
        )
        assert tracker.elapsed_minutes() == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# UsageTracker — retentativas por tarefa (design §2-3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUsageTrackerTaskRetries:
    def test_record_task_attempt_incrementa_cumulativamente(self):
        tracker = UsageTracker(_budget(max_task_retries=3), execution_id="exec1", clock=lambda: 0.0)
        assert tracker.record_task_attempt("t1") == 1
        assert tracker.record_task_attempt("t1") == 2
        assert tracker.task_attempts("t1") == 2
        # Uma tarefa diferente tem contagem independente.
        assert tracker.record_task_attempt("t2") == 1

    def test_task_retries_exhausted_no_limite_exato(self):
        tracker = UsageTracker(_budget(max_task_retries=2), execution_id="exec1", clock=lambda: 0.0)
        tracker.record_task_attempt("t1")
        assert not tracker.task_retries_exhausted("t1")
        tracker.record_task_attempt("t1")
        assert tracker.task_retries_exhausted("t1")

    def test_task_retries_exhausted_para_tarefa_nunca_tentada_e_false(self):
        tracker = UsageTracker(_budget(max_task_retries=2), execution_id="exec1", clock=lambda: 0.0)
        assert not tracker.task_retries_exhausted("nunca_tentada")

    def test_contagem_cumulativa_entre_ciclos_de_replanejamento(self):
        """design.md §2: retentativas contam cumulativamente mesmo quando a
        tarefa reaparece em um novo ciclo de replanejamento (mesmo task_name)."""
        tracker = UsageTracker(_budget(max_task_retries=2), execution_id="exec1", clock=lambda: 0.0)
        # Ciclo de plano 1: 1a tentativa falha.
        tracker.record_task_attempt("t1")
        assert not tracker.task_retries_exhausted("t1")
        # Ciclo de plano 2 (replanejamento incremental, mesmo task_name): 2a tentativa.
        tracker.record_task_attempt("t1")
        assert tracker.task_retries_exhausted("t1")

    def test_mark_task_abandoned_e_is_task_abandoned(self):
        tracker = UsageTracker(_budget(), execution_id="exec1", clock=lambda: 0.0)
        assert not tracker.is_task_abandoned("t1")
        tracker.mark_task_abandoned("t1")
        assert tracker.is_task_abandoned("t1")
        assert "t1" in tracker.abandoned_tasks

    def test_abandoned_tasks_e_imutavel(self):
        tracker = UsageTracker(_budget(), execution_id="exec1", clock=lambda: 0.0)
        tracker.mark_task_abandoned("t1")
        frozen = tracker.abandoned_tasks
        assert isinstance(frozen, frozenset)

    def test_all_pending_abandoned_vazio_e_false(self):
        tracker = UsageTracker(_budget(), execution_id="exec1", clock=lambda: 0.0)
        assert not tracker.all_pending_abandoned([])

    def test_all_pending_abandoned_true_quando_todas_abandonadas(self):
        tracker = UsageTracker(_budget(), execution_id="exec1", clock=lambda: 0.0)
        tracker.mark_task_abandoned("t1")
        tracker.mark_task_abandoned("t2")
        assert tracker.all_pending_abandoned(["t1", "t2"])

    def test_all_pending_abandoned_false_quando_parcial(self):
        tracker = UsageTracker(_budget(), execution_id="exec1", clock=lambda: 0.0)
        tracker.mark_task_abandoned("t1")
        assert not tracker.all_pending_abandoned(["t1", "t2"])


# ---------------------------------------------------------------------------
# LimitStatus
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLimitStatus:
    def test_should_close_false_quando_nada_esgotado(self):
        status = LimitStatus(
            tokens_used=0, tokens_pct=0.0, tokens_exhausted=False,
            minutes_elapsed=0.0, minutes_pct=0.0, time_exhausted=False,
            connection_retries=0, connection_retries_pct=0.0, connection_retries_exhausted=False,
        )
        assert not status.should_close
        assert status.stop_reason is None

    def test_stop_reason_prioriza_tokens(self):
        status = LimitStatus(
            tokens_used=1, tokens_pct=1.0, tokens_exhausted=True,
            minutes_elapsed=1, minutes_pct=1.0, time_exhausted=True,
            connection_retries=1, connection_retries_pct=1.0, connection_retries_exhausted=True,
        )
        assert status.stop_reason == StopReason.TOKENS


# ---------------------------------------------------------------------------
# Leitores default (telemetria) — design.md §1: max_tokens conta TODOS os
# agentes da sessão, inclusive um futuro agente Curator (tasks.md 5.5): a
# soma não filtra por agent_id/role, apenas por execution_id.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDefaultReaders:
    def test_default_token_reader_soma_todos_os_agentes_e_provedores(self):
        from src.usage import _default_token_reader

        fake_summary = {
            "by_provider_model": [
                {"llm_provider": "google", "llm_model": "gemini-3-flash", "total_tokens": 100},
                {"llm_provider": "ollama", "llm_model": "qwen3:8b", "total_tokens": 250},
                # Um futuro agente Curator usaria o mesmo execution_id e o mesmo
                # totalizador por provedor/modelo — não há filtro por agent_id.
                {"llm_provider": "google", "llm_model": "gemini-3-pro", "total_tokens": 50},
            ]
        }
        with patch("src.telemetry.get_telemetry") as mock_get_telemetry:
            mock_get_telemetry.return_value.get_token_summary.return_value = fake_summary
            total = _default_token_reader("exec1")
        assert total == 400

    def test_default_token_reader_lida_com_resumo_vazio(self):
        from src.usage import _default_token_reader

        with patch("src.telemetry.get_telemetry") as mock_get_telemetry:
            mock_get_telemetry.return_value.get_token_summary.return_value = {}
            total = _default_token_reader("exec1")
        assert total == 0

    def test_default_connection_retry_reader_delega_a_telemetria(self):
        from src.usage import _default_connection_retry_reader

        with patch("src.telemetry.get_telemetry") as mock_get_telemetry:
            mock_get_telemetry.return_value.get_connection_retry_count.return_value = 7
            total = _default_connection_retry_reader("exec1")
        assert total == 7
