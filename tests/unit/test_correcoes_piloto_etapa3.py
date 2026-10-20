"""Correções achadas no piloto da etapa 3 (2026-10-20): métricas fora do contrato e laço do plano sem fim."""

import json
from itertools import count
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.subtask_contract import plan_contract_issues
from src.agents.validator.agent import ValidationResult, ValidatorAgent
from src.knowledge.ingestion_io import collect_evidence
from src.llm.base import LLMResponse
from src.orchestration.orchestrator import AgentResult, Orchestrator

pytestmark = pytest.mark.unit

PLAN = '[{"agent_id": "developer", "task_name": "t", "prompt": "p", "validation_criteria": ["c"]}]'


def _task(name, artifacts, **over):
    base = {"agent_id": "developer", "task_name": name, "prompt": "p", "validation_criteria": ["c"],
            "expected_artifacts": artifacts}
    base.update(over)
    return base


def test_plano_com_metrics_por_tarefa_e_corrigivel():
    plan = [_task("logistica", ["metrics_logistica.json", "params_logistica.json"])]
    issues, _ = plan_contract_issues(plan)
    assert sum(i.startswith("artefato_de_metrica_fora_do_contrato") for i in issues) == 2
    assert "metrics.json" in issues[0]


def test_plano_com_metrics_json_exato_e_aceito_e_nao_colide():
    plan = [_task("a", ["metrics.json", "params.json"]), _task("b", ["metrics.json", "params.json"])]
    assert plan_contract_issues(plan) == ([], [])


def test_outros_arquivos_com_nome_parecido_nao_sao_reprovados():
    plan = [_task("a", ["metricas_resumo.csv", "params_grid.csv", "relatorio_metrics.json"])]
    assert plan_contract_issues(plan) == ([], [])


def _sessao(tmp_path, arquivos):
    pasta = tmp_path / "sess" / "logistica"
    pasta.mkdir(parents=True)
    for nome, conteudo in arquivos.items():
        (pasta / nome).write_text(json.dumps(conteudo), encoding="utf-8")
    return tmp_path / "sess"


def test_ingestao_le_o_unico_metrics_com_sufixo(tmp_path):
    sessao = _sessao(tmp_path, {"metrics_logistica.json": {"acuracia": 0.9}})
    ev = collect_evidence(sessao, "logistica")
    assert ev.metrics_status == "ok" and ev.metrics == {"acuracia": 0.9}
    assert any("metrics_logistica.json" in w for w in ev.warnings)


def test_ingestao_prefere_o_metrics_json_do_contrato(tmp_path):
    sessao = _sessao(tmp_path, {"metrics.json": {"acuracia": 0.8}, "metrics_logistica.json": {"acuracia": 0.9}})
    assert collect_evidence(sessao, "logistica").metrics == {"acuracia": 0.8}


def test_ingestao_com_duas_variantes_continua_ausente(tmp_path):
    sessao = _sessao(tmp_path, {"metrics_a.json": {"acuracia": 0.9}, "metrics_b.json": {"acuracia": 0.7}})
    assert collect_evidence(sessao, "logistica").metrics_status == "ausente"


@pytest.mark.asyncio
@pytest.mark.parametrize("papel, aceita", [("preparacao", True), ("referencia", True), ("teste", False), ("", False)])
async def test_hipotese_vazia_so_vale_em_preparacao_e_referencia(papel, aceita):
    provider = MagicMock()
    provider.generate = AsyncMock(return_value=LLMResponse(text='{"status": "approved", "reason": "ok", "issues": []}'))
    task = _task("preparar", ["metrics.json"], hypothesis="", scientific_rationale="", papel=papel)
    with patch("src.agents.validator.agent.record_llm_call"):
        result = await ValidatorAgent(provider=provider).validate_plan([task], "x")
    assert result.is_valid is aceita
    if not aceita:
        assert any("'hypothesis' vazia" in i for i in result.issues)


def rejeicao_llm(n):
    return ValidationResult(is_valid=False, status="revision_needed", reason="r", issues=[f"objecao {n}"],
                            signature=f"sig{n}", deterministic=False)


@pytest.fixture
def orch():
    o = Orchestrator(session_manager=MagicMock(), output_manager=MagicMock())
    o.validator = MagicMock()
    o.validator.validate_plan = AsyncMock()
    return o


def _planner():
    return AgentResult(agent_id="researcher", session_id="s", status="success", response={"text": PLAN})


@pytest.mark.asyncio
async def test_objecoes_novas_do_validator_llm_viram_consultivas_no_limite(orch):
    n = count(1)
    orch.validator.validate_plan.side_effect = lambda **_: rejeicao_llm(next(n))
    with patch("src.orchestration.orchestrator.PLAN_LLM_REJECTION_LIMIT", 3):
        with patch.object(orch, "_execute_agent", AsyncMock(return_value=_planner())) as execute:
            tasks = await orch._run_planning_loop("p", "s")
    assert len(tasks) == 1 and execute.call_count == 4


@pytest.mark.asyncio
async def test_limite_nao_vale_para_reprovacao_deterministica(orch):
    n = count(1)
    orch.validator.validate_plan.side_effect = lambda **_: ValidationResult(
        is_valid=False, status="revision_needed", reason="r", issues=["x"], signature=f"d{next(n)}", deterministic=True)
    with patch("src.orchestration.orchestrator.PLAN_LLM_REJECTION_LIMIT", 1):
        with patch("src.orchestration.orchestrator.MAX_PLANNING_ITERATIONS", 4):
            with patch.object(orch, "_execute_agent", AsyncMock(return_value=_planner())) as execute:
                tasks = await orch._run_planning_loop("p", "s")
    assert tasks == [] and execute.call_count == 4
