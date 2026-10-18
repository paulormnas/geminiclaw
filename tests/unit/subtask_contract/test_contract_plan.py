"""Validação do plano com o contrato (v18.7-subtask-contract §6): critério do Problema, colisão, teto e nomes.

Validator real com ``FakeRecordingProvider``; nenhum cenário chama provedor pago.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.agents.subtask_contract import ProblemObjective, plan_contract_issues
from src.agents.validator.agent import ValidatorAgent
from src.orchestration.plan_normalizer import normalize_plan
from tests.support.fake_recording_provider import FakeRecordingProvider

pytestmark = pytest.mark.unit

PROBLEM = ProblemObjective("acuracia", "maior_melhor", 0.9, "classe majoritária")
APPROVED = json.dumps({"status": "approved", "reason": "ok", "issues": []})


def _t(name, artifacts=(), deps=(), criteria=("relatório salvo",), **over):
    base = {"agent_id": "developer", "task_name": name, "prompt": f"faça {name}", "depends_on": list(deps),
            "validation_criteria": list(criteria), "expected_artifacts": list(artifacts)}
    base.update(over)
    return base


async def _validate(plan, reply=APPROVED, **kw):
    provider = FakeRecordingProvider(script=[reply])
    with patch("src.agents.validator.agent.record_llm_call"):
        result = await ValidatorAgent(provider=provider).validate_plan(plan=plan, prompt="tarefa", **kw)
    return result, provider


@pytest.mark.asyncio
async def test_validacao_do_plano_com_o_criterio_do_problema():
    """Scenario: Validação do plano com o critério do Problema."""
    result, provider = await _validate([_t("a")], problem=PROBLEM)
    assert result.is_valid
    message = provider.calls[0].messages[0]
    sources = [f.source for f in message["_fragments"]]
    assert "contrato:objetivo" in sources and sources.count("plano") == 2
    content = message["content"]
    assert "acuracia" in content and "0.9" in content and "classe majoritária" in content and "tarefa" in content


@pytest.mark.asyncio
async def test_sem_problema_nao_ha_fragmento_do_objetivo():
    _, provider = await _validate([_t("a")])
    assert "contrato:objetivo" not in [f.source for f in provider.calls[0].messages[0]["_fragments"]]


@pytest.mark.asyncio
async def test_colisao_real():
    """Scenario: Colisão real (sem chamada ao LLM)."""
    plan = [_t("treinar_modelo_a", ["results.csv"]), _t("treinar_modelo_b", ["results.csv"])]
    result, provider = await _validate(plan)
    assert not result.is_valid and result.deterministic and provider.calls == []
    assert result.issues == ["colisao_artefato: results.csv em treinar_modelo_a, treinar_modelo_b"]


@pytest.mark.asyncio
async def test_atualizacao_intencional():
    """Scenario: Atualização intencional."""
    plan = [_t("treinar_modelo_a", ["results.csv"]), _t("comparar_modelos", ["results.csv"], deps=["treinar_modelo_a"])]
    result, _ = await _validate(plan)
    assert result.is_valid and "artefato_atualizado" in result.warnings
    assert not any("colisao" in i for i in result.issues)


@pytest.mark.asyncio
async def test_dependencia_transitiva_tambem_e_atualizacao():
    plan = [_t("a", ["x.csv"]), _t("b", [], deps=["a"]), _t("c", ["x.csv"], deps=["b"])]
    assert plan_contract_issues(plan) == ([], ["artefato_atualizado"])


def test_metrics_e_params_ficam_fora_da_regra_de_colisao():
    plan = [_t("a", ["metrics.json", "params.json"]), _t("b", ["out/metrics.json", "params.json"])]
    assert plan_contract_issues(plan) == ([], [])


def test_colisao_compara_o_nome_sem_pasta():
    plan = [_t("a", ["pasta1/results.csv"]), _t("b", ["results.csv"])]
    assert plan_contract_issues(plan)[0] == ["colisao_artefato: results.csv em a, b"]


def test_verificacao_de_colisao_desligavel():
    plan = [_t("a", ["r.csv"]), _t("b", ["r.csv"])]
    with patch("src.config.PLAN_ARTIFACT_COLLISION_CHECK", False):
        assert plan_contract_issues(plan) == ([], [])


def test_contrato_desligado_desliga_as_verificacoes():
    plan = [_t("a", ["r.csv"]), _t("b", ["../r.csv"])]
    with patch("src.config.SUBTASK_CONTRACT_ENABLED", False):
        assert plan_contract_issues(plan) == ([], [])


@pytest.mark.asyncio
async def test_criterios_longos_demais():
    """Scenario: Critérios longos demais."""
    plan = [_t("treinar_modelo_a", criteria=["acurácia no teste >= 0.90 " + "x" * 800, "y" * 800])]
    result, provider = await _validate(plan)
    assert not result.is_valid and provider.calls == []
    assert "campo_do_contrato_longo: treinar_modelo_a.validation_criteria" in result.issues


def test_campo_dentro_do_teto_e_so_para_o_developer():
    long = ["z" * 2000]
    assert plan_contract_issues([_t("a", criteria=long, agent_id="researcher")]) == ([], [])
    with patch("src.config.CONTRACT_FIELD_MAX_CHARS", 5000):
        assert plan_contract_issues([_t("a", criteria=long)]) == ([], [])


@pytest.mark.asyncio
async def test_nome_de_artefato_invalido_reprova_no_validator():
    result, provider = await _validate([_t("a", ["../fora.csv"])])
    assert not result.is_valid and provider.calls == []
    assert result.issues == ["nome_de_artefato_invalido: ../fora.csv (subtarefa 'a')"]


@pytest.mark.parametrize("name", ["../fora.csv", "/abs.csv", "a/../b.csv", "com espaço.csv", "x" * 200, ""])
def test_nome_de_artefato_com_caminho_relativo_no_normalizador(name):
    """Scenario: Nome de artefato com caminho relativo."""
    plan = [_t("a", [name])]
    normalized = normalize_plan(plan)
    assert any(i.startswith("nome_de_artefato_invalido") for i in normalized.unrecoverable)


def test_nomes_validos_passam_no_normalizador():
    plan = [_t("a", ["metrics.json", "graficos/curva_roc-1.png", "_tmp.csv"])]
    assert not [i for i in normalize_plan(plan).unrecoverable if "nome_de_artefato" in i]


@pytest.mark.asyncio
async def test_instrucao_renderizada_com_criterio_sem_chave():
    """Scenario: Instrução renderizada."""
    reply = json.dumps({"status": "revision_needed", "reason": "r", "issues": ["criterio_sem_chave: comparar_modelos.c1"]})
    result, provider = await _validate([_t("comparar_modelos")], reply=reply)
    assert "criterio_sem_chave" in provider.calls[0].system
    assert result.status == "revision_needed" and "criterio_sem_chave: comparar_modelos.c1" in result.issues


@pytest.mark.asyncio
async def test_sem_contrato_a_instrucao_nao_menciona_a_regra():
    with patch("src.config.SUBTASK_CONTRACT_ENABLED", False):
        _, provider = await _validate([_t("a")])
    assert "criterio_sem_chave" not in provider.calls[0].system
