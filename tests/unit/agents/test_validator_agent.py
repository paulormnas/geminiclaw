"""Testes unitários para o ValidatorAgent (Roadmap V14.2)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from src.agents.validator_agent import ValidatorAgent, ValidationResult, ReviewResult
from src.llm.base import LLMResponse


@pytest.fixture
def mock_validator_provider():
    """Mock do provedor LLM configurado para o Validator."""
    provider = MagicMock()
    provider.generate = AsyncMock()
    provider.model_name = "qwen3:8b"
    return provider


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_approves_valid_plan(mock_validator_provider):
    """Cenário 1: Plano válido com todos os campos obrigatórios e validation_criteria aprovado."""
    mock_validator_provider.generate.return_value = LLMResponse(
        text='{"status": "approved", "reason": "Plano coerente e estruturado", "issues": []}'
    )
    validator = ValidatorAgent(provider=mock_validator_provider)

    valid_plan = [
        {
            "agent_id": "researcher",
            "task_name": "buscar_contexto",
            "prompt": "Pesquisar documentação técnica do algoritmo",
            "validation_criteria": ["Documento salvo em /outputs/ com links"],
            "expected_artifacts": ["contexto.md"],
            "depends_on": [],
        },
        {
            "agent_id": "developer",
            "task_name": "implementar_modelo",
            "prompt": "Criar script de treinamento em Python",
            "validation_criteria": ["Script executa sem erro e salva modelo"],
            "expected_artifacts": ["modelo.pkl"],
            "depends_on": ["buscar_contexto"],
        },
    ]

    result = await validator.validate_plan(valid_plan, prompt="Treinar modelo")
    assert result.is_valid is True
    assert result.status == "approved"
    assert len(result.issues) == 0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_rejects_plan_without_validation_criteria(mock_validator_provider):
    """Cenário 2: Plano sem validation_criteria em qualquer subtarefa é SEMPRE rejeitado (10/10)."""
    validator = ValidatorAgent(provider=mock_validator_provider)

    plan_missing_criteria = [
        {
            "agent_id": "developer",
            "task_name": "executar_codigo",
            "prompt": "Executar script Python",
            # validation_criteria AUSENTE
            "expected_artifacts": ["resultado.csv"],
            "depends_on": [],
        }
    ]

    # Executa 10 vezes para validar o critério de aceite (10/10 rejeições determinísticas)
    for _ in range(10):
        result = await validator.validate_plan(plan_missing_criteria, prompt="Executar código")
        assert result.is_valid is False
        assert result.status == "revision_needed"
        assert any("validation_criteria" in issue for issue in result.issues)

    # Também testa com lista vazia de critérios
    plan_empty_criteria = [
        {
            "agent_id": "developer",
            "task_name": "executar_codigo",
            "prompt": "Executar script Python",
            "validation_criteria": [],  # Vazio
            "expected_artifacts": ["resultado.csv"],
            "depends_on": [],
        }
    ]
    result = await validator.validate_plan(plan_empty_criteria, prompt="Executar código")
    assert result.is_valid is False
    assert result.status == "revision_needed"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_rejects_malformed_plan(mock_validator_provider):
    """Cenário 3: Plano com formato inválido ou campos obrigatórios faltantes."""
    validator = ValidatorAgent(provider=mock_validator_provider)

    # 1. Plano não é lista
    result = await validator.validate_plan({"not": "a list"}, prompt="Tarefa")
    assert result.is_valid is False
    assert "lista não vazia" in result.reason

    # 2. Subtarefa sem 'prompt' e sem 'agent_id'
    plan_missing_fields = [
        {
            "task_name": "tarefa_incompleta",
            "validation_criteria": ["Critério 1"],
        }
    ]
    result = await validator.validate_plan(plan_missing_fields, prompt="Tarefa")
    assert result.is_valid is False
    assert any("agent_id" in issue for issue in result.issues)
    assert any("prompt" in issue for issue in result.issues)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_review_result_checks_artifacts_on_disk(tmp_path):
    """Cenário 4: review_result verifica artefatos em disco e reprova se ausentes."""
    mock_provider = MagicMock()
    mock_provider.generate = AsyncMock(
        return_value=LLMResponse(text='{"status": "pass", "feedback": "OK", "issues": []}')
    )
    validator = ValidatorAgent(provider=mock_provider)

    task = {
        "task_name": "gerar_grafico",
        "expected_artifacts": ["grafico.png", "metricas.json"],
        "validation_criteria": ["Gráfico gerado em PNG"],
    }

    # Caso A: Nenhum arquivo no disco -> Falha
    result_missing = await validator.review_result(
        task=task,
        response_text="Gráfico gerado com sucesso!",
        output_dir=tmp_path,
    )
    assert result_missing.is_approved is False
    assert result_missing.status == "fail"
    assert "não foram encontrados no disco" in result_missing.feedback

    # Caso B: Arquivos criados no disco -> Sucesso
    (tmp_path / "grafico.png").write_text("png_content")
    (tmp_path / "metricas.json").write_text("{}")

    result_present = await validator.review_result(
        task=task,
        response_text="Gráfico gerado com sucesso!",
        output_dir=tmp_path,
    )
    assert result_present.is_approved is True
    assert result_present.status == "pass"
