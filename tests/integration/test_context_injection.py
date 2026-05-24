"""Testes de integração para V13.4 — Injeção de contexto no prompt do LLM.

V13.4.4 — Valida que o bloco de contexto do workspace (manifest) é injetado
corretamente no prompt antes de cada chamada ao LLM, e que o código do step
anterior falho é incluído quando pertinente.
"""
from __future__ import annotations

import pathlib
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.skills.code.manifest import WorkspaceManifest
from src.llm.context_injection import build_workspace_context_block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manifest(
    tmp_path: pathlib.Path,
    session_id: str = "test_session",
    task_name: str = "test_task",
) -> WorkspaceManifest:
    """Cria um manifest real em diretório temporário."""
    session_dir = tmp_path / session_id
    return WorkspaceManifest(
        session_dir=session_dir,
        session_id=session_id,
        task_name=task_name,
    )


def _make_llm_response(tool_calls: list | None = None, text: str = "") -> MagicMock:
    """Cria uma LLMResponse mock."""
    resp = MagicMock()
    resp.text = text
    resp.tool_calls = tool_calls or []
    resp.usage = {"prompt_tokens": 10, "completion_tokens": 5}
    resp.to_message.return_value = {"role": "assistant", "content": text}
    return resp


# ---------------------------------------------------------------------------
# Cenário 1: Manifest com 1 step bem-sucedido → prompt contém artefatos
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_context_block_with_successful_step(tmp_path):
    """V13.4.1: Com manifest de 1 step bem-sucedido, o bloco contém os artefatos listados."""
    manifest = _make_manifest(tmp_path)
    manifest.record_step(
        step=1,
        status="success",
        artifacts=["iris.csv", "boxplot.png"],
        summary="Dataset Iris carregado. Gráficos gerados.",
        code_file="step_01.py",
    )

    block = build_workspace_context_block(
        session_dir=tmp_path / "test_session",
        session_id="test_session",
        task_name="test_task",
        max_code_context_lines=150,
    )

    assert "[CONTEXTO DO WORKSPACE]" in block
    assert "iris.csv" in block
    assert "boxplot.png" in block
    assert "Steps concluídos: 1" in block


# ---------------------------------------------------------------------------
# Cenário 2: Manifest com step falho → prompt contém código anterior e erro
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_context_block_with_failed_step_injects_code(tmp_path):
    """V13.4.2: Com manifest de 1 step falho, o prompt contém o código anterior e o erro."""
    manifest = _make_manifest(tmp_path)

    # Salvar snapshot de código
    session_dir = tmp_path / "test_session"
    code_content = "import pandas as pd\ndf = pd.read_csv('/outputs/iris.csv')\nprint(df.head())"
    (session_dir / "step_01.py").write_text(code_content, encoding="utf-8")

    manifest.record_step(
        step=1,
        status="failed",
        artifacts=[],
        summary="Script EDA falhou.",
        error={
            "error_type": "AttributeError",
            "error_message": "'tuple' object has no attribute 'items'",
            "error_location": "step_01.py, linha 258",
        },
        code_file="step_01.py",
    )

    block = build_workspace_context_block(
        session_dir=session_dir,
        session_id="test_session",
        task_name="test_task",
        max_code_context_lines=150,
    )

    assert "AttributeError" in block
    assert "'tuple' object has no attribute 'items'" in block
    # O código do step anterior deve ser incluído
    assert "import pandas as pd" in block
    assert "linha 258" in block


# ---------------------------------------------------------------------------
# Cenário 3: Manifest ausente (primeira execução) → indica nenhum step anterior
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_context_block_without_manifest_indicates_first_run(tmp_path):
    """V13.4.1: Manifest ausente (primeira execução) → bloco indica nenhum step anterior."""
    # Diretório existe mas não tem manifest.json
    session_dir = tmp_path / "nova_sessao"
    session_dir.mkdir(parents=True)

    block = build_workspace_context_block(
        session_dir=session_dir,
        session_id="nova_sessao",
        task_name="minha_tarefa",
        max_code_context_lines=150,
    )

    assert "[CONTEXTO DO WORKSPACE]" in block
    assert "Steps concluídos: 0" in block
    # Não deve mencionar artefatos ou erros
    assert "Erro:" not in block


# ---------------------------------------------------------------------------
# Cenário 4: Código com 300 linhas → apenas as últimas 150 são injetadas
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_context_block_limits_code_to_max_lines(tmp_path):
    """V13.4.2: Código anterior com 300 linhas → injetadas apenas as últimas 150."""
    manifest = _make_manifest(tmp_path)
    session_dir = tmp_path / "test_session"

    # Código com 300 linhas, cada uma com número sequencial
    lines = [f"# linha {i}" for i in range(1, 301)]
    code_content = "\n".join(lines)
    (session_dir / "step_01.py").write_text(code_content, encoding="utf-8")

    manifest.record_step(
        step=1,
        status="failed",
        artifacts=[],
        summary="Falhou por bug.",
        error={
            "error_type": "ValueError",
            "error_message": "valor inválido",
            "error_location": "step_01.py, linha 295",
        },
        code_file="step_01.py",
    )

    block = build_workspace_context_block(
        session_dir=session_dir,
        session_id="test_session",
        task_name="test_task",
        max_code_context_lines=150,
    )

    # As linhas 1-150 NÃO devem estar no bloco
    assert "# linha 1\n" not in block
    assert "# linha 150\n" not in block
    # As linhas 151-300 DEVEM estar (últimas 150)
    assert "# linha 151" in block
    assert "# linha 300" in block


# ---------------------------------------------------------------------------
# Cenário 5: run_agent_loop inicia cada iteração com bloco de contexto injetado
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_run_agent_loop_injects_context_block_in_messages(tmp_path, monkeypatch):
    """V13.4.1: run_agent_loop injeta bloco de contexto antes de chamar o LLM."""
    session_id = "test_inject_session"
    task_name = "test_inject_task"

    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True)

    monkeypatch.setenv("SESSION_ID", session_id)
    monkeypatch.setenv("TASK_NAME", task_name)
    monkeypatch.setenv("OUTPUT_BASE_DIR", str(tmp_path))

    # Manifest com 1 step bem-sucedido e artefato
    manifest = WorkspaceManifest(
        session_dir=session_dir,
        session_id=session_id,
        task_name=task_name,
    )
    manifest.record_step(
        step=1,
        status="success",
        artifacts=["resultado.csv"],
        summary="Dados processados.",
        code_file="step_01.py",
    )

    final_resp = _make_llm_response(text="Tarefa finalizada.")
    mock_prov = AsyncMock()
    mock_prov.generate.return_value = final_resp

    captured_messages: list = []

    async def capturing_generate(messages, **kwargs):
        captured_messages.extend(messages)
        return final_resp

    mock_prov.generate.side_effect = capturing_generate

    with patch("src.llm.agent_loop.get_provider", return_value=mock_prov), \
         patch("src.llm.agent_loop.compress_messages", new=AsyncMock(side_effect=lambda msgs, **kw: msgs)), \
         patch("src.llm.agent_loop.get_telemetry", return_value=MagicMock(
             record_token_usage=MagicMock(),
             record_tool_usage=MagicMock(),
         )):
        from src.llm.agent_loop import run_agent_loop

        await run_agent_loop(
            prompt="Continue a análise.",
            instruction="Você é um agente de dados.",
            tools=[],
        )

    # Verificar que alguma mensagem contém o bloco de contexto com o artefato
    all_content = " ".join(
        str(m.get("content", "")) for m in captured_messages
    )
    assert "[CONTEXTO DO WORKSPACE]" in all_content
    assert "resultado.csv" in all_content
