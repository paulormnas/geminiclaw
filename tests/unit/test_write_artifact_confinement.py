"""Testes de confinamento de write_artifact (Roadmap V16/ADR 014, Design §4).

Cobre o Requirement "Escrita confinada ao diretório da sessão" da spec
``agent-runtime`` (openspec/changes/v16-in-process-agents/specs/agent-runtime/spec.md).
"""

from pathlib import Path

import pytest

from agents.base.tools import write_artifact
from src.agent_runtime.context import AgentContext, bind_agent_context, current_context


def _bind_context(tmp_path: Path) -> AgentContext:
    ctx = AgentContext(
        session_id="sess-1",
        agent_session_id="sess-1-agent",
        agent_id="developer",
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
@pytest.mark.asyncio
class TestWriteArtifactHappyPath:
    async def test_writes_inside_session_artifacts_dir(self, tmp_path: Path) -> None:
        ctx = _bind_context(tmp_path)

        result = await write_artifact("resumo.md", "conteúdo do artefato")

        expected_path = ctx.output_dir / "artifacts" / "resumo.md"
        assert expected_path.exists()
        assert expected_path.read_text(encoding="utf-8") == "conteúdo do artefato"
        assert str(expected_path.resolve()) in result


@pytest.mark.unit
@pytest.mark.asyncio
class TestWriteArtifactPathTraversal:
    """Cenário: Path traversal."""

    async def test_traversal_filename_stays_inside_artifacts_dir(self, tmp_path: Path) -> None:
        ctx = _bind_context(tmp_path)

        result = await write_artifact("../../etc/passwd", "conteudo malicioso")

        # Nunca deve escrever fora do diretório de artefatos da sessão.
        outside_path = Path("/etc/passwd")
        assert not (outside_path.exists() and outside_path.read_text(errors="ignore") == "conteudo malicioso")

        artifacts_dir = (ctx.output_dir / "artifacts").resolve()
        written = artifacts_dir / "passwd"
        assert written.exists()
        assert "Erro" not in result or written.exists()

    async def test_absolute_path_filename_confined(self, tmp_path: Path) -> None:
        ctx = _bind_context(tmp_path)

        await write_artifact("/etc/shadow", "x")

        artifacts_dir = (ctx.output_dir / "artifacts").resolve()
        assert (artifacts_dir / "shadow").exists()
        assert not Path("/etc/shadow").exists() or Path("/etc/shadow").read_text(errors="ignore") != "x"

    async def test_dot_dot_filename_rejected(self, tmp_path: Path) -> None:
        _bind_context(tmp_path)
        result = await write_artifact("..", "x")
        assert "Erro" in result


@pytest.mark.unit
@pytest.mark.asyncio
class TestWriteArtifactSymlink:
    """Cenário: Symlink."""

    async def test_symlink_target_outside_session_is_refused(self, tmp_path: Path) -> None:
        ctx = _bind_context(tmp_path)
        artifacts_dir = ctx.output_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_target = outside_dir / "secret.txt"
        outside_target.write_text("segredo pré-existente", encoding="utf-8")

        symlink_path = artifacts_dir / "evil.txt"
        symlink_path.symlink_to(outside_target)

        result = await write_artifact("evil.txt", "novo conteudo")

        assert "Erro" in result
        assert "symlink" in result.lower() or "link" in result.lower()
        # O alvo original fora do diretório de artefatos nunca deve ser sobrescrito.
        assert outside_target.read_text(encoding="utf-8") == "segredo pré-existente"


@pytest.mark.unit
@pytest.mark.asyncio
class TestWriteArtifactContainerFallback:
    """Sem AgentContext vinculado (modo container legado), usa /outputs fixo."""

    async def test_missing_outputs_dir_returns_error(self) -> None:
        # Sem contexto e sem /outputs montado no ambiente de teste — deve falhar de forma explícita.
        result = await write_artifact("resumo.md", "conteudo")
        assert "Erro" in result
