"""Regressão do benchmark: o revisor reprovava subtarefas cujos artefatos existiam em ``<subtarefa>/``."""

from unittest.mock import MagicMock

import pytest

from src.autonomous_loop import AutonomousLoop
from src.orchestrator import AgentResult, AgentTask

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_artifacts_written_in_subtask_folder_are_found(tmp_path):
    session_dir = tmp_path / "sess"
    (session_dir / "eda_iris").mkdir(parents=True)
    (session_dir / "eda_iris" / "eda_summary.json").write_text("{}")
    (session_dir / "eda_iris" / "iris_pairplot.png").write_bytes(b"x")

    orchestrator = MagicMock()
    orchestrator.output_manager.base_dir = tmp_path
    orchestrator.output_manager.list_artifacts.return_value = []  # nada em artifacts/
    from src.agents.validator_agent import ValidatorAgent

    orchestrator.validator = ValidatorAgent(provider=MagicMock())  # sem critérios: não chama o LLM

    task = AgentTask(
        agent_id="developer", prompt="eda", task_name="eda_iris",
        expected_artifacts=["eda_summary.json", "iris_pairplot.png"],
    )
    result = AgentResult(agent_id="developer", session_id="s", status="success", response={"text": "ok"})

    review = await AutonomousLoop(orchestrator)._review_subtask(task, result, "sess")

    assert review["status"] == "pass", review


@pytest.mark.asyncio
async def test_missing_artifact_is_still_reported(tmp_path):
    (tmp_path / "sess").mkdir()
    orchestrator = MagicMock()
    orchestrator.output_manager.base_dir = tmp_path
    orchestrator.output_manager.list_artifacts.return_value = []
    from src.agents.validator_agent import ValidatorAgent

    orchestrator.validator = ValidatorAgent(provider=MagicMock())
    task = AgentTask(agent_id="developer", prompt="x", task_name="t", expected_artifacts=["nao_existe.png"])
    result = AgentResult(agent_id="developer", session_id="s", status="success", response={"text": "ok"})

    review = await AutonomousLoop(orchestrator)._review_subtask(task, result, "sess")

    assert review["status"] == "fail" and "nao_existe.png" in review["issues"][0]
