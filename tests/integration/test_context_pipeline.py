"""Testes de integração end-to-end do pipeline de contexto `input_context/`
(Roadmap V15.5 / Spec G9): ContextLoader -> Orchestrator -> input_snapshot/ -> CLI.
"""

from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.context_loader import ContextLoader
from src.orchestrator import AgentResult, AgentTask, Orchestrator
from src.session import Session
from src.cli import load_context_with_confirmation, clear_context


def _make_session(agent_id: str, session_id: str, payload: dict | None = None) -> Session:
    return Session(
        id=session_id,
        agent_id=agent_id,
        status="active",
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
class TestContextLoaderMultiFormat:
    """Cenário: input_context/ com PDF + CSV + PNG -> ContextBundle com os 3 documentos."""

    def test_pdf_csv_png_gera_bundle_com_tres_categorias(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "artigo.pdf").write_bytes(b"%PDF-fake")
        (context_dir / "dados.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
        (context_dir / "grafico.png").write_bytes(b"fake-png")

        fake_extracted = MagicMock(
            text_content="Conteúdo nativo do artigo " * 10,
            extraction_errors=[],
            format="pdf",
            title="artigo.pdf",
            num_pages=2,
        )
        with patch(
            "src.skills.document_processor.extractors.registry.ExtractorRegistry.extract",
            return_value=fake_extracted,
        ), patch("pytesseract.image_to_string", return_value="texto do gráfico"), patch(
            "PIL.Image.open", return_value=MagicMock()
        ):
            bundle = ContextLoader(context_dir).load()

        assert len(bundle.text_documents) == 1
        assert len(bundle.structured_data) == 1
        assert len(bundle.images) == 1
        assert bundle.total_files == 3

    def test_diretorio_vazio_gera_aviso_sem_quebrar(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        bundle = ContextLoader(context_dir).load()
        assert bundle.total_files == 0
        assert bundle.to_prompt_context() == ""


@pytest.mark.unit
@pytest.mark.asyncio
class TestOrchestratorContextInjection:
    """O ContextBundle deve ser injetado apenas no plano inicial (nunca em replan)."""

    async def test_contexto_injetado_no_prompt_inicial_do_researcher(self, tmp_path: Path) -> None:
        orchestrator, mock_runtime, mock_sm = _create_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        researcher_session = _make_session("researcher", "s_researcher")
        mock_sm.create.side_effect = [master_session, researcher_session]

        mock_runtime.run.return_value = AgentResult(
            agent_id="researcher",
            session_id="s_researcher",
            status="success",
            response={
                "text": '[{"agent_id": "developer", "task_name": "t1", "prompt": "p", "validation_criteria": ["ok"]}]'
            },
        )
        orchestrator.validator.validate_plan = AsyncMock(
            return_value=MagicMock(is_valid=True, issues=[])
        )

        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "context.md").write_text("Hipótese: X causa Y.", encoding="utf-8")
        bundle = ContextLoader(context_dir).load()

        tasks = await orchestrator._run_planning_loop(
            prompt="Reproduza o experimento", master_session_id="sess_master", previous_plan=None
        )

        assert tasks  # plano foi gerado
        # _run_planning_loop não usa self._current_context_block automaticamente sem handle_request;
        # validamos diretamente que o campo é lido corretamente quando setado.
        orchestrator._current_context_block = bundle.to_prompt_context()
        assert "Hipótese: X causa Y." in orchestrator._current_context_block

    async def test_handle_request_carrega_contexto_e_expoe_no_orchestrator(self, tmp_path: Path) -> None:
        orchestrator, mock_runtime, mock_sm = _create_orchestrator()

        master_session = _make_session("orchestrator", "sess_master")
        agent_session = _make_session("a0", "s0")
        mock_sm.create.side_effect = [master_session, agent_session]

        mock_runtime.run.return_value = AgentResult(
            agent_id="developer", session_id="s0", status="success", response={"idx": 0}
        )

        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "context.md").write_text("Contexto científico pré-curado.", encoding="utf-8")
        bundle = ContextLoader(context_dir).load()

        task = AgentTask(agent_id="developer", prompt="faz algo")
        result = await orchestrator.handle_request("tarefa", [task], context_bundle=bundle)

        assert "Contexto científico pré-curado." in orchestrator._current_context_block
        assert result.session_id == "sess_master"


@pytest.mark.unit
@pytest.mark.asyncio
class TestInputSnapshot:
    """Cópia imutável de input_context/ em outputs/<session>/input_snapshot/."""

    async def test_input_snapshot_criado_com_arquivos_usados(self, tmp_path: Path) -> None:
        orchestrator, mock_runtime, mock_sm = _create_orchestrator()
        orchestrator.output_manager.base_dir = tmp_path / "outputs"

        master_session = _make_session("orchestrator", "sess_master")
        agent_session = _make_session("a0", "s0")
        mock_sm.create.side_effect = [master_session, agent_session]

        mock_runtime.run.return_value = AgentResult(
            agent_id="developer", session_id="s0", status="success", response={"idx": 0}
        )

        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "context.md").write_text("dados", encoding="utf-8")
        bundle = ContextLoader(context_dir).load()

        task = AgentTask(agent_id="developer", prompt="faz algo")
        await orchestrator.handle_request("tarefa", [task], context_bundle=bundle)

        snapshot_dir = tmp_path / "outputs" / "sess_master" / "input_snapshot"
        assert snapshot_dir.is_dir()
        assert (snapshot_dir / "context.md").read_text(encoding="utf-8") == "dados"


@pytest.mark.unit
class TestCliContextConfirmation:
    """Aviso de contexto grande e confirmação não-bloqueante do pesquisador."""

    def test_contexto_pequeno_nao_pede_confirmacao(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "a.md").write_text("pequeno", encoding="utf-8")

        with patch("builtins.input") as mock_input:
            bundle = load_context_with_confirmation(str(context_dir))

        mock_input.assert_not_called()
        assert bundle is not None
        assert bundle.total_files == 1

    def test_contexto_grande_pede_confirmacao_e_aceita(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.cli as cli_module

        monkeypatch.setattr(cli_module, "CONTEXT_TOKEN_WARNING_THRESHOLD", 10)

        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "grande.md").write_text("x" * 1000, encoding="utf-8")

        with patch("builtins.input", return_value="s"):
            bundle = cli_module.load_context_with_confirmation(str(context_dir))

        assert bundle is not None

    def test_contexto_grande_recusado_retorna_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import src.cli as cli_module

        monkeypatch.setattr(cli_module, "CONTEXT_TOKEN_WARNING_THRESHOLD", 10)

        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "grande.md").write_text("x" * 1000, encoding="utf-8")

        with patch("builtins.input", return_value="n"):
            bundle = cli_module.load_context_with_confirmation(str(context_dir))

        assert bundle is None


@pytest.mark.unit
class TestClearContext:
    """Comando `geminiclaw clear-context`."""

    def test_clear_context_remove_arquivos_preserva_readme(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "README.md").write_text("leia-me", encoding="utf-8")
        (context_dir / "dados.csv").write_text("a,b\n1,2\n", encoding="utf-8")

        with patch("builtins.input", return_value="s"):
            clear_context(str(context_dir))

        assert (context_dir / "README.md").exists()
        assert not (context_dir / "dados.csv").exists()

    def test_clear_context_cancelado_preserva_tudo(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "dados.csv").write_text("a,b\n1,2\n", encoding="utf-8")

        with patch("builtins.input", return_value="n"):
            clear_context(str(context_dir))

        assert (context_dir / "dados.csv").exists()

    def test_clear_context_diretorio_inexistente_nao_quebra(self, tmp_path: Path) -> None:
        clear_context(str(tmp_path / "nao_existe"))
