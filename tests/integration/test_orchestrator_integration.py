import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator import AgentResult, AgentTask, Orchestrator
from src.output_manager import OutputManager
from src.session import SessionManager


@pytest.mark.integration
@pytest.mark.asyncio
async def test_orchestrator_single_agent_flow() -> None:
    """Fluxo completo com sessões e saídas reais e o runtime de agentes simulado.

    O agente simulado grava um artefato no diretório da sessão (como a ferramenta
    ``write_artifact`` faria) e devolve uma resposta; o orquestrador deve listá-lo e fechar a
    sessão do agente.
    """
    output_dir = tempfile.mkdtemp(prefix="gcout_", dir="/tmp")

    try:
        session_manager = SessionManager()
        output_manager = OutputManager(base_dir=output_dir)

        async def fake_agent(task: AgentTask, ctx) -> AgentResult:
            assert task.prompt == "Qual é a resposta para tudo?"
            artifacts = ctx.output_dir / "artifacts"
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / "result.txt").write_text("Resposta final: 42")
            return AgentResult(
                agent_id=task.agent_id,
                session_id=ctx.agent_session_id,
                status="success",
                response={"answer": "42", "source": "Douglas Adams"},
            )

        runtime = MagicMock()
        runtime.run = AsyncMock(side_effect=fake_agent)

        orchestrator = Orchestrator(
            session_manager=session_manager,
            output_manager=output_manager,
            agent_runtime=runtime,
        )

        task = AgentTask(agent_id="ag1", prompt="Qual é a resposta para tudo?")
        result = await orchestrator.handle_request("Qual é a resposta para tudo?", [task])

        assert result.total == 1
        assert result.succeeded == 1
        assert result.failed == 0
        assert result.results[0].status == "success"
        assert result.results[0].response["answer"] == "42"
        assert result.results[0].response["source"] == "Douglas Adams"
        assert result.results[0].agent_id == "ag1"

        # Verifica se o artefato foi listado
        assert len(result.artifacts) == 1
        assert result.artifacts[0]["name"] == "result.txt"
        assert result.artifacts[0]["task"] == "shared"

        # Verifica que a sessão foi criada e fechada
        session = session_manager.get(result.results[0].session_id)
        assert session is not None
        assert session.status == "closed"

    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
