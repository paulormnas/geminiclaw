"""Testes de integração do fluxo Human-in-the-Loop completo (Roadmap V15.3 / Spec G5).

Cobre: consulta ao pesquisador via _execute_agent, deduplicação de perguntas
similares, persistência de interações, monitoramento de limites operacionais e
geração de DivergenceReport.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator import Orchestrator, AgentTask, AgentResult
from src.autonomous_loop import AutonomousLoop
from src.session import Session
from src.cli import resume_session


def _make_session(session_id: str, payload: dict | None = None, status: str = "active") -> Session:
    return Session(
        id=session_id,
        agent_id="orchestrator",
        status=status,
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
        payload=payload or {},
    )


def _create_orchestrator():
    mock_session_manager = MagicMock()
    mock_runtime = MagicMock()
    mock_runtime.run = AsyncMock()
    orchestrator = Orchestrator(session_manager=mock_session_manager, agent_runtime=mock_runtime)
    return orchestrator, mock_runtime, mock_session_manager


@pytest.mark.unit
@pytest.mark.asyncio
class TestAskResearcherCore:
    """_ask_researcher_core: exibição, persistência e deduplicação."""

    async def test_pergunta_nova_bloqueia_e_persiste(self) -> None:
        orchestrator, _runtime, mock_sm = _create_orchestrator()
        mock_sm.get.return_value = _make_session("sess_1", payload={})

        task = AgentTask(agent_id="researcher", prompt="p", task_name="t1")

        with patch("asyncio.to_thread", new=AsyncMock(return_value="Use /outputs/dados.csv")):
            answer = await orchestrator._ask_researcher_core(
                question="Onde está o dataset?",
                context="ctx",
                why_cant_proceed="motivo",
                options=["A", "B"],
                task=task,
                master_session_id="sess_1",
            )

        assert answer == "Use /outputs/dados.csv"
        mock_sm.update.assert_called_once()
        _, kwargs = mock_sm.update.call_args
        interactions = kwargs["payload"]["researcher_interactions"]
        assert len(interactions) == 1
        assert interactions[0]["question"] == "Onde está o dataset?"
        assert interactions[0]["researcher_response"] == "Use /outputs/dados.csv"
        assert interactions[0]["subtask_name"] == "t1"

    async def test_pergunta_similar_reaproveita_resposta_sem_bloquear(self) -> None:
        orchestrator, _runtime, mock_sm = _create_orchestrator()
        mock_sm.get.return_value = _make_session(
            "sess_1",
            payload={
                "researcher_interactions": [
                    {"question": "Onde está o dataset de treino?", "researcher_response": "Em /outputs/dados.csv"}
                ]
            },
        )

        task = AgentTask(agent_id="researcher", prompt="p", task_name="t2")

        with patch("asyncio.to_thread") as mock_to_thread:
            answer = await orchestrator._ask_researcher_core(
                question="Onde está o dataset de treino?",
                context="",
                why_cant_proceed="",
                options=[],
                task=task,
                master_session_id="sess_1",
            )

        mock_to_thread.assert_not_called()
        assert answer == "Em /outputs/dados.csv"

    async def test_pergunta_diferente_nao_reaproveita(self) -> None:
        orchestrator, _runtime, mock_sm = _create_orchestrator()
        mock_sm.get.return_value = _make_session(
            "sess_1",
            payload={"researcher_interactions": [{"question": "Qual formato de imagem usar?", "researcher_response": "PNG"}]},
        )

        task = AgentTask(agent_id="researcher", prompt="p", task_name="t3")

        with patch("asyncio.to_thread", new=AsyncMock(return_value="resposta nova")):
            answer = await orchestrator._ask_researcher_core(
                question="Onde está o dataset de treino?",
                context="",
                why_cant_proceed="",
                options=[],
                task=task,
                master_session_id="sess_1",
            )

        assert answer == "resposta nova"


@pytest.mark.unit
@pytest.mark.asyncio
class TestExecuteAgentAskResearcherRoundTrip:
    """O agente em execução consulta o pesquisador pelo callback do AgentContext."""

    async def test_agente_pergunta_ao_pesquisador_durante_a_execucao(self) -> None:
        orchestrator, runtime, mock_sm = _create_orchestrator()

        session = _make_session("agent_sess", payload={})
        mock_sm.create.return_value = session
        mock_sm.get.return_value = session

        answers: list[str] = []

        async def fake_run(task, ctx):
            # O agente pergunta no meio da execução e usa a resposta no resultado.
            answers.append(await ctx.ask_researcher("q", "ctx", "motivo", ["A", "B"]))
            return AgentResult(
                agent_id=task.agent_id, session_id=ctx.agent_session_id, status="success", response={"text": "concluído"}
            )

        runtime.run.side_effect = fake_run

        with patch.object(orchestrator, "_ask_researcher_core", new=AsyncMock(return_value="resposta")) as mock_core:
            task = AgentTask(agent_id="researcher", prompt="faz algo", task_name="t1")
            result = await orchestrator._execute_agent(task, "master_sess")

        mock_core.assert_awaited_once()
        assert mock_core.await_args.kwargs["question"] == "q"
        assert mock_core.await_args.kwargs["options"] == ["A", "B"]
        assert mock_core.await_args.kwargs["master_session_id"] == "master_sess"
        assert answers == ["resposta"]
        assert result.status == "success"
        assert result.response == {"text": "concluído"}


@pytest.mark.unit
@pytest.mark.asyncio
class TestOperationalThresholds:
    """Monitoramento de limites operacionais (tokens, custo, duração, execuções de agente)."""

    async def test_sem_uso_nenhum_limite_disparado(self) -> None:
        mock_orchestrator = MagicMock()
        mock_orchestrator._session_agent_run_counts = {}
        loop = AutonomousLoop(mock_orchestrator)
        loop._session_mode = "assisted"

        with patch("src.autonomous_loop.get_telemetry") as mock_get_tel:
            mock_get_tel.return_value.get_token_summary.return_value = {"by_provider_model": []}
            suspended = await loop._check_operational_thresholds("sess_1")

        assert suspended is False

    async def test_modo_semi_nunca_bloqueia_mesmo_com_limite_atingido(self) -> None:
        mock_orchestrator = MagicMock()
        mock_orchestrator._session_agent_run_counts = {}
        loop = AutonomousLoop(mock_orchestrator)
        loop._session_mode = "semi"

        with patch("src.autonomous_loop.get_telemetry") as mock_get_tel:
            mock_get_tel.return_value.get_token_summary.return_value = {
                "by_provider_model": [{"total_tokens": 10_000_000, "total_cost_usd": 100.0}]
            }
            with patch("builtins.input") as mock_input:
                suspended = await loop._check_operational_thresholds("sess_1")

        mock_input.assert_not_called()
        assert suspended is False

    async def test_modo_assisted_suspende_quando_pesquisador_confirma(self) -> None:
        mock_orchestrator = MagicMock()
        mock_orchestrator._session_agent_run_counts = {}
        loop = AutonomousLoop(mock_orchestrator)
        loop._session_mode = "assisted"

        with patch("src.autonomous_loop.get_telemetry") as mock_get_tel:
            mock_get_tel.return_value.get_token_summary.return_value = {
                "by_provider_model": [{"total_tokens": 10_000_000, "total_cost_usd": 100.0}]
            }
            with patch("asyncio.to_thread", new=AsyncMock(return_value="s")):
                suspended = await loop._check_operational_thresholds("sess_1")

        assert suspended is True
        mock_orchestrator.session_manager.update.assert_called_once_with("sess_1", status="suspended")

    async def test_modo_assisted_continua_quando_pesquisador_nao_confirma(self) -> None:
        mock_orchestrator = MagicMock()
        mock_orchestrator._session_agent_run_counts = {}
        loop = AutonomousLoop(mock_orchestrator)
        loop._session_mode = "assisted"

        with patch("src.autonomous_loop.get_telemetry") as mock_get_tel:
            mock_get_tel.return_value.get_token_summary.return_value = {
                "by_provider_model": [{"total_tokens": 10_000_000, "total_cost_usd": 100.0}]
            }
            with patch("asyncio.to_thread", new=AsyncMock(return_value="n")):
                suspended = await loop._check_operational_thresholds("sess_1")

        assert suspended is False


@pytest.mark.unit
@pytest.mark.asyncio
class TestDivergenceReport:
    """Geração e persistência de DivergenceReport após esgotar retries."""

    async def test_report_divergence_persiste_no_payload(self) -> None:
        mock_orchestrator = MagicMock()
        mock_orchestrator.session_manager.get.return_value = _make_session("sess_1", payload={})
        loop = AutonomousLoop(mock_orchestrator)
        loop._session_mode = "semi"

        task = AgentTask(
            agent_id="developer", prompt="p", task_name="treinar_modelo",
            hypothesis="Acurácia > 0.85",
        )
        await loop._report_divergence(task, ["erro 1", "erro 2", "erro 3"], "sess_1")

        mock_orchestrator.session_manager.update.assert_called_once()
        _, kwargs = mock_orchestrator.session_manager.update.call_args
        reports = kwargs["payload"]["divergence_reports"]
        assert len(reports) == 1
        assert reports[0]["task_name"] == "treinar_modelo"
        assert reports[0]["expected"] == "Acurácia > 0.85"
        assert reports[0]["obtained_per_attempt"] == ["erro 1", "erro 2", "erro 3"]

    async def test_report_divergence_exibido_no_modo_assisted(self, capsys: pytest.CaptureFixture) -> None:
        mock_orchestrator = MagicMock()
        mock_orchestrator.session_manager.get.return_value = _make_session("sess_1", payload={})
        loop = AutonomousLoop(mock_orchestrator)
        loop._session_mode = "assisted"

        task = AgentTask(agent_id="developer", prompt="p", task_name="t1")
        await loop._report_divergence(task, ["erro 1"], "sess_1")

        out = capsys.readouterr().out
        assert "DivergenceReport" in out
        assert "t1" in out


@pytest.mark.unit
@pytest.mark.asyncio
class TestResumeSession:
    """geminiclaw resume — retomada simplificada de sessão suspensa."""

    async def test_sessao_inexistente(self, capsys: pytest.CaptureFixture) -> None:
        orchestrator = MagicMock()
        orchestrator.session_manager.get.return_value = None

        await resume_session(orchestrator, "sess_x")

        assert "não encontrada" in capsys.readouterr().out

    async def test_sessao_nao_suspensa(self, capsys: pytest.CaptureFixture) -> None:
        orchestrator = MagicMock()
        orchestrator.session_manager.get.return_value = _make_session("sess_1", status="active")

        await resume_session(orchestrator, "sess_1")

        assert "não está suspensa" in capsys.readouterr().out

    async def test_sessao_suspensa_sem_prompt_original(self, capsys: pytest.CaptureFixture) -> None:
        orchestrator = MagicMock()
        orchestrator.session_manager.get.return_value = _make_session("sess_1", payload={}, status="suspended")

        await resume_session(orchestrator, "sess_1")

        assert "não é possível retomar" in capsys.readouterr().out

    async def test_sessao_suspensa_reexecuta_prompt_original(self, tmp_path) -> None:
        orchestrator = MagicMock()
        orchestrator.session_manager.get.return_value = _make_session(
            "sess_1", payload={"prompt": "Reproduza a Tabela 3", "mode": "assisted"}, status="suspended"
        )

        with patch("src.cli.load_context_with_confirmation") as mock_load, \
             patch("src.cli.execute_prompt", new=AsyncMock()) as mock_execute:
            from src.context_loader import ContextBundle
            mock_load.return_value = ContextBundle()

            await resume_session(orchestrator, "sess_1")

        mock_execute.assert_called_once()
        args, kwargs = mock_execute.call_args
        assert args[1] == "Reproduza a Tabela 3"
        assert kwargs["mode"] == "assisted"
