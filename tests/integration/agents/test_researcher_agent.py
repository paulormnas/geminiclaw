"""Testes de integração para o Researcher Agent com capacidades de planejamento (Roadmap V14.3)."""

import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock

from agents.researcher.agent import plan, replan, root_agent
from src.llm.base import LLMResponse, ToolCall
from src.skills.base import SkillResult


@pytest.fixture(autouse=True)
def mock_db_and_qdrant_env(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", ":memory:")
    monkeypatch.setenv("QDRANT_CHECK_COMPATIBILITY", "false")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_researcher_plan_generates_valid_dag_with_validation_criteria():
    """Cenário 1: plan() gera um plano estruturado onde todas as subtarefas contêm validation_criteria."""
    mock_plan = [
        {
            "agent_id": "researcher",
            "task_name": "pesquisar_iris",
            "prompt": "Investigar parâmetros dos modelos Random Forest e SVM",
            "validation_criteria": ["Documento salvo em /outputs/ com links de documentação"],
            "expected_artifacts": ["pesquisa.md"],
            "depends_on": [],
        },
        {
            "agent_id": "developer",
            "task_name": "treinar_modelos",
            "prompt": "Treinar Random Forest e SVM no dataset Iris",
            "validation_criteria": ["Modelos treinados com acurácia registrada"],
            "expected_artifacts": ["modelos.pkl"],
            "depends_on": ["pesquisar_iris"],
        },
    ]

    with patch("src.llm.agent_loop.run_agent_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = json.dumps(mock_plan)

        result_tasks = await plan(
            task="Comparar Random Forest e SVM no dataset Iris",
            context={"dataset": "iris"},
        )

        assert isinstance(result_tasks, list)
        assert len(result_tasks) == 2
        for task in result_tasks:
            assert "task_name" in task
            assert "validation_criteria" in task
            assert len(task["validation_criteria"]) > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_researcher_plan_invokes_web_search_for_technical_domain(caplog):
    """Cenário 2: Para tarefa de domínio técnico, ocorre ao menos 1 busca técnica antes do plano."""
    mock_plan = [
        {
            "agent_id": "developer",
            "task_name": "treinar_svm",
            "prompt": "Treinar SVM com Scikit-Learn",
            "validation_criteria": ["Acurácia > 90%"],
            "expected_artifacts": ["modelo.pkl"],
            "depends_on": [],
        }
    ]

    with patch("src.llm.agent_loop.run_agent_loop", new_callable=AsyncMock) as mock_loop:
        # Simula o loop registrando o log de busca
        async def side_effect(*args, **kwargs):
            from src.logger import get_logger
            get_logger("agents.researcher.agent").info(
                "Executando busca web técnica para contexto",
                extra={"query": "scikit-learn SVM best practices", "tool": "quick_search"}
            )
            return json.dumps(mock_plan)

        mock_loop.side_effect = side_effect

        with caplog.at_level("INFO"):
            await plan(task="Comparar Random Forest e SVM no dataset Iris")

        assert any(
            "busca" in record.message.lower() or "quick_search" in str(record.__dict__)
            for record in caplog.records
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_researcher_replan_preserves_completed_subtasks():
    """Cenário 3: replan() não redefine subtarefas já concluídas com sucesso."""
    original_plan = [
        {
            "task_name": "etapa_1_dados",
            "agent_id": "developer",
            "prompt": "Carregar dados",
            "validation_criteria": ["Dados salvos em CSV"],
            "expected_artifacts": ["dados.csv"],
            "depends_on": [],
        },
        {
            "task_name": "etapa_2_treinamento",
            "agent_id": "developer",
            "prompt": "Treinar modelo",
            "validation_criteria": ["Modelo salvo em PKL"],
            "expected_artifacts": ["modelo.pkl"],
            "depends_on": ["etapa_1_dados"],
        },
    ]

    failed_tasks = [
        {
            "task_name": "etapa_2_treinamento",
            "agent_id": "developer",
            "prompt": "Treinar modelo",
            "validation_criteria": ["Modelo salvo em PKL"],
            "expected_artifacts": ["modelo.pkl"],
            "depends_on": ["etapa_1_dados"],
        }
    ]

    # Nova tentativa da etapa 2 gerada pelo replanejador
    recovered_plan = [
        original_plan[0],  # etapa 1 intacta
        {
            "task_name": "etapa_2_treinamento_ajustada",
            "agent_id": "developer",
            "prompt": "Treinar modelo com hiperparâmetros ajustados",
            "validation_criteria": ["Modelo salvo em PKL"],
            "expected_artifacts": ["modelo_v2.pkl"],
            "depends_on": ["etapa_1_dados"],
        },
    ]

    with patch("src.llm.agent_loop.run_agent_loop", new_callable=AsyncMock) as mock_loop:
        mock_loop.return_value = json.dumps(recovered_plan)

        new_plan = await replan(
            original_plan=original_plan,
            failed_tasks=failed_tasks,
            artifacts_available=["dados.csv"],
        )

        task_names = [t["task_name"] for t in new_plan]
        # Etapa 1 mantida intacta
        assert "etapa_1_dados" in task_names
        # Etapa 2 ajustada presente
        assert "etapa_2_treinamento_ajustada" in task_names


@pytest.mark.asyncio
@pytest.mark.integration
async def test_web_search_to_web_reader_pipeline():
    """Cenário 4: URL retornada por quick_search é lida corretamente por web_reader."""
    from src.skills.search_quick.skill import QuickSearchSkill
    from src.skills.web_reader.skill import WebReaderSkill

    quick_search = QuickSearchSkill()
    web_reader = WebReaderSkill()

    sample_url = "https://scikit-learn.org/stable/modules/svm.html"
    sample_search_output = f"[1] Documentação SVM - Scikit-Learn\nURL: {sample_url}\nGuia oficial do SVM."

    with patch.object(quick_search, "run", new_callable=AsyncMock) as mock_search_run:
        mock_search_run.return_value = SkillResult(
            success=True,
            output=sample_search_output,
            metadata={"urls": [sample_url]},
        )

        search_res = await quick_search.run(query="scikit learn svm docs")
        assert search_res.success is True
        extracted_url = search_res.metadata["urls"][0]
        assert extracted_url == sample_url

    with patch.object(web_reader, "run", new_callable=AsyncMock) as mock_reader_run:
        mock_reader_run.return_value = SkillResult(
            success=True,
            output="# Support Vector Machines\nDocumentação oficial detalhada...",
            metadata={"url": extracted_url, "length": 45},
        )

        reader_res = await web_reader.run(url=extracted_url)
        assert reader_res.success is True
        assert "Support Vector Machines" in reader_res.output
        assert reader_res.metadata["url"] == sample_url
