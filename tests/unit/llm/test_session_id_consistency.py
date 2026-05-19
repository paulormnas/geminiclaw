"""Testes unitários para V13.1 — consistência de session_id no agent_loop.

V13.1.3 — Valida que o campo session_id da tool python_interpreter é
sempre sobrescrito com o valor canônico de SESSION_ID do ambiente,
independentemente do que o LLM gerar como argumento.
"""
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, arguments: dict) -> MagicMock:
    """Cria um ToolCall mock com name e arguments serializados."""
    tc = MagicMock()
    tc.name = name
    tc.id = f"call_{name}"
    tc.arguments = arguments
    return tc


def _make_llm_response(tool_calls: list | None = None, text: str = "") -> MagicMock:
    """Cria uma LLMResponse mock."""
    resp = MagicMock()
    resp.text = text
    resp.tool_calls = tool_calls or []
    resp.usage = {"prompt_tokens": 10, "completion_tokens": 5}
    resp.to_message.return_value = {"role": "assistant", "content": text}
    return resp


# ---------------------------------------------------------------------------
# Fixture: mock do provider LLM
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_provider():
    """Retorna um LLM provider completamente mockado."""
    provider = AsyncMock()
    # Por padrão, segunda chamada retorna resposta final sem tool calls
    return provider


# ---------------------------------------------------------------------------
# Cenário 1: session_id gerado pelo LLM ("1") é sobrescrito pelo env var
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_id_sobrescrito_pelo_env_var(monkeypatch):
    """V13.1.1: session_id='1' gerado pelo LLM é substituído pelo SESSION_ID env var."""
    monkeypatch.setenv("SESSION_ID", "eda_iris_001")

    tool_call = _make_tool_call("python_interpreter", {"session_id": "1", "code": "print('hello')"})
    # Primeira chamada: LLM emite tool call
    first_resp = _make_llm_response(tool_calls=[tool_call])
    # Segunda chamada: LLM conclui sem mais tools
    second_resp = _make_llm_response(text="Tarefa concluída.")

    captured_args: list[dict] = []

    async def fake_tool(**kwargs):
        captured_args.append(kwargs)
        return "ok"

    fake_tool.__name__ = "python_interpreter"
    fake_tool.parameters_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "code": {"type": "string"},
        },
        "required": ["session_id", "code"],
    }

    mock_prov = AsyncMock()
    mock_prov.generate.side_effect = [first_resp, second_resp]

    with patch("src.llm.agent_loop.get_provider", return_value=mock_prov), \
         patch("src.llm.agent_loop.compress_messages", new=AsyncMock(side_effect=lambda msgs, **kw: msgs)), \
         patch("src.llm.agent_loop.get_telemetry", return_value=MagicMock(
             record_token_usage=MagicMock(),
             record_tool_usage=MagicMock(),
         )):
        from src.llm.agent_loop import run_agent_loop

        await run_agent_loop(
            prompt="Execute EDA",
            instruction="Você é um agente de dados.",
            tools=[fake_tool],
        )

    assert len(captured_args) == 1, "A ferramenta deve ter sido chamada uma vez"
    assert captured_args[0]["session_id"] == "eda_iris_001", (
        "session_id deve ser sobrescrito pelo valor de SESSION_ID env var"
    )


# ---------------------------------------------------------------------------
# Cenário 2: Tool call sem campo session_id recebe o valor do env var
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_id_injetado_quando_ausente(monkeypatch):
    """V13.1.1: Tool call sem session_id recebe o valor de SESSION_ID env var."""
    monkeypatch.setenv("SESSION_ID", "tarefa_preprocessamento")

    # Tool call sem session_id nos argumentos
    tool_call = _make_tool_call("python_interpreter", {"code": "import pandas as pd"})
    first_resp = _make_llm_response(tool_calls=[tool_call])
    second_resp = _make_llm_response(text="Concluído.")

    captured_args: list[dict] = []

    async def fake_tool(**kwargs):
        captured_args.append(kwargs)
        return "ok"

    fake_tool.__name__ = "python_interpreter"
    fake_tool.parameters_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "code": {"type": "string"},
        },
        "required": ["code"],
    }

    mock_prov = AsyncMock()
    mock_prov.generate.side_effect = [first_resp, second_resp]

    with patch("src.llm.agent_loop.get_provider", return_value=mock_prov), \
         patch("src.llm.agent_loop.compress_messages", new=AsyncMock(side_effect=lambda msgs, **kw: msgs)), \
         patch("src.llm.agent_loop.get_telemetry", return_value=MagicMock(
             record_token_usage=MagicMock(),
             record_tool_usage=MagicMock(),
         )):
        from src.llm.agent_loop import run_agent_loop

        await run_agent_loop(
            prompt="Pre-processa dados",
            instruction="Agente de ML.",
            tools=[fake_tool],
        )

    assert len(captured_args) == 1
    assert captured_args[0]["session_id"] == "tarefa_preprocessamento", (
        "session_id deve ser injetado a partir do SESSION_ID env var"
    )


# ---------------------------------------------------------------------------
# Cenário 3: Tool call para ferramenta diferente de python_interpreter
#            NÃO é modificada
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_outras_ferramentas_nao_modificadas(monkeypatch):
    """V13.1.1: Ferramenta diferente de python_interpreter não tem session_id modificado."""
    monkeypatch.setenv("SESSION_ID", "session_canonico")

    tool_call = _make_tool_call("quick_search", {"query": "iris dataset", "session_id": "outro_valor"})
    first_resp = _make_llm_response(tool_calls=[tool_call])
    second_resp = _make_llm_response(text="Busca concluída.")

    captured_args: list[dict] = []

    async def fake_search(**kwargs):
        captured_args.append(kwargs)
        return "resultado da busca"

    fake_search.__name__ = "quick_search"
    fake_search.parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "session_id": {"type": "string"},
        },
        "required": ["query"],
    }

    mock_prov = AsyncMock()
    mock_prov.generate.side_effect = [first_resp, second_resp]

    with patch("src.llm.agent_loop.get_provider", return_value=mock_prov), \
         patch("src.llm.agent_loop.compress_messages", new=AsyncMock(side_effect=lambda msgs, **kw: msgs)), \
         patch("src.llm.agent_loop.get_telemetry", return_value=MagicMock(
             record_token_usage=MagicMock(),
             record_tool_usage=MagicMock(),
         )):
        from src.llm.agent_loop import run_agent_loop

        await run_agent_loop(
            prompt="Pesquisa sobre iris",
            instruction="Agente de busca.",
            tools=[fake_search],
        )

    assert len(captured_args) == 1
    assert captured_args[0].get("session_id") == "outro_valor", (
        "session_id de ferramentas que não são python_interpreter NÃO deve ser modificado"
    )


# ---------------------------------------------------------------------------
# Cenário 4: SESSION_ID não definido → usa fallback do próprio argumento da tool
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_id_fallback_quando_env_var_ausente(monkeypatch):
    """V13.1.1: Se SESSION_ID não estiver definido, o argumento original é preservado."""
    monkeypatch.delenv("SESSION_ID", raising=False)

    tool_call = _make_tool_call("python_interpreter", {"session_id": "valor_original", "code": "pass"})
    first_resp = _make_llm_response(tool_calls=[tool_call])
    second_resp = _make_llm_response(text="ok")

    captured_args: list[dict] = []

    async def fake_tool(**kwargs):
        captured_args.append(kwargs)
        return "ok"

    fake_tool.__name__ = "python_interpreter"
    fake_tool.parameters_schema = {
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
            "code": {"type": "string"},
        },
        "required": ["session_id", "code"],
    }

    mock_prov = AsyncMock()
    mock_prov.generate.side_effect = [first_resp, second_resp]

    with patch("src.llm.agent_loop.get_provider", return_value=mock_prov), \
         patch("src.llm.agent_loop.compress_messages", new=AsyncMock(side_effect=lambda msgs, **kw: msgs)), \
         patch("src.llm.agent_loop.get_telemetry", return_value=MagicMock(
             record_token_usage=MagicMock(),
             record_tool_usage=MagicMock(),
         )):
        from src.llm.agent_loop import run_agent_loop

        await run_agent_loop(
            prompt="Executa código",
            instruction="Agente.",
            tools=[fake_tool],
        )

    assert len(captured_args) == 1
    # Sem SESSION_ID no env, o fallback é o valor original do argumento
    assert captured_args[0]["session_id"] == "valor_original"
