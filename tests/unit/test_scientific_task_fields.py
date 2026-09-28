"""Testes unitários dos campos de epistemologia científica em AgentTask
(Roadmap V15.1 / Spec G1): task_type, hypothesis, scientific_rationale.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator import AgentTask, AgentResult, Orchestrator


@pytest.mark.unit
class TestAgentTaskScientificFields:
    """Defaults retrocompatíveis dos novos campos."""

    def test_defaults_sao_retrocompativeis(self) -> None:
        task = AgentTask(agent_id="developer", image="img", prompt="faz algo")
        assert task.task_type is None
        assert task.hypothesis == ""
        assert task.scientific_rationale == ""

    def test_campos_aceitam_valores_explicitos(self) -> None:
        task = AgentTask(
            agent_id="developer",
            image="img",
            prompt="faz algo",
            task_type="reproduction",
            hypothesis="O modelo atinge acurácia > 0.85",
            scientific_rationale="Reproduz a Tabela 3 do artigo de referência",
        )
        assert task.task_type == "reproduction"
        assert task.hypothesis == "O modelo atinge acurácia > 0.85"
        assert task.scientific_rationale == "Reproduz a Tabela 3 do artigo de referência"


@pytest.mark.unit
@pytest.mark.asyncio
class TestPlanningLoopPopulatesScientificFields:
    """O plano aprovado deve propagar task_type/hypothesis/scientific_rationale para AgentTask."""

    async def test_campos_cientificos_propagados_do_plano_aprovado(self) -> None:
        orchestrator = Orchestrator(
            runner=MagicMock(),
            ipc=MagicMock(),
            session_manager=MagicMock(),
            output_manager=MagicMock(),
        )

        plan_json = (
            '[{"agent_id": "developer", "task_name": "treinar", "task_type": "reproduction", '
            '"prompt": "treina modelo", "hypothesis": "Acurácia > 0.85", '
            '"scientific_rationale": "Reproduz Tabela 3", '
            '"validation_criteria": ["Acurácia > 0.85 no teste"]}]'
        )

        with patch.object(orchestrator, "_execute_agent") as mock_exec:
            mock_exec.return_value = AgentResult(
                agent_id="researcher", session_id="s1", status="success", response={"text": plan_json}
            )
            orchestrator.validator.validate_plan = AsyncMock(
                return_value=MagicMock(is_valid=True, issues=[])
            )

            tasks = await orchestrator._run_planning_loop("Reproduza a Tabela 3", "master_s")

        assert len(tasks) == 1
        assert tasks[0].task_type == "reproduction"
        assert tasks[0].hypothesis == "Acurácia > 0.85"
        assert tasks[0].scientific_rationale == "Reproduz Tabela 3"

    async def test_plano_sem_campos_cientificos_usa_defaults(self) -> None:
        """Retrocompatibilidade: plano gerado antes desta spec não quebra o parsing."""
        orchestrator = Orchestrator(
            runner=MagicMock(),
            ipc=MagicMock(),
            session_manager=MagicMock(),
            output_manager=MagicMock(),
        )

        plan_json = (
            '[{"agent_id": "developer", "task_name": "t1", "prompt": "faz algo", '
            '"validation_criteria": ["ok"]}]'
        )

        with patch.object(orchestrator, "_execute_agent") as mock_exec:
            mock_exec.return_value = AgentResult(
                agent_id="researcher", session_id="s1", status="success", response={"text": plan_json}
            )
            orchestrator.validator.validate_plan = AsyncMock(
                return_value=MagicMock(is_valid=True, issues=[])
            )

            tasks = await orchestrator._run_planning_loop("tarefa qualquer", "master_s")

        assert len(tasks) == 1
        assert tasks[0].task_type is None
        assert tasks[0].hypothesis == ""
        assert tasks[0].scientific_rationale == ""
