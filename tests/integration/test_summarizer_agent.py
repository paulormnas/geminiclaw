"""Testes de integração do relatório científico estruturado (Roadmap V15.4 / Spec G8).

Cobre: injeção de dados reais (ArtifactReader) no prompt do Summarizer,
geração de session_metadata.json ao final da sessão, e o comando
`geminiclaw convert`.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.orchestrator import Orchestrator, AgentTask, AgentResult
from src.autonomous_loop import AutonomousLoop
from src.session import Session
from src.cli import convert_report


def _make_session(session_id: str, payload: dict | None = None) -> Session:
    return Session(
        id=session_id,
        agent_id="orchestrator",
        status="active",
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
        payload=payload or {},
    )


@pytest.mark.unit
@pytest.mark.asyncio
class TestSynthesizeResultsInjectsRealData:
    """_synthesize_results deve injetar dados reais de metrics.json e researcher_interactions."""

    async def test_prompt_contem_metricas_reais_e_interacoes(self, tmp_path: Path) -> None:
        mock_orchestrator = MagicMock()
        mock_orchestrator.output_manager.base_dir = tmp_path
        mock_orchestrator.session_manager.get.return_value = _make_session(
            "sess_1",
            payload={
                "researcher_interactions": [{"question": "Onde está o dataset?", "researcher_response": "Em /outputs/"}],
                "divergence_reports": [],
            },
        )
        mock_orchestrator._execute_agent = AsyncMock(
            return_value=AgentResult(agent_id="summarizer", session_id="s1", status="success", response={"text": "relatorio"})
        )

        task_dir = tmp_path / "sess_1" / "treinar" / "treinar"
        task_dir.mkdir(parents=True)
        (task_dir / "metrics.json").write_text(
            json.dumps({"task_name": "treinar", "seed": 42, "metrics": {"accuracy": 0.87}, "divergence_note": None}),
            encoding="utf-8",
        )

        loop = AutonomousLoop(mock_orchestrator)
        results = [AgentResult(agent_id="developer", session_id="s0", status="success", response={"text": "ok"})]

        await loop._synthesize_results("Treinar modelo", results, "sess_1")

        sent_prompt = mock_orchestrator._execute_agent.call_args[0][0].prompt
        assert "0.87" in sent_prompt
        assert "Onde está o dataset?" in sent_prompt


@pytest.mark.unit
@pytest.mark.asyncio
class TestSessionMetadataGeneration:
    """handle_request deve salvar session_metadata.json com o schema esperado."""

    async def test_session_metadata_salvo_ao_final(self, tmp_path: Path) -> None:
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(
            return_value=AgentResult(agent_id="developer", session_id="s0", status="success", response={"text": "ok"})
        )

        mock_sm = MagicMock()
        master_session = _make_session("sess_master")
        agent_session = _make_session("s0")
        mock_sm.create.side_effect = [master_session, agent_session]
        mock_sm.get.return_value = _make_session(
            "sess_master", payload={"researcher_interactions": [{"question": "q", "researcher_response": "a"}]}
        )

        from src.output_manager import OutputManager
        output_manager = OutputManager(base_dir=str(tmp_path))

        orchestrator = Orchestrator(session_manager=mock_sm, output_manager=output_manager, agent_runtime=mock_runtime)

        task = AgentTask(agent_id="developer", prompt="faz algo")
        await orchestrator.handle_request("Reproduza a Tabela 3", [task])

        metadata_path = tmp_path / "sess_master" / "session_metadata.json"
        assert metadata_path.exists()
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert data["session_id"] == "sess_master"
        assert data["task"] == "Reproduza a Tabela 3"
        assert data["report_path"] == "relatorio_final.md"
        assert data["researcher_interactions"] == [{"question": "q", "researcher_response": "a"}]
        assert "token_usage" in data
        assert "cost_usd" in data
        assert "agent_runs" in data


@pytest.mark.unit
class TestConvertCommand:
    """geminiclaw convert --session <id> --format <fmt>."""

    def test_sessao_sem_relatorio_final(self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.cli as cli_module
        monkeypatch.setattr(cli_module, "OUTPUT_BASE_DIR", str(tmp_path))

        convert_report("sess_inexistente", "latex")

        assert "não encontrada" in capsys.readouterr().out

    def test_formato_invalido(self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.cli as cli_module
        monkeypatch.setattr(cli_module, "OUTPUT_BASE_DIR", str(tmp_path))

        session_dir = tmp_path / "sess_1"
        session_dir.mkdir()
        (session_dir / "relatorio_final.md").write_text("# Relatório\nConteúdo.", encoding="utf-8")

        convert_report("sess_1", "pdf")

        assert "latex, html, docx" in capsys.readouterr().out

    def test_conversao_bem_sucedida(self, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.cli as cli_module
        monkeypatch.setattr(cli_module, "OUTPUT_BASE_DIR", str(tmp_path))

        session_dir = tmp_path / "sess_1"
        session_dir.mkdir()
        (session_dir / "relatorio_final.md").write_text("# Relatório\nConteúdo do relatório.", encoding="utf-8")

        convert_report("sess_1", "html")

        assert (session_dir / "relatorio_final.html").exists()
        assert "convertido" in capsys.readouterr().out
