"""Testes unitários para o ValidatorAgent (Roadmap V14.2)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.validator_agent import ValidatorAgent
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


# ---------------------------------------------------------------------------
# Roadmap V15.1 / Spec G1 — hypothesis, scientific_rationale, task_type
# ---------------------------------------------------------------------------


def _base_task(**overrides):
    task = {
        "agent_id": "developer",
        "task_name": "treinar_modelo",
        "prompt": "Treinar modelo de classificação",
        "validation_criteria": ["Modelo treinado com sucesso"],
    }
    task.update(overrides)
    return task


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_rejects_empty_hypothesis(mock_validator_provider):
    """Subtarefa com 'hypothesis' vazia é rejeitada deterministicamente."""
    validator = ValidatorAgent(provider=mock_validator_provider)
    plan = [_base_task(hypothesis="   ")]

    result = await validator.validate_plan(plan, prompt="Treinar modelo")

    assert result.is_valid is False
    assert any("hypothesis" in issue for issue in result.issues)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_accepts_missing_scientific_rationale(mock_validator_provider):
    """Ausência de 'scientific_rationale' é aceita (campo opcional retrocompatível)."""
    mock_validator_provider.generate.return_value = LLMResponse(
        text='{"status": "approved", "reason": "ok", "issues": []}'
    )
    validator = ValidatorAgent(provider=mock_validator_provider)
    plan = [_base_task(hypothesis="O modelo atinge acurácia > 0.85")]
    assert "scientific_rationale" not in plan[0]

    result = await validator.validate_plan(plan, prompt="Treinar modelo")

    assert result.is_valid is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_rejects_empty_scientific_rationale(mock_validator_provider):
    """Subtarefa com 'scientific_rationale' vazia (presente, mas em branco) é rejeitada."""
    validator = ValidatorAgent(provider=mock_validator_provider)
    plan = [_base_task(scientific_rationale="")]

    result = await validator.validate_plan(plan, prompt="Treinar modelo")

    assert result.is_valid is False
    assert any("scientific_rationale" in issue for issue in result.issues)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_requires_quantitative_criterion_for_reproduction(mock_validator_provider):
    """task_type='reproduction' sem critério quantitativo é rejeitado."""
    validator = ValidatorAgent(provider=mock_validator_provider)
    plan = [_base_task(task_type="reproduction", validation_criteria=["Gráfico gerado corretamente"])]

    result = await validator.validate_plan(plan, prompt="Reproduzir Tabela 3 do artigo")

    assert result.is_valid is False
    assert any("critério quantitativo" in issue for issue in result.issues)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_accepts_quantitative_criterion_for_reproduction(mock_validator_provider):
    """task_type='reproduction' com critério quantitativo (threshold numérico) é aceito."""
    mock_validator_provider.generate.return_value = LLMResponse(
        text='{"status": "approved", "reason": "ok", "issues": []}'
    )
    validator = ValidatorAgent(provider=mock_validator_provider)
    plan = [_base_task(task_type="reproduction", validation_criteria=["Acurácia > 0.85 no conjunto de teste"])]

    result = await validator.validate_plan(plan, prompt="Reproduzir Tabela 3 do artigo")

    assert result.is_valid is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_accepts_qualitative_criterion_for_eda(mock_validator_provider):
    """task_type='eda' aceita validation_criteria qualitativo, sem exigir threshold numérico."""
    mock_validator_provider.generate.return_value = LLMResponse(
        text='{"status": "approved", "reason": "ok", "issues": []}'
    )
    validator = ValidatorAgent(provider=mock_validator_provider)
    plan = [_base_task(task_type="eda", validation_criteria=["Gráficos de distribuição gerados para todas as colunas"])]

    result = await validator.validate_plan(plan, prompt="Fazer EDA do dataset Iris")

    assert result.is_valid is True


@pytest.mark.asyncio
@pytest.mark.unit
async def test_validator_requires_quantitative_criterion_for_validation_type(mock_validator_provider):
    """task_type='validation' também exige critério quantitativo, assim como 'reproduction'."""
    validator = ValidatorAgent(provider=mock_validator_provider)
    plan = [_base_task(task_type="validation", validation_criteria=["Resultado documentado"])]

    result = await validator.validate_plan(plan, prompt="Validar hipótese X")

    assert result.is_valid is False
    assert any("critério quantitativo" in issue for issue in result.issues)


# ---------------------------------------------------------------------------
# Roadmap V15.2 / Spec G2 — review_result contra metrics.json real
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.unit
async def test_review_result_approves_when_metrics_meet_threshold(tmp_path, mock_validator_provider):
    """metrics.json com acurácia 0.87 e critério '> 0.85' -> aprovado, sem chamar o LLM."""
    validator = ValidatorAgent(provider=mock_validator_provider)

    task_dir = tmp_path / "treinar_modelo"
    task_dir.mkdir()
    (task_dir / "metrics.json").write_text(
        '{"task_name": "treinar_modelo", "seed": 42, "metrics": {"accuracy": 0.87}, "divergence_note": null}',
        encoding="utf-8",
    )

    task = {
        "task_name": "treinar_modelo",
        "validation_criteria": ["Acurácia > 0.85 no conjunto de teste"],
    }

    result = await validator.review_result(task=task, response_text="ok", output_dir=tmp_path)

    assert result.is_approved is True
    assert result.status == "pass"
    mock_validator_provider.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_review_result_fails_when_metrics_below_threshold(tmp_path, mock_validator_provider):
    """metrics.json com acurácia 0.60 e critério '> 0.85' -> reprovado."""
    validator = ValidatorAgent(provider=mock_validator_provider)

    task_dir = tmp_path / "treinar_modelo"
    task_dir.mkdir()
    (task_dir / "metrics.json").write_text(
        '{"metrics": {"accuracy": 0.60}, "divergence_note": null}', encoding="utf-8"
    )

    task = {"task_name": "treinar_modelo", "validation_criteria": ["Acurácia > 0.85"]}

    result = await validator.review_result(task=task, response_text="ok", output_dir=tmp_path)

    assert result.is_approved is False
    assert result.status == "fail"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_review_result_fails_when_metrics_json_missing(tmp_path, mock_validator_provider):
    """Critério quantitativo sem metrics.json em disco -> reprovado com issue clara."""
    validator = ValidatorAgent(provider=mock_validator_provider)

    task = {"task_name": "treinar_modelo", "validation_criteria": ["Acurácia > 0.85"]}

    result = await validator.review_result(task=task, response_text="ok", output_dir=tmp_path)

    assert result.is_approved is False
    assert result.status == "fail"
    assert any("metrics.json" in issue for issue in result.issues)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_review_result_divergent_but_documented(tmp_path, mock_validator_provider):
    """metrics.json com divergence_note preenchido -> status divergent_but_documented, não fail."""
    validator = ValidatorAgent(provider=mock_validator_provider)

    task_dir = tmp_path / "treinar_modelo"
    task_dir.mkdir()
    (task_dir / "metrics.json").write_text(
        '{"metrics": {"accuracy": 0.60}, '
        '"divergence_note": "Resultado diverge do artigo por diferença no pré-processamento."}',
        encoding="utf-8",
    )

    task = {"task_name": "treinar_modelo", "validation_criteria": ["Acurácia > 0.85"]}

    result = await validator.review_result(task=task, response_text="ok", output_dir=tmp_path)

    assert result.is_approved is True
    assert result.status == "divergent_but_documented"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_review_result_sem_criterio_quantitativo_nao_exige_metrics_json(tmp_path, mock_validator_provider):
    """Sem critério quantitativo, o fluxo genérico (artefatos + LLM) é usado normalmente."""
    mock_validator_provider.generate.return_value = LLMResponse(
        text='{"status": "pass", "feedback": "ok", "issues": []}'
    )
    validator = ValidatorAgent(provider=mock_validator_provider)

    task = {
        "task_name": "buscar_contexto",
        "validation_criteria": ["Documento salvo com resumo do artigo"],
    }

    result = await validator.review_result(task=task, response_text="Contexto salvo.", output_dir=tmp_path)

    assert result.is_approved is True
    mock_validator_provider.generate.assert_called_once()
