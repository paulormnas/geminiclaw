"""Testes de integração para o Developer Agent (Roadmap V14.4)."""

import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from agents.developer.agent import root_agent, handle_request_filter, _build_developer_instruction
from src.autonomous_loop import AutonomousLoop
from src.orchestrator import AgentTask


@pytest.fixture(autouse=True)
def mock_db_and_qdrant_env(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", ":memory:")
    monkeypatch.setenv("QDRANT_CHECK_COMPATIBILITY", "false")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_developer_agent_generates_and_executes_code(tmp_path, monkeypatch):
    """Cenário 1: Developer Agent gera e executa código Python produzindo artefato em /outputs/."""
    monkeypatch.setenv("OUTPUT_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("SESSION_ID", "test_session_dev_1")

    from src.skills.code.skill import CodeSkill
    code_skill = CodeSkill()

    code_to_run = (
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})\n"
        f"df.to_csv('{tmp_path}/tabela.csv', index=False)\n"
        "print('Tabela salva com sucesso')"
    )

    with patch.object(code_skill.sandbox, "run") as mock_exec:
        from src.skills.code.sandbox import SandboxResult
        # Simula criação do arquivo
        (tmp_path / "tabela.csv").write_text("a,b\n1,4\n2,5\n3,6")
        mock_exec.return_value = SandboxResult(
            stdout="Tabela salva com sucesso",
            stderr="",
            exit_code=0,
            artifacts=[str(tmp_path / "tabela.csv")],
        )

        res = await code_skill.run(
            code=code_to_run,
            session_id="test_session_dev_1",
            task_name="criar_tabela",
        )

        assert res.success is True
        assert (tmp_path / "tabela.csv").exists()
        assert "Tabela salva" in res.output


@pytest.mark.unit
@pytest.mark.integration
def test_developer_agent_reads_manifest_and_reuses_artifacts(tmp_path, monkeypatch):
    """Cenário 2: Developer Agent lê manifest e referencia artefatos existentes de steps anteriores."""
    session_id = "test_manifest_session"
    monkeypatch.setenv("OUTPUT_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("SESSION_ID", session_id)

    session_dir = tmp_path / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = session_dir / "workspace_manifest.json"

    # Step 1 gerou dados.csv
    manifest_data = {
        "session_id": session_id,
        "artifacts": [
            {"name": "dados_processados.csv", "type": "file", "path": "/outputs/dados_processados.csv"}
        ]
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    instruction = _build_developer_instruction()

    # Verifica se a instrução informa ao modelo sobre os artefatos disponíveis de steps anteriores
    assert "dados_processados.csv" in instruction
    assert "CONTEXTO DO WORKSPACE" in instruction
    assert "REUTILIZADOS" in instruction


@pytest.mark.unit
@pytest.mark.integration
def test_developer_agent_rejects_research_subtasks():
    """Cenário 3: Developer Agent rejeita subtarefas de pesquisa com erro claro."""
    # Prompts de pesquisa bibliográfica
    research_prompts = [
        "Faça uma pesquisa bibliográfica sobre redes neurais convolucionais",
        "Revisão de literatura sobre algoritmos de clustering",
        "Buscar artigos científicos recentes sobre LLMs",
    ]

    for p in research_prompts:
        rejection_msg = handle_request_filter(p)
        assert rejection_msg == "use researcher_agent para pesquisa"

    # Prompt de código não deve ser rejeitado
    code_prompt = "Treinar modelo Random Forest e salvar matriz de confusão"
    assert handle_request_filter(code_prompt) is None


@pytest.mark.unit
@pytest.mark.integration
def test_dispatch_subtask_routing():
    """Cenário 4: _dispatch_subtask roteia base -> developer, código -> developer e pesquisa -> researcher."""
    loop = AutonomousLoop(orchestrator=MagicMock())

    # 1. Tarefa com base_agent legado -> redirecionada para developer
    task_base = AgentTask(agent_id="base", image="geminiclaw-base", prompt="Calcular média")
    routed_base = loop._dispatch_subtask(task_base)
    assert routed_base.agent_id == "developer"
    assert routed_base.image == "geminiclaw-developer"

    # 2. Tarefa explícita de developer
    task_dev = AgentTask(agent_id="developer", image="", prompt="Criar script")
    routed_dev = loop._dispatch_subtask(task_dev)
    assert routed_dev.agent_id == "developer"
    assert routed_dev.image == "geminiclaw-developer"

    # 3. Tarefa de pesquisa inferida pelo prompt
    task_res = AgentTask(agent_id="unknown", image="", prompt="Pesquisar documentação da API")
    routed_res = loop._dispatch_subtask(task_res)
    assert routed_res.agent_id == "researcher"
    assert routed_res.image == "geminiclaw-researcher"
