"""Revisão de subtarefa com contrato: aceite × integridade, parecer tipado, hash (v18.7-subtask-contract §5.1–5.3).

Revisor simulado com ``FakeRecordingProvider``; nenhum cenário chama provedor pago.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agent_runtime.types import AgentTask
from src.agents.subtask_contract import INTEGRITY_RULES, build_developer_contract, guard_review
from src.agents.validator.agent import ReviewResult, ValidatorAgent
from src.orchestration.autonomous_loop import AutonomousLoop
from tests.support.fake_recording_provider import FakeRecordingProvider
from tests.unit.subtask_contract.test_contract_dispatch import ContractHarness, _one_task

pytestmark = pytest.mark.unit

TASK = "treinar_modelo_a"
SCRIPT = "import json\nacc = (y_pred == y_test).mean()\njson.dump({'acuracia': acc}, open('metrics.json', 'w'))\n"


def _write(root: Path, rel: str, content) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def _task(criteria, artifacts=()):
    return AgentTask(agent_id="developer", prompt="x", task_name=TASK, validation_criteria=list(criteria),
                     expected_artifacts=list(artifacts), hypothesis="o modelo A melhora a acurácia")


def _contract(task):
    return build_developer_contract(task, [task], None, "tarefa", researcher_tainted=False)


def _verdict(**parsed) -> str:
    return json.dumps({"status": "fail", "feedback": "f", "issues": [], **parsed})


async def _review(tmp_path, criteria, reply, *, contract=True, artifacts=()):
    task = _task(criteria, artifacts)
    provider = FakeRecordingProvider(script=[reply])
    agent = ValidatorAgent(provider=provider)
    with patch("src.agents.validator.agent.record_llm_call"):
        review = await agent.review_result(
            task=task, response_text="feito", output_dir=tmp_path, **({"contract": _contract(task)} if contract else {})
        )
    return review, provider


METRIC_OK = "acurácia no teste >= 0.90"


@pytest.fixture
def disk(tmp_path):
    _write(tmp_path, f"{TASK}/metrics.json", {"metrics": {"acuracia": 0.93}})
    _write(tmp_path, f"{TASK}/script.py", SCRIPT)
    _write(tmp_path, f"{TASK}/relatorio.md", "# relatório\n")
    return tmp_path


@pytest.mark.asyncio
async def test_criterio_fraco_vira_observacao(disk):
    """Scenario: Critério fraco vira observação."""
    reply = _verdict(issues=[{"tipo": "aceite", "item": "c7", "texto": "o critério deveria exigir validação cruzada"}],
                     observacoes=[])
    review, provider = await _review(disk, ["relatório salvo", "gráficos gerados"], reply)
    assert review.status == "pass" and review.is_approved and review.issues == []
    assert "o critério deveria exigir validação cruzada" in review.observations
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_integridade_reprova_sempre(disk):
    """Scenario: Integridade reprova sempre (todos os critérios atendidos pelas métricas)."""
    reply = _verdict(issues=[{"tipo": "integridade", "regra": "sem_ajuste_no_teste",
                              "texto": "hiperparâmetros escolhidos pela acurácia no teste"}])
    review, _ = await _review(disk, [METRIC_OK], reply)
    assert review.status == "fail" and not review.is_approved
    assert review.issues == ["sem_ajuste_no_teste: hiperparâmetros escolhidos pela acurácia no teste"]
    assert review.typed_issues[0]["tipo"] == "integridade"


@pytest.mark.asyncio
async def test_integridade_com_regra_inexistente_vira_observacao(disk):
    reply = _verdict(issues=[{"tipo": "integridade", "regra": "inventada", "texto": "algo"}])
    review, _ = await _review(disk, [METRIC_OK], reply)
    assert review.status == "pass" and "algo" in review.observations


@pytest.mark.asyncio
async def test_criterio_ja_decidido_pelas_metricas_nao_reprova_pelo_revisor(disk):
    reply = _verdict(issues=[{"tipo": "aceite", "item": "c1", "texto": "acurácia insuficiente"}])
    review, _ = await _review(disk, [METRIC_OK, "relatório salvo"], reply)
    assert review.status == "pass" and "acurácia insuficiente" in review.observations


@pytest.mark.asyncio
async def test_formato_antigo_do_parecer(disk):
    """Scenario: Formato antigo do parecer."""
    reply = _verdict(issues=["matriz de confusão salva: arquivo vazio", "faltou discutir limitações"])
    review, _ = await _review(disk, ["relatório salvo", "matriz de confusão salva"], reply)
    assert review.status == "fail"
    assert review.typed_issues == [{"tipo": "aceite", "item": "c2", "texto": "matriz de confusão salva: arquivo vazio"}]
    assert review.observations == ["faltou discutir limitações"]
    assert "issue_sem_tipo" in review.motivos


@pytest.mark.asyncio
async def test_hash_do_contrato_no_parecer(disk):
    """Scenario: Hash do contrato no parecer."""
    task = _task(["relatório salvo"])
    contract = _contract(task)
    provider = FakeRecordingProvider(script=[_verdict(status="pass")])
    with patch("src.agents.validator.agent.record_llm_call"):
        review = await ValidatorAgent(provider=provider).review_result(
            task=task, response_text="ok", output_dir=disk, contract=contract
        )
    assert review.contract_sha256 == contract.sha256()


@pytest.mark.asyncio
async def test_so_criterios_de_metrica_aprovados_chamam_o_revisor_com_script_e_regras(disk):
    """Scenario: Só critérios de métrica, aprovados."""
    review, provider = await _review(disk, [METRIC_OK], _verdict(status="pass"))
    assert review.status == "pass" and len(provider.calls) == 1
    sent = "\n".join(str(m.get("content")) for m in provider.calls[0].messages)
    assert "acc = (y_pred == y_test).mean()" in sent and "SCRIPT EXECUTADO" in sent
    assert all(rule.id in sent for rule in INTEGRITY_RULES) and "CONTRATO DA SUBTAREFA" in sent
    assert "decididos pelas métricas" in sent


@pytest.mark.asyncio
async def test_integridade_desligada(disk):
    """Scenario: Integridade desligada."""
    with patch("src.config.REVIEW_INTEGRITY_ALWAYS", False):
        review, provider = await _review(disk, [METRIC_OK], _verdict(status="fail"))
    assert review.status == "pass" and provider.calls == []


@pytest.mark.asyncio
async def test_metrica_literal_reprova_sem_chamar_o_llm(disk):
    """Scenario: Métrica literal."""
    _write(disk, f"metricas_literais/{TASK}.json",
           {"exec_id": "e1", "achados": [{"metrica": "acuracia", "linha": 4, "padrao": "P1"}]})
    review, provider = await _review(disk, [METRIC_OK], _verdict(status="pass"))
    assert review.status == "fail" and provider.calls == []
    assert review.typed_issues[0] == {"tipo": "integridade", "regra": "metricas_calculadas",
                                      "texto": review.typed_issues[0]["texto"]}


@pytest.mark.asyncio
async def test_literal_de_metrica_fora_do_item_7_nao_reprova(disk):
    _write(disk, f"metricas_literais/{TASK}.json",
           {"exec_id": "e1", "achados": [{"metrica": "tempo_treino", "linha": 4, "padrao": "P1"}]})
    review, _ = await _review(disk, [METRIC_OK], _verdict(status="pass"))
    assert review.status == "pass"


@pytest.mark.asyncio
async def test_literal_com_qualificador_corresponde_a_metrica_do_contrato(disk):
    _write(disk, f"metricas_literais/{TASK}.json",
           {"exec_id": "e1", "achados": [{"metrica": "test_accuracy", "linha": 2, "padrao": "P2"}]})
    review, provider = await _review(disk, [METRIC_OK], _verdict(status="pass"))
    assert review.status == "fail" and provider.calls == []


@pytest.mark.asyncio
async def test_sem_contrato_o_comportamento_e_o_anterior(disk):
    review, provider = await _review(disk, [METRIC_OK], _verdict(status="fail"), contract=False)
    assert review.status == "pass" and provider.calls == [] and review.contract_sha256 == ""


@pytest.mark.asyncio
async def test_contrato_desligado_na_configuracao_volta_ao_anterior(disk):
    with patch("src.config.SUBTASK_CONTRACT_ENABLED", False):
        review, provider = await _review(disk, [METRIC_OK], _verdict(status="fail"))
    assert review.status == "pass" and provider.calls == [] and review.contract_sha256 == ""


def test_guarda_limita_observacoes_e_remove_repetidas():
    task = _task(["relatório salvo"])
    parsed = {"issues": [], "observacoes": ["a", "a", "b"] + [f"x{i}" for i in range(40)]}
    guarded = guard_review(parsed, _contract(task), INTEGRITY_RULES)
    assert not guarded.failed and guarded.observations[:2] == ("a", "b") and len(guarded.observations) <= 20


@pytest.mark.asyncio
async def test_laco_revisa_com_o_contrato_da_tentativa_e_registra_o_hash(tmp_path):
    """Scenario: Hash do contrato no parecer (evento ``subtask_review`` com ``contrato_sha256``)."""
    h = ContractHarness(tmp_path, plans=[_one_task()])
    async def fake_review(**kwargs):
        c = kwargs["contract"]
        return ReviewResult(is_approved=True, status="pass", feedback="ok", contract_sha256=c.sha256())

    review_mock = AsyncMock(side_effect=fake_review)
    h.orch.validator.review_result = review_mock
    seen: list[dict] = []
    from src.observability.telemetry import TelemetryCollector

    h.extra_patches += [
        patch("src.config.REVIEW_ENABLED", True), patch("src.config.REVIEW_MODE", "per_subtask"),
        patch.object(TelemetryCollector, "record_agent_event", autospec=True,
                     side_effect=lambda self, **kw: seen.append(kw)),
    ]
    await h.run()
    assert review_mock.await_count >= 1
    contract = review_mock.await_args.kwargs["contract"]
    assert contract is not None and contract.sha256() == h.contracts[0].sha256()
    events = [kw for kw in seen if kw.get("event_type") == "subtask_review"]
    assert events and events[0]["payload"]["contrato_sha256"] == h.contracts[0].sha256()


@pytest.mark.asyncio
async def test_revisao_do_laco_sem_contrato_nao_passa_o_argumento(tmp_path):
    h = ContractHarness(tmp_path, plans=[_one_task()])
    review_mock = AsyncMock(return_value=ReviewResult(is_approved=True, status="pass", feedback="ok"))
    h.orch.validator.review_result = review_mock
    h.extra_patches += [patch("src.config.REVIEW_ENABLED", True), patch("src.config.SUBTASK_CONTRACT_ENABLED", False)]
    await h.run()
    assert review_mock.await_count >= 1 and "contract" not in review_mock.await_args.kwargs


def test_ponto_de_envio_do_script_e_unico():
    root = Path(__file__).resolve().parents[3] / "src"
    users = [p.name for p in root.rglob("*.py") if "script_fragment(" in p.read_text(encoding="utf-8")]
    assert sorted(users) == ["agent.py", "subtask_contract.py"]
    assert AutonomousLoop  # o laço não monta o script: só passa o contrato
