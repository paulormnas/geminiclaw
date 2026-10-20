"""``v18.8-verdict-controlled-sessions`` 5.2a: nome de métrica composto em critério quantitativo.

Um teste por ``#### Scenario`` de ``specs/pipeline-robustness``. Sem rede, LLM real, Docker ou banco.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator.agent import ValidatorAgent
from src.knowledge.metric_criteria import _evaluate_metric_criteria, _metric_criteria
from src.llm.base import LLMResponse
from src.orchestration.orchestrator import AgentTask

pytestmark = pytest.mark.unit

CRITERION = "acuracia_teste_media >= 0.93 para confirmar h1"


def _evaluate(criterion: str, metrics: dict) -> tuple:
    return _evaluate_metric_criteria(_metric_criteria([criterion]), metrics)[0]


def _write(root: Path, rel: str, content) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


async def _review(root: Path, criteria: list[str]):
    provider = MagicMock()
    provider.model_name = "m"
    provider.generate = AsyncMock(return_value=LLMResponse(text='{"status": "pass", "feedback": "ok", "issues": []}'))
    task = AgentTask(agent_id="developer", prompt="x", task_name="modelo_lr", validation_criteria=criteria,
                     expected_artifacts=["modelo.txt"], hypothesis_id="hyp-1")
    with patch("src.agents.validator.agent.record_llm_call"):
        return await ValidatorAgent(provider=provider).review_result(task=task, response_text="ok", output_dir=root)


def test_chave_composta_em_snake_case():
    """Scenario: Chave composta em snake_case."""
    ok, detail = _evaluate(CRITERION, {"acuracia_teste_media": 0.615})
    assert ok is False and "valor real = 0.615" in detail


def test_chave_composta_atendida():
    ok, _ = _evaluate(CRITERION, {"acuracia_teste_media": 0.95})
    assert ok is True


def test_criterio_condicional():
    """Scenario: Critério condicional."""
    criterion = "se bloqueio_tipos = false: acuracia_teste_media >= 0.93"
    (crit,) = _metric_criteria([criterion])
    assert [(c.metric, c.operator, c.threshold) for c in crit.comparisons] == [("accuracy", ">=", 0.93)]
    ok, detail = _evaluate(criterion, {"acuracia_teste_media": 0.615})
    assert ok is False and "'acuracia_teste_media'" in detail


@pytest.mark.asyncio
async def test_reprovacao_so_por_limiar_vira_resultado_negativo(tmp_path):
    """Scenario: Reprovação só por limiar vira resultado negativo."""
    _write(tmp_path, "modelo_lr/metrics.json", {"acuracia_teste_media": 0.615})
    _write(tmp_path, "modelo_lr/modelo.txt", "modelo")
    review = await _review(tmp_path, [CRITERION])
    assert review.status == "fail" and review.outcome == "resultado_negativo"


def test_qualificador_de_outro_conjunto():
    """Scenario: Qualificador de outro conjunto."""
    ok, detail = _evaluate("acuracia_teste_media >= 0.93", {"cv_accuracy_mean": 0.90})
    assert ok is False and "não está em metrics.json" in detail


def test_nome_sem_alias():
    """Scenario: Nome sem alias."""
    assert _metric_criteria(["contagem_graficos >= 3"]) == []
