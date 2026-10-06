"""Controle de recursos do runtime em processo (ADR 014).

Substitui os testes do semáforo e da espera por saúde do antigo ``ContainerRunner``: sem eles,
o ``asyncio.gather`` do laço autônomo dispararia todas as subtarefas prontas ao mesmo tempo.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_runtime.context import AgentContext
from src.agent_runtime.resources import ResourceGuard, calculate_dynamic_limit, wait_for_health
from src.agent_runtime.runtime import AgentRuntime


def _health(available_mb=None, temperature=None, raises=False) -> MagicMock:
    health = MagicMock()
    if raises:
        health.get_memory_usage.side_effect = Exception("Erro I/O")
    else:
        health.get_memory_usage.return_value = None if available_mb is None else {"available_mb": available_mb}
    health.get_temperature.return_value = temperature
    return health


@pytest.mark.unit
class TestDynamicLimit:
    @pytest.fixture(autouse=True)
    def _cap(self):
        with patch("src.agent_runtime.resources.MAX_CONCURRENT_AGENTS", 3):
            yield

    def test_6gb_or_more_allows_three(self) -> None:
        assert calculate_dynamic_limit(_health(available_mb=6200.0)) == 3

    def test_between_3_and_6gb_allows_two(self) -> None:
        assert calculate_dynamic_limit(_health(available_mb=4096.0)) == 2

    def test_under_3gb_allows_one(self) -> None:
        assert calculate_dynamic_limit(_health(available_mb=2048.0)) == 1

    def test_unreadable_memory_falls_back_to_default(self) -> None:
        assert calculate_dynamic_limit(_health(available_mb=None)) == 3  # macOS

    def test_read_error_falls_back_to_default(self) -> None:
        assert calculate_dynamic_limit(_health(raises=True)) == 3

    def test_never_exceeds_max_concurrent_agents(self) -> None:
        with patch("src.agent_runtime.resources.MAX_CONCURRENT_AGENTS", 2):
            assert calculate_dynamic_limit(_health(available_mb=8000.0)) == 2

    def test_never_below_one(self) -> None:
        with patch("src.agent_runtime.resources.MAX_CONCURRENT_AGENTS", 0):
            assert calculate_dynamic_limit(_health(available_mb=8000.0)) == 1


@pytest.mark.unit
@pytest.mark.asyncio
class TestWaitForHealth:
    @pytest.fixture(autouse=True)
    def _limits(self, monkeypatch):
        monkeypatch.setattr("src.agent_runtime.resources.PI_TEMPERATURE_LIMIT", 75.0)
        monkeypatch.setattr("src.agent_runtime.resources.PI_MIN_AVAILABLE_MEMORY_MB", 512.0)

        async def _instant(_seconds):
            return None

        monkeypatch.setattr("src.agent_runtime.resources.asyncio.sleep", _instant)

    async def test_returns_immediately_when_healthy(self) -> None:
        await wait_for_health(_health(available_mb=4000.0, temperature=50.0))

    async def test_waits_until_temperature_drops(self) -> None:
        health = _health(available_mb=4000.0)
        health.get_temperature.side_effect = [80.0, 78.0, 60.0]

        await wait_for_health(health)

        assert health.get_temperature.call_count == 3

    async def test_waits_until_memory_is_available(self) -> None:
        health = _health(temperature=50.0)
        health.get_memory_usage.side_effect = [{"available_mb": 100.0}, {"available_mb": 2000.0}]

        await wait_for_health(health)

        assert health.get_memory_usage.call_count == 2

    async def test_fails_explicitly_when_limits_persist(self) -> None:
        with pytest.raises(RuntimeError, match="Timeout aguardando saúde do sistema"):
            await wait_for_health(_health(available_mb=100.0, temperature=90.0), max_wait_seconds=20, poll_seconds=5)


async def _run_concurrently(guard: ResourceGuard, provider: str | None, workers: int) -> int:
    """Executa ``workers`` tarefas pela mesma vaga e devolve o pico de simultaneidade."""
    running = peak = 0

    async def work() -> None:
        nonlocal running, peak
        async with guard.slot(provider):
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

    await asyncio.gather(*(work() for _ in range(workers)))
    return peak


@pytest.mark.unit
@pytest.mark.asyncio
class TestResourceGuardSlots:
    @pytest.fixture(autouse=True)
    def _no_health_wait(self, monkeypatch):
        monkeypatch.setattr("src.agent_runtime.resources.HEALTH_CHECK_ENABLED", False)

    async def test_limits_simultaneous_agents(self) -> None:
        guard = ResourceGuard(health=_health(), max_concurrent=2)
        assert await _run_concurrently(guard, "google", workers=6) == 2

    async def test_local_inference_has_its_own_lower_limit(self) -> None:
        guard = ResourceGuard(health=_health(), max_concurrent=3, local_llm_concurrent=1)
        assert await _run_concurrently(guard, "ollama", workers=5) == 1

    async def test_remote_providers_ignore_the_local_inference_limit(self) -> None:
        guard = ResourceGuard(health=_health(), max_concurrent=3, local_llm_concurrent=1)
        assert await _run_concurrently(guard, "google", workers=5) == 3

    async def test_limit_comes_from_available_memory_when_not_fixed(self) -> None:
        with patch("src.agent_runtime.resources.MAX_CONCURRENT_AGENTS", 3):
            guard = ResourceGuard(health=_health(available_mb=4096.0))
        assert guard.limit == 2

    async def test_health_gate_runs_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setattr("src.agent_runtime.resources.HEALTH_CHECK_ENABLED", True)
        gate = AsyncMock()
        monkeypatch.setattr("src.agent_runtime.resources.wait_for_health", gate)

        async with ResourceGuard(health=_health(), max_concurrent=1).slot("google"):
            pass

        gate.assert_awaited_once()

    async def test_slot_is_released_after_an_error(self) -> None:
        guard = ResourceGuard(health=_health(), max_concurrent=1)
        with pytest.raises(ValueError):
            async with guard.slot("google"):
                raise ValueError("falha no agente")

        async with guard.slot("google"):  # não trava: a vaga foi liberada
            pass


def _ctx(agent_id: str = "developer") -> AgentContext:
    from pathlib import Path

    return AgentContext(
        session_id="s",
        agent_session_id="s-a",
        agent_id=agent_id,
        mode="assisted",
        output_dir=Path("/tmp/geminiclaw-test"),
        model="m",
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestAgentRuntimeUsesTheGuard:
    async def test_health_failure_becomes_an_error_result_not_an_exception(self) -> None:
        """O runtime nunca levanta exceção: falta de saúde do sistema vira AgentResult de erro."""
        from src.orchestrator import AgentTask

        guard = MagicMock()
        slot = MagicMock()
        slot.__aenter__ = AsyncMock(side_effect=RuntimeError("Timeout aguardando saúde do sistema."))
        slot.__aexit__ = AsyncMock(return_value=False)
        guard.slot.return_value = slot

        result = await AgentRuntime(guard=guard).run(AgentTask(agent_id="developer", prompt="p"), _ctx())

        assert result.status == "error"
        assert "saúde do sistema" in result.error

    async def test_slot_is_requested_with_the_role_provider(self) -> None:
        from src.orchestrator import AgentTask

        guard = MagicMock()
        slot = MagicMock()
        slot.__aenter__ = AsyncMock(return_value=None)
        slot.__aexit__ = AsyncMock(return_value=False)
        guard.slot.return_value = slot

        runtime = AgentRuntime(guard=guard)
        with patch.object(runtime, "_execute", AsyncMock(return_value="ok")), patch.object(
            AgentRuntime, "_provider_name", staticmethod(lambda _agent_id: "ollama")
        ):
            result = await runtime.run(AgentTask(agent_id="developer", prompt="p"), _ctx())

        assert result.status == "success"
        guard.slot.assert_called_once_with("ollama")

    async def test_unknown_role_falls_back_to_the_researcher_provider(self) -> None:
        """Papel fora do catálogo usa o provedor resolvido do researcher (não há mais provedor global)."""
        from src.model_config import get_role_model_config

        assert AgentRuntime._provider_name("papel_inexistente") == get_role_model_config("researcher").provider
