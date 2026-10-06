"""Revisão de subtarefa robusta (v16-pipeline-robustness §2 e §3): artefatos tolerantes e métricas nomeadas."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator_agent import ValidatorAgent
from src.llm.base import LLMResponse
from src.orchestrator import AgentTask

pytestmark = pytest.mark.unit


def _agent(text='{"status": "pass", "feedback": "ok", "issues": []}'):
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text=text))
    return ValidatorAgent(provider=provider), provider


def _write(root, rel, content=b"x"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())


async def _review(agent, tmp_path, **task_kw):
    task = AgentTask(agent_id="developer", prompt="x", task_name=task_kw.pop("task_name", "eda"), **task_kw)
    with patch("src.agents.validator_agent.record_llm_call"):
        return await agent.review_result(task=task, response_text="ok", output_dir=tmp_path)


@pytest.mark.asyncio
async def test_prefixo_diferente_aprova_com_name_mismatch(tmp_path):
    """Scenario: Prefixo diferente do esperado (revisão não reprova por artefato ausente)."""
    _write(tmp_path, "eda/iris_hist.png")
    _write(tmp_path, "eda/iris_box.png")
    agent, _ = _agent()
    review = await _review(agent, tmp_path, expected_artifacts=["eda_hist.png", "eda_box.png"])
    assert review.status == "pass" and review.name_mismatch
    assert review.resolved_artifacts == {"eda_hist.png": "eda/iris_hist.png", "eda_box.png": "eda/iris_box.png"}


@pytest.mark.asyncio
async def test_menos_arquivos_que_o_esperado_reprova_listando_o_que_existe(tmp_path):
    """Scenario: Menos arquivos que o esperado."""
    _write(tmp_path, "eda/a.png")
    agent, _ = _agent()
    review = await _review(agent, tmp_path, expected_artifacts=["x1.png", "x2.png"])
    assert review.status == "fail"
    assert "a.png" in review.feedback and review.issues


@pytest.mark.asyncio
async def test_criterio_de_contagem_nao_exige_metrics_json(tmp_path):
    """Scenario: Critério de contagem não exige métricas."""
    _write(tmp_path, "eda/g1.png")
    agent, provider = _agent()
    review = await _review(agent, tmp_path, validation_criteria=["pelo menos 3 gráficos gerados"])
    assert review.status == "pass"
    provider.generate.assert_awaited()  # o critério foi ao revisor LLM


@pytest.mark.asyncio
async def test_metrics_json_de_outra_subtarefa_nao_vale(tmp_path):
    """Scenario: `metrics.json` de outra subtarefa."""
    _write(tmp_path, "outra/metrics.json", json.dumps({"metrics": {"accuracy": 0.99}}))
    (tmp_path / "modelo").mkdir()
    agent, _ = _agent()
    review = await _review(agent, tmp_path, task_name="modelo", validation_criteria=["acurácia >= 0.9"])
    assert review.status == "fail" and "metrics.json" in review.feedback


@pytest.mark.asyncio
async def test_metrics_json_de_dependencia_vale(tmp_path):
    _write(tmp_path, "dados/metrics.json", json.dumps({"metrics": {"accuracy": 0.99}}))
    (tmp_path / "modelo").mkdir()
    agent, _ = _agent()
    review = await _review(agent, tmp_path, task_name="modelo", depends_on=["dados"],
                           validation_criteria=["acurácia >= 0.9"])
    assert review.status == "pass"


@pytest.mark.asyncio
async def test_dois_criterios_um_falha(tmp_path):
    """Scenario: Dois critérios, um falha."""
    _write(tmp_path, "modelo/metrics.json", json.dumps({"metrics": {"accuracy": 0.95, "f1": 0.70}}))
    agent, _ = _agent()
    review = await _review(agent, tmp_path, task_name="modelo",
                           validation_criteria=["acurácia >= 0.9", "f1 >= 0.8"])
    assert review.status == "fail"
    assert "0.95" in review.feedback and "0.7" in review.feedback
    assert len(review.issues) == 1


@pytest.mark.asyncio
async def test_metrica_nomeada_ausente(tmp_path):
    """Scenario: Métrica nomeada ausente."""
    _write(tmp_path, "modelo/metrics.json", json.dumps({"metrics": {"accuracy": 0.95}}))
    agent, _ = _agent()
    review = await _review(agent, tmp_path, task_name="modelo", validation_criteria=["auc >= 0.9"])
    assert review.status == "fail" and "'auc'" in review.feedback


@pytest.mark.asyncio
async def test_metrica_com_nome_composto_e_alias_do_arquivo(tmp_path):
    _write(tmp_path, "modelo/metrics.json", json.dumps({"metrics": {"f1_score": 0.9}}))
    agent, _ = _agent()
    review = await _review(agent, tmp_path, task_name="modelo", validation_criteria=["f1 no teste >= 0.8"])
    assert review.status == "pass"


@pytest.mark.asyncio
async def test_modo_estrito_reprova_prefixo_diferente(tmp_path):
    """Scenario: Modo estrito."""
    _write(tmp_path, "eda/iris_hist.png")
    agent, _ = _agent()
    with patch("src.agents.validator_agent.ARTIFACT_MATCH_MODE", "strict"):
        review = await _review(agent, tmp_path, expected_artifacts=["eda_hist.png"])
    assert review.status == "fail"


@pytest.mark.asyncio
async def test_evidencia_do_revisor_mostra_arquivo_renomeado(tmp_path):
    _write(tmp_path, "eda/iris_hist.png")
    agent, provider = _agent()
    await _review(agent, tmp_path, expected_artifacts=["eda_hist.png"], validation_criteria=["gráfico gerado"])
    content = provider.generate.call_args.kwargs["messages"][0]["content"]
    assert "iris_hist.png" in content and "resolvido por extension" in content
    assert "NÃO é motivo" in provider.generate.call_args.kwargs["system"]


@pytest.mark.asyncio
async def test_assinatura_de_reprovacao_ignora_numeros(tmp_path):
    _write(tmp_path, "m/metrics.json", json.dumps({"metrics": {"accuracy": 0.5}}))
    agent, _ = _agent()
    r1 = await _review(agent, tmp_path, task_name="m", validation_criteria=["acurácia >= 0.9"])
    _write(tmp_path, "m/metrics.json", json.dumps({"metrics": {"accuracy": 0.6}}))
    r2 = await _review(agent, tmp_path, task_name="m", validation_criteria=["acurácia >= 0.9"])
    assert r1.signature and r1.signature == r2.signature
