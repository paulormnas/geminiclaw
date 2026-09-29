"""Confinamento do `ingest` da skill document_processor ao diretório da sessão.

Revisão de segurança STRIDE (v16-in-process-agents, 6.1): o `file_path` vem do LLM e,
sem confinamento, permitiria ler e indexar qualquer arquivo do host (`.env`, chaves).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent_runtime.context import AgentContext, bind_agent_context, current_context
from src.skills.document_processor.skill import DocumentProcessorSkill, _resolve_ingest_path


def _bind(tmp_path: Path) -> AgentContext:
    ctx = AgentContext(
        session_id="sess-1",
        agent_session_id="sess-1-agent",
        agent_id="researcher",
        mode="assisted",
        output_dir=tmp_path / "outputs" / "sess-1",
        model="test-model",
    )
    bind_agent_context(ctx)
    return ctx


@pytest.fixture(autouse=True)
def _clear_context():
    token = current_context.set(None)
    yield
    current_context.reset(token)


@pytest.mark.unit
class TestResolveIngestPath:
    def test_without_agent_context_path_is_unchanged(self) -> None:
        assert _resolve_ingest_path("/qualquer/lugar.pdf") == "/qualquer/lugar.pdf"

    def test_file_in_input_snapshot_is_allowed(self, tmp_path: Path) -> None:
        ctx = _bind(tmp_path)
        doc = ctx.output_dir / "input_snapshot" / "artigo.txt"
        doc.parent.mkdir(parents=True)
        doc.write_text("texto")

        assert _resolve_ingest_path(str(doc)) == str(doc.resolve())

    def test_relative_path_is_resolved_from_input_snapshot(self, tmp_path: Path) -> None:
        ctx = _bind(tmp_path)
        doc = ctx.output_dir / "input_snapshot" / "artigo.txt"
        doc.parent.mkdir(parents=True)
        doc.write_text("texto")

        assert _resolve_ingest_path("artigo.txt") == str(doc.resolve())

    def test_file_in_artifacts_is_allowed(self, tmp_path: Path) -> None:
        ctx = _bind(tmp_path)
        doc = ctx.output_dir / "artifacts" / "resumo.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("resumo")

        assert _resolve_ingest_path(str(doc)) == str(doc.resolve())

    @pytest.mark.parametrize("path", ["/etc/passwd", "/etc/shadow", "../../../etc/passwd"])
    def test_paths_outside_session_are_refused(self, tmp_path: Path, path: str) -> None:
        _bind(tmp_path)
        with pytest.raises(PermissionError):
            _resolve_ingest_path(path)

    def test_sibling_session_is_refused(self, tmp_path: Path) -> None:
        _bind(tmp_path)
        other = tmp_path / "outputs" / "sess-2" / "input_snapshot" / "privado.txt"
        other.parent.mkdir(parents=True)
        other.write_text("de outra sessão")

        with pytest.raises(PermissionError):
            _resolve_ingest_path(str(other))

    def test_symlink_escaping_session_is_refused(self, tmp_path: Path) -> None:
        ctx = _bind(tmp_path)
        secret = tmp_path / ".env"
        secret.write_text("GEMINI_API_KEY=nao-vazar")
        link = ctx.output_dir / "input_snapshot" / "inocente.txt"
        link.parent.mkdir(parents=True)
        link.symlink_to(secret)

        with pytest.raises(PermissionError):
            _resolve_ingest_path(str(link))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_of_host_file_returns_error_and_never_extracts(tmp_path: Path) -> None:
    _bind(tmp_path)
    # DocumentProcessorSkill ainda não implementa `run` (abstrato em BaseSkill) e por isso não
    # instancia; a subclasse abaixo só existe para exercitar `execute_async` sem conectar a bancos.
    class _Skill(DocumentProcessorSkill):
        async def run(self, **kwargs):  # pragma: no cover
            raise NotImplementedError

    skill = _Skill.__new__(_Skill)
    skill.extractor_registry = MagicMock()
    skill.indexer = MagicMock(ingest=AsyncMock())

    result = await skill.execute_async(action="ingest", file_path="/etc/passwd")

    assert "error" in result
    skill.extractor_registry.extract.assert_not_called()
    skill.indexer.ingest.assert_not_awaited()
