"""Parada da sessão por cota ou teto de gasto esgotado (v18.7-benchmark-fixes, specs ``usage-limits`` e
``session-continuity``)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_runtime.runtime import AgentRuntime
from src.agent_runtime.types import AgentResult
from src.llm import quota
from src.llm.metering import bind_execution
from src.llm.quota import ProviderQuotaExhausted, record_quota_exhausted
from src.llm.retry import emit_connection_retry
from src.orchestration.autonomous_loop import AutonomousLoop
from src.orchestration.usage import StopReason, UsageBudget, UsageTracker
from src.session.continuity import MOTIVOS_RETOMAVEIS, RESUME_OK
from src.utils.agent_context import AgentContext
from tests.support.exploration_world import LoopHarness, hyp, plan, task
from tests.support.fake_recording_provider import SPENDING_CAP_MESSAGE

pytestmark = pytest.mark.unit


class FakeTelemetry:
    """Telemetria que conta ``connection_retry`` por execução e guarda os eventos de agente; o resto é simulado."""

    def __init__(self) -> None:
        self.retries: Counter[str] = Counter()
        self.events: list[dict[str, Any]] = []
        self._other = MagicMock()

    def record_connection_retry(self, **kw: Any) -> None:
        self.retries[kw["execution_id"]] += 1

    def record_agent_event(self, **kw: Any) -> None:
        self.events.append(kw)

    def get_connection_retry_count(self, execution_id: str) -> int:
        return self.retries[execution_id]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._other, name)


@pytest.fixture
def telemetry(monkeypatch):
    fake = FakeTelemetry()
    monkeypatch.setattr("src.observability.telemetry.get_telemetry", lambda: fake)
    monkeypatch.setattr("src.orchestration.autonomous_loop.get_telemetry", lambda: fake)
    quota._recorded.clear()
    yield fake
    quota._recorded.clear()


@pytest.fixture(autouse=True)
def _defaults():
    with patch("src.config.CURATOR_ENABLED", False):
        yield


def _exhausted(provider: str = "google", model: str = "gemini-4-argon") -> ProviderQuotaExhausted:
    return ProviderQuotaExhausted(provider, model, 429, SPENDING_CAP_MESSAGE)


def _quota_events(telemetry: FakeTelemetry) -> list[dict[str, Any]]:
    return [e for e in telemetry.events if e["event_type"] == "cota_provedor_esgotada"]


# --- AgentRuntime ------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_devolve_a_categoria_cota_provedor(monkeypatch):
    async def raising_loop(**kwargs: Any) -> str:
        raise _exhausted()

    monkeypatch.setattr("src.agent_runtime.runtime.run_agent_loop", raising_loop)
    monkeypatch.setattr("src.agent_runtime.runtime.ModelRouter.get_provider", lambda role, model=None: object())
    ctx = AgentContext(session_id="s", agent_session_id="s-a", agent_id="developer", mode="auto",
                       output_dir=Path("/tmp/x"), model="m")
    task_ = MagicMock(agent_id="developer", prompt="p", task_name="t")
    result = await AgentRuntime().run(task_, ctx)
    assert result.status == "error" and result.error_category == "cota_provedor"
    assert "spending cap" in result.error


# --- UsageTracker ------------------------------------------------------------------------------------------------


def test_precedencia_sobre_o_limite_de_conexao():
    """Scenario: Precedência sobre limite de conexão."""
    tracker = UsageTracker(
        UsageBudget.from_config(max_connection_retries=3), execution_id="s", token_reader=lambda: 0,
        connection_retry_reader=lambda: 99, egress_reader=lambda: 0,
        pending_stop=lambda: StopReason.PROVIDER_QUOTA,
    )
    status = tracker.check()
    assert status.connection_retries_exhausted and status.stop_reason == StopReason.PROVIDER_QUOTA


def test_tokens_e_tempo_vem_antes_da_cota():
    tracker = UsageTracker(
        UsageBudget.from_config(max_tokens=10), execution_id="s", token_reader=lambda: 10**6,
        connection_retry_reader=lambda: 0, egress_reader=lambda: 0, pending_stop=lambda: StopReason.PROVIDER_QUOTA,
    )
    assert tracker.check().stop_reason == StopReason.TOKENS


def test_pending_stop_do_laco_consulta_a_cota_da_sessao(telemetry):
    assert AutonomousLoop._pending_model_stop("mestra-1") is None
    assert AutonomousLoop._pending_model_stop() is None
    bind_execution("mestra-1", "mestra-1")
    record_quota_exhausted(_exhausted())
    assert AutonomousLoop._pending_model_stop("mestra-1") == StopReason.PROVIDER_QUOTA
    assert AutonomousLoop._pending_model_stop("outra") is None


# --- Laço autônomo ---------------------------------------------------------------------------------------------


class QuotaHarness(LoopHarness):
    """Harness em que o Developer esgota a cota na primeira chamada (e conta as chamadas)."""

    def __init__(self, *args: Any, fail_on: str = "developer", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fail_on = fail_on
        self.synthesize = AsyncMock(return_value=None)
        self.extra_patches.append(patch.object(AutonomousLoop, "_synthesize_results", self.synthesize))

    async def _run(self, task_: Any, ctx: Any) -> AgentResult:
        if task_.agent_id == self.fail_on:
            self.ran.append(task_.task_name or task_.agent_id)
            record_quota_exhausted(_exhausted())
            return AgentResult(
                agent_id=task_.agent_id, session_id="x", status="error", response={},
                error=SPENDING_CAP_MESSAGE, error_category="cota_provedor",
            )
        return await super()._run(task_, ctx)


@pytest.mark.asyncio
async def test_teto_de_gasto_durante_a_execucao_de_subtarefas(tmp_path, telemetry):
    """Scenario: Teto de gasto durante a execução de subtarefas."""
    first = plan([task("t1"), task("t2", depends_on=["t1"])], [hyp("h1")])
    h = QuotaHarness(tmp_path, plans=[first, first])
    await h.run()
    assert h.stop_reason == "limite_cota_provedor"
    assert h.ran == ["t1"] and h.plan_calls == 1  # a segunda subtarefa não é despachada e ninguém replaneja
    h.synthesize.assert_not_called()
    cp = h.payload["checkpoint"]
    assert cp["consolidation_pending"] is True and cp["cota_provedor"]["provedor"] == "google"
    assert cp["cota_provedor"]["modelo"] == "gemini-4-argon" and cp["cota_provedor"]["status"] == 429
    assert h.checkpoint().motivo_parada == "limite_cota_provedor" and h.checkpoint().curator_pendente is True
    assert len(_quota_events(telemetry)) == 1
    (sessao,) = h.w.raw.find_nodes("Sessao", {"sessao_id": h.w.sid}, limit=2)
    assert sessao.properties["motivo_parada"] == "limite_cota_provedor"


@pytest.mark.asyncio
async def test_cota_esgotada_no_planejamento(tmp_path, telemetry):
    """Scenario: Cota esgotada no planejamento (a sessão fecha sem contar o ciclo como plano rejeitado)."""
    h = QuotaHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])], fail_on="researcher")
    result = await h.run()
    assert h.stop_reason == "limite_cota_provedor"
    assert h.ran == ["researcher"] and h.plan_calls == 0
    assert result.total == 0
    h.synthesize.assert_not_called()


@pytest.mark.asyncio
async def test_limite_de_conexao_com_agente_em_processo(tmp_path, telemetry):
    """Scenario: Limite de conexão com agente em processo (as retentativas do provedor contam para a sessão)."""

    class Flaky(LoopHarness):
        async def _run(self, task_: Any, ctx: Any) -> AgentResult:
            if task_.agent_id == "developer":
                self.ran.append(task_.task_name)
                for _ in range(4):  # o provedor responde 503 e retenta, dentro do contexto do orquestrador
                    emit_connection_retry("llm_provider:google", "503")
                return AgentResult(agent_id="developer", session_id="x", status="error", response={},
                                   error="503", error_category="llm_connection")
            return await super()._run(task_, ctx)

    first = plan([task("t1"), task("t2", depends_on=["t1"])], [hyp("h1")])
    h = Flaky(tmp_path, plans=[first, first])
    await h.run(budget=UsageBudget.from_config(max_connection_retries=3))
    assert h.stop_reason == "limite_conexao"
    assert telemetry.retries[h.w.sid] >= 3


@pytest.mark.asyncio
async def test_nova_sessao_nao_herda_a_parada(tmp_path, telemetry):
    """Scenario: Nova sessão não herda a parada (o laço limpa o registro ao começar)."""
    bind_execution("sess", "sess")
    record_quota_exhausted(_exhausted())
    assert quota.quota_stop_for("sess") is not None
    h = QuotaHarness(tmp_path, plans=[plan([task("t1")], [hyp("h1")])], fail_on="nenhum")
    quota._recorded[h.w.sid] = _exhausted()  # sobra de uma sessão anterior com o mesmo id
    await h.run()
    assert h.stop_reason != "limite_cota_provedor" and h.ran == ["t1"]


# --- CLI e continuidade ----------------------------------------------------------------------------------------


def test_mensagem_acionavel_da_cli():
    """Scenario: Mensagem acionável."""
    from src.cli.main import quota_stop_message

    text = quota_stop_message("sessao-42", {"provedor": "google", "modelo": "gemini-4-argon", "status": 429})
    assert "limite_cota_provedor" in text and "google" in text and "gemini-4-argon" in text
    assert "geminiclaw resume --session sessao-42" in text
    assert "provedor não identificado" in quota_stop_message("s", None)


def test_secao_do_relatorio_descreve_a_cota():
    """Scenario: Seção do relatório."""
    from src.report.operation_metrics import describe_stop_reason

    text = describe_stop_reason("limite_cota_provedor")
    assert "limite_cota_provedor" in text and "cota ou teto de gasto esgotado no provedor" in text


def test_retomada_aceita():
    """Scenario: Retomada aceita."""
    from src.session.continuity import evaluate_resumability

    assert "limite_cota_provedor" in MOTIVOS_RETOMAVEIS
    cp = MagicMock(motivo_parada="limite_cota_provedor")
    assert evaluate_resumability("closed", cp, "limite_cota_provedor").decision == RESUME_OK


def test_no_sessao_com_o_motivo_novo():
    """Scenario: Nó Sessao com o motivo novo."""
    from src.knowledge.graph_store import InMemoryGraphStore
    from src.knowledge.provenance import Actor

    store = InMemoryGraphStore()
    store.create_node(
        "Sessao",
        {"projeto_id": "p", "sessao_id": "s", "modo": "auto", "inicio": "2026-10-16T00:00:00+00:00",
         "no_execucao": "A", "motivo_parada": "limite_cota_provedor"},
        actor=Actor(kind="orquestrador"),
    )
