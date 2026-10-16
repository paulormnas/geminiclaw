"""Cenários da mudança v18.6-remove-unused-agents (remoção do ``reviewer`` e do código sem uso).

Cada teste cita o Scenario da spec em ``openspec/changes/archive/v18.6-remove-unused-agents/specs/``.
"""

from __future__ import annotations

import inspect
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.agent_runtime.definitions import get_agent_definitions, reset_definitions_cache
from src.llm.catalog import REQUIRED_ROLES, CatalogError
from src.llm.routing import read_pins, reset_removed_variables_warning
from src.orchestration.orchestrator import AGENT_IDS, AgentResult, AgentTask, Orchestrator
from src.orchestration.plan_normalizer import normalize_plan
from tests.support.catalog_fixtures import load

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


def _task(agent_id: str) -> dict:
    return {"agent_id": agent_id, "task_name": "t", "prompt": "p", "validation_criteria": ["c"]}


# --- agent-runtime: papéis de subtarefa do plano -----------------------------------------------------------------


def test_base_no_plano_vira_developer():
    """Scenario: `base` no plano."""
    result = normalize_plan([_task("base")])
    assert result.tasks[0]["agent_id"] == "developer"
    assert any(r.kind == "normalize_agent_id" for r in result.repairs)
    assert not result.unrecoverable


@pytest.mark.parametrize("papel", ["reviewer", "revisor", "summarizer", "sumarizador"])
def test_reviewer_no_plano_e_nao_recuperavel(papel):
    """Scenario: `reviewer` no plano (e `summarizer`, que a spec trata do mesmo modo)."""
    result = normalize_plan([_task(papel)])
    assert result.unrecoverable
    message = " ".join(result.unrecoverable)
    assert "developer" in message and "researcher" in message


def test_papeis_de_subtarefa_do_plano():
    assert AGENT_IDS == ("developer", "researcher")


def test_papeis_internos_continuam_executaveis():
    """Scenario: Papéis internos continuam executáveis."""
    reset_definitions_cache()
    try:
        definitions = get_agent_definitions()
    finally:
        reset_definitions_cache()
    assert {"developer", "researcher", "summarizer", "base", "curator"} <= set(definitions)
    assert "reviewer" not in definitions
    assert not (REPO / "src" / "agents" / "reviewer").exists()


def test_dispatch_de_papel_desconhecido_segue_por_palavras_chave():
    from src.orchestration.autonomous_loop import AutonomousLoop

    loop = AutonomousLoop(MagicMock())
    assert loop._dispatch_subtask(AgentTask(agent_id="base", prompt="calcular média")).agent_id == "developer"
    assert loop._dispatch_subtask(AgentTask(agent_id="x", prompt="buscar artigo")).agent_id == "researcher"
    assert loop._dispatch_subtask(AgentTask(agent_id="researcher", prompt="calcular")).agent_id == "researcher"


# --- código morto ------------------------------------------------------------------------------------------------


def test_handle_request_nao_aceita_mais_agent_tasks():
    assert "agent_tasks" not in inspect.signature(Orchestrator.handle_request).parameters


def _import_config(**env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", "import src.config as c; print(c.REVIEW_MODE)"],
        cwd=REPO, env={**os.environ, **env}, capture_output=True, text=True, timeout=60,
    )


def test_review_mode_end_only_falha_na_inicializacao():
    done = _import_config(REVIEW_MODE="end_only")
    assert done.returncode != 0 and "REVIEW_MODE" in done.stderr and "per_subtask" in done.stderr
    ok = _import_config(REVIEW_MODE="disabled")
    assert ok.returncode == 0 and ok.stdout.strip() == "disabled"


# --- llm-providers: catálogo e variável obsoleta -----------------------------------------------------------------


def test_catalogo_versionado_tem_cinco_papeis_obrigatorios():
    """Scenario: Catálogo versionado válido (cinco papéis, sem `reviewer`)."""
    from src.llm.catalog import load_catalog

    assert REQUIRED_ROLES == ("researcher", "developer", "summarizer", "validator", "base")
    catalog = load_catalog(local_path=Path("/nonexistent.yaml"), base_urls={})
    assert "reviewer" not in catalog.papeis
    for role in REQUIRED_ROLES:
        assert catalog.papeis[role].preferencia, role


def test_catalogo_local_com_papel_removido(tmp_path):
    """Scenario: Catálogo local com papel removido."""
    local = {"modelos": [], "papeis": {"reviewer": {"preferencia": ["ollama/qwen3:8b"]}}}
    with pytest.raises(CatalogError, match="reviewer.*removido"):
        load(tmp_path, local=local)


def test_catalogo_principal_com_papel_removido(tmp_path):
    from tests.support.catalog_fixtures import base_document

    doc = base_document()
    doc["papeis"]["reviewer"] = dict(doc["papeis"]["base"])
    with pytest.raises(CatalogError, match="reviewer.*removido"):
        load(tmp_path, doc)


def test_reviewer_model_definida_gera_warning(caplog, tmp_path):
    """Scenario: `REVIEWER_MODEL` definida."""
    reset_removed_variables_warning()
    from tests.support.catalog_fixtures import base_document

    catalog = load(tmp_path, base_document())
    env = {"REVIEWER_MODEL": "anthropic/claude-haiku-5-5"}
    with caplog.at_level(logging.WARNING, logger="src.llm.routing"):
        pins = read_pins(catalog, env)
    assert pins == {}  # segue sem usá-la
    avisos = [r for r in caplog.records if "REVIEWER_MODEL" in r.getMessage() and "removido" in r.getMessage()]
    assert len(avisos) == 1
    reset_removed_variables_warning()


# --- telemetria da revisão de subtarefa --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evento_subtask_review_tem_agent_id_validator(tmp_path):
    """Scenario: Telemetria da revisão (o evento; a chamada LLM é coberta em test_judge_independence)."""
    from src.agents.validator.agent import ValidatorAgent
    from src.orchestration.autonomous_loop import AutonomousLoop

    (tmp_path / "sess").mkdir()
    orchestrator = MagicMock()
    orchestrator.output_manager.base_dir = tmp_path
    orchestrator.output_manager.list_artifacts.return_value = []
    orchestrator.validator = ValidatorAgent(provider=MagicMock())
    task = AgentTask(agent_id="developer", prompt="x", task_name="t")
    result = AgentResult(agent_id="developer", session_id="s", status="success", response={"text": "ok"})
    telemetry = MagicMock()
    with patch("src.observability.telemetry.get_telemetry", return_value=telemetry):
        await AutonomousLoop(orchestrator)._review_subtask(task, result, "sess")
    call = telemetry.record_agent_event.call_args.kwargs
    assert call["event_type"] == "subtask_review" and call["agent_id"] == "validator"


# --- communication-eval ------------------------------------------------------------------------------------------


def test_sessao_antiga_com_agent_id_reviewer_aparece_em_revisao_subtarefa(tmp_path):
    """Scenario: Sessão antiga."""
    from scripts.benchmark import communication as comm

    event = {
        "event_type": "subtask_review", "agent_id": "reviewer", "task_name": "t", "ts": 1.0,
        "payload": {"approved": True, "status": "pass", "attempt": 1},
    }
    out = comm.evaluate_events([event], {}, tmp_path, {"reviewer": "google/antigo"})
    assert out["revisao_subtarefa"]["reviews"] == 1
    assert out["revisao_subtarefa"]["model"] == "google/antigo"
    assert "reviewer" not in out


def test_pool_do_juiz_exclui_reviewer():
    """Scenario: Pool do juiz."""
    from scripts.benchmark import comm_judge as cj

    assert "reviewer" not in cj.POOL_ROLES
    models = {"developer": "google/gemini-4-argon", "researcher": "google/gemini-4-argon",
              "reviewer": "anthropic/claude-sonnet-5-5"}
    with pytest.raises(cj.JudgeUnavailable):
        cj.select_judge(models)
