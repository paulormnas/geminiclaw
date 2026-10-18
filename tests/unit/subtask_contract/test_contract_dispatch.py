"""Despacho, runtime e fixação do contrato (v18.7-subtask-contract §3).

Um teste por cenário da spec ``agent-prompts``. Sem rede nem provedor pago: ``FakeRecordingProvider`` e o harness do
laço de exploração.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.agent_runtime.types import AgentResult, AgentTask
from src.llm.agent_loop import run_agent_loop
from src.llm.base import LLMResponse, ToolCall
from src.llm.context_compression import PINNED_KEY, compress_messages
from src.orchestration.autonomous_loop import AutonomousLoop
from src.orchestration.exploration import ExplorationSession
from src.orchestration.exploration_contract import ContractMixin
from tests.support.exploration_world import LoopHarness, hyp, plan, task
from tests.support.fake_recording_provider import FakeRecordingProvider

pytestmark = pytest.mark.unit

CRITERIA = ["acurácia no teste >= 0.90", "matriz de confusão salva"]


class ContractHarness(LoopHarness):
    """Registra o contrato de cada execução do Developer; ``fail_first`` falha a primeira tentativa de cada tarefa."""

    def __init__(self, *args: Any, fail_first: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.contracts: list[Any] = []
        self.tasks_seen: list[AgentTask] = []
        self.fail_first = fail_first
        self._failed: set[str] = set()

    async def _run(self, task_: Any, ctx: Any) -> AgentResult:
        if task_.agent_id == "developer":
            self.contracts.append(task_.contract)
            self.tasks_seen.append(task_)
            if self.fail_first and task_.task_name not in self._failed:
                self._failed.add(task_.task_name)
                self.ran.append(task_.task_name)
                return AgentResult(agent_id="developer", session_id="x", status="error", response={}, error="falhou")
        return await super()._run(task_, ctx)


def _one_task(**over):
    return plan(
        [task("treinar_modelo_a", validation_criteria=list(CRITERIA), expected_artifacts=["metrics.json"],
              hypothesis="o modelo A melhora a acurácia", **over)],
        [hyp("h1")],
    )


# --- Despacho ---------------------------------------------------------------------------------------------------


def test_despacho_preserva_todos_os_campos():
    """Scenario: Despacho."""
    original = AgentTask(
        agent_id="developer", prompt="p", task_name="t", task_type="model_impl", hypothesis_ref="h1",
        hypothesis_id="id-h1", prompt_tainted=True, approach={"nome": "rf"}, papel_decidido="teste",
    )
    out = AutonomousLoop._dispatch_subtask(None, original)  # não usa ``self``
    assert (out.task_type, out.hypothesis_ref, out.prompt_tainted) == ("model_impl", "h1", True)
    assert out.hypothesis_id == "id-h1" and out.approach == {"nome": "rf"} and out.papel_decidido == "teste"
    assert out is not original


def test_despacho_normaliza_papel_desconhecido_sem_perder_campos():
    out = AutonomousLoop._dispatch_subtask(None, AgentTask(agent_id="x", prompt="calcule", task_type="eda"))
    assert out.agent_id == "developer" and out.task_type == "eda"


@pytest.mark.asyncio
async def test_contrato_chega_ao_runtime(tmp_path):
    h = ContractHarness(tmp_path, plans=[_one_task()])
    await h.run()
    assert h.ran == ["treinar_modelo_a"]
    contract = h.contracts[0]
    assert contract is not None and contract.task_name == "treinar_modelo_a"
    assert [c for _, c in contract.criteria] == CRITERIA
    assert contract.expected_artifacts == ("metrics.json",)
    assert h.tasks_seen[0].task_type == "model_impl"  # campo do plano chegou ao runtime


@pytest.mark.asyncio
async def test_contrato_desligado(tmp_path):
    """Scenario: Contrato desligado."""
    h = ContractHarness(tmp_path, plans=[_one_task()])
    with patch("src.config.SUBTASK_CONTRACT_ENABLED", False):
        await h.run()
    assert h.ran == ["treinar_modelo_a"] and h.contracts == [None]


@pytest.mark.asyncio
async def test_contrato_nao_vai_ao_researcher(tmp_path):
    h = ContractHarness(tmp_path, plans=[_one_task()])
    seen = []
    original = h._run

    async def spy(task_, ctx):
        if task_.agent_id == "researcher":
            seen.append(getattr(task_, "contract", None))
        return await original(task_, ctx)

    h.runtime.run = spy
    await h.run()
    assert seen and all(c is None for c in seen)


@pytest.mark.asyncio
async def test_nova_tentativa_reconstroi_o_contrato_do_plano_vigente(tmp_path):
    """Scenario: Nova tentativa depois de replanejamento."""
    h = ContractHarness(tmp_path, plans=[_one_task()], fail_first=True)
    real = AutonomousLoop._attempt_contract
    calls = {"n": 0}

    async def spy(self, task_, plan_, original, sid):
        calls["n"] += 1
        if calls["n"] == 2:  # o plano vigente muda entre as tentativas
            task_.validation_criteria = ["acurácia no teste >= 0.85", "matriz de confusão salva"]
        return await real(self, task_, plan_, original, sid)

    with patch.object(AutonomousLoop, "_attempt_contract", spy):
        await h.run()
    first, second = h.contracts[0], h.contracts[1]
    assert first is not second and first.sha256() != second.sha256()
    assert ">= 0.90" in first.criteria[0][1] and ">= 0.85" in second.criteria[0][1]
    assert all(">= 0.90" not in c for _, c in second.criteria)


# --- Campo longo ------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_campo_longo_retira_a_subtarefa_e_as_dependentes(tmp_path):
    """Scenario: Plano aceito com avisos e campo longo (retirada no ciclo, contada por motivo)."""
    p = plan(
        [task("longa", validation_criteria=["acurácia no teste >= 0.90 " + "x" * 300]),
         task("depende", depends_on=["longa"])],
        [hyp("h1")],
    )
    h = ContractHarness(tmp_path, plans=[p])
    events: list[tuple[str, dict]] = []
    h.extra_patches.append(patch.object(
        ExplorationSession, "_emit", autospec=True, side_effect=lambda self, kind, payload: events.append((kind, payload))
    ))
    with patch("src.config.CONTRACT_FIELD_MAX_CHARS", 100):
        await h.run()
    assert "longa" not in h.ran and "depende" not in h.ran and h.contracts == []
    cycle = next(pl for k, pl in events if k == "hypothesis_cycle")
    assert cycle["retiradas_por_motivo"] == {"campo_do_contrato_longo": 1, "depende_de_subtarefa_retirada": 1}


@pytest.mark.asyncio
async def test_campo_longo_nunca_e_despachado_mesmo_sem_retirada_no_ciclo(tmp_path):
    h = ContractHarness(tmp_path, plans=[plan([task("longa", validation_criteria=["r2 > 0.8 " + "x" * 300])],
                                              [hyp("h1")])])
    with patch("src.config.CONTRACT_FIELD_MAX_CHARS", 100), patch.object(
        ContractMixin, "drop_long_contract_fields", lambda self, live, plan_, dropped: None
    ):
        await h.run()
    assert "longa" not in h.ran and h.contracts == []  # nenhum provedor foi chamado para ela


# --- Laço do agente ---------------------------------------------------------------------------------------------


def _tool(name="python_interpreter"):
    def fn(**kwargs):
        return "x" * 3000

    fn.__name__ = name
    fn.parameters_schema = {"type": "object", "properties": {"code": {"type": "string"}}, "required": []}
    return fn


def _contract_fragments():
    task_ = AgentTask(agent_id="developer", prompt="x", task_name="treinar_modelo_a",
                      validation_criteria=list(CRITERIA), expected_artifacts=["metrics.json"])
    from src.agents.subtask_contract import build_developer_contract

    return build_developer_contract(task_, [task_], None, "tarefa", researcher_tainted=False).fragments()


def _calls(n):
    return [
        LLMResponse(text="", tool_calls=[ToolCall(id=f"c{i}", name="python_interpreter", arguments={"code": "1"})],
                    finish_reason="tool_calls")
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_laco_com_varias_voltas_leva_o_contrato_uma_vez(monkeypatch):
    """Scenario: Laço com várias voltas."""
    monkeypatch.setenv("OLLAMA_NUM_CTX", "100000")
    provider = FakeRecordingProvider(script=[*_calls(4), "fim"])
    await run_agent_loop("enunciado", "SISTEMA", [_tool()], provider=provider, pinned_prefix=_contract_fragments())
    assert len(provider.calls) == 5
    last = provider.calls[-1]
    with_contract = [m for m in last.messages if "CONTRATO DA SUBTAREFA" in str(m.get("content", ""))]
    assert len(with_contract) == 1
    first_user = next(m for m in last.messages if m["role"] == "user")
    assert first_user is with_contract[0]
    assert all(c.system == "SISTEMA" for c in provider.calls)


@pytest.mark.asyncio
async def test_sem_contrato_o_primeiro_user_e_o_enunciado(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_CTX", "100000")
    provider = FakeRecordingProvider(script=["fim"])
    await run_agent_loop("enunciado", "SISTEMA", [], provider=provider)
    users = [m for m in provider.calls[0].messages if m["role"] == "user"]
    assert users[0]["content"] == "enunciado"
    assert not any("CONTRATO" in str(m.get("content", "")) for m in provider.calls[0].messages)


@pytest.mark.asyncio
async def test_compressao_nao_remove_o_contrato(monkeypatch):
    """Scenario: Compressão não remove o contrato."""
    monkeypatch.setenv("OLLAMA_NUM_CTX", "1024")
    fragments = _contract_fragments()
    provider = FakeRecordingProvider(script=[*_calls(6), "fim"])
    await run_agent_loop("enunciado", "SISTEMA", [_tool()], provider=provider, pinned_prefix=fragments,
                         max_iterations=10)
    from src.utils.egress_fragments import plain_text

    expected = plain_text(fragments)
    last = provider.calls[-1]
    pinned = [m for m in last.messages if "CONTRATO DA SUBTAREFA" in str(m.get("content", ""))]
    assert len(pinned) == 1 and pinned[0]["content"] == expected
    # a compressão atuou no resto: o histórico enviado é menor que o acumulado
    assert len(last.messages) < 2 + 2 * 6 + 1


@pytest.mark.asyncio
async def test_compress_messages_preserva_a_fixada_na_posicao():
    from src.utils.egress_fragments import ContentOrigin as O
    from src.utils.egress_fragments import PromptFragment, labeled

    frag = PromptFragment("CONTRATO " * 40, O.INSTRUCAO, source="contrato")
    messages = [
        labeled("system", PromptFragment("SIS", O.INSTRUCAO, source="system")),
        labeled("user", frag, **{PINNED_KEY: True}),
        *[{"role": "user", "content": "y" * 600} for _ in range(10)],
    ]
    out = await compress_messages(messages, max_tokens=500, system="SIS")
    pinned = [m for m in out if m.get(PINNED_KEY)]
    assert len(pinned) == 1 and pinned[0]["content"] == messages[1]["content"]
    assert out.index(pinned[0]) <= 1 and all(m["role"] != "user" for m in out[: out.index(pinned[0])])
    assert len(out) < len(messages)


@pytest.mark.asyncio
async def test_evento_da_tentativa_registra_hash_e_limiar_mascarado(tmp_path):
    """Scenario: Researcher com dados brutos, Developer sem (evento da tentativa com ``limiar_mascarado``)."""
    from unittest.mock import MagicMock

    fake = MagicMock()
    h = ContractHarness(tmp_path, plans=[_one_task()])
    with patch("src.orchestration.autonomous_loop.get_telemetry", return_value=fake), patch(
        "src.orchestration.autonomous_loop.role_tainted", side_effect=lambda role: role != "developer"
    ), patch("src.agents.subtask_contract.role_tainted", return_value=True):
        await h.run()
    events = [c.kwargs for c in fake.record_agent_event.call_args_list if c.kwargs.get("event_type") == "subtask_contract"]
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["limiar_mascarado"] is True and payload["tentativa"] == 1
    assert payload["contrato_sha256"] == h.contracts[0].sha256() and payload["tarefa_original_truncada_de"] is None
