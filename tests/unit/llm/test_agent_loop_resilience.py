"""Testes unitários para V12.2 — Resiliência do Agent Loop.

Cobre os mecanismos:
  V12.2.1: ErrorTracker — após 3 erros consecutivos do mesmo tipo na mesma
           ferramenta, uma mensagem de sistema é injetada no contexto.
  V12.2.2: Detecção de resposta final vazia ou declarativa — faz retry com
           prompt de recuperação.
  V12.2.3: Limite de tentativas por ferramenta — após 4 falhas, a ferramenta
           é removida da lista de tools disponíveis.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.llm.agent_loop import run_agent_loop, ErrorTracker
from src.llm.base import LLMResponse, ToolCall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(name: str, raises: Exception = None, return_value: str = "ok"):
    """Cria uma ferramenta mock que pode lançar exceção ou retornar valor."""
    if raises:
        def tool_fn(**kwargs):
            raise raises
    else:
        def tool_fn(**kwargs):
            return return_value
    tool_fn.__name__ = name
    tool_fn.parameters_schema = {
        "type": "object",
        "properties": {"arg": {"type": "string"}},
        "required": [],
    }
    return tool_fn


def _make_provider(responses: list) -> AsyncMock:
    """Cria um provider mock com side_effect."""
    provider = AsyncMock()
    provider.generate.side_effect = responses
    return provider


# ---------------------------------------------------------------------------
# V12.2.1 — ErrorTracker: detecção de erros repetitivos
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestErrorTracker:
    """Testa a classe ErrorTracker de forma isolada."""

    def test_track_retorna_false_abaixo_do_limiar(self):
        """Menos de 3 erros consecutivos não deve acionar alerta."""
        tracker = ErrorTracker(threshold=3)
        assert tracker.track("python_interpreter", "TypeError") is False
        assert tracker.track("python_interpreter", "TypeError") is False

    def test_track_retorna_true_no_limiar(self):
        """Exatamente 3 erros consecutivos deve retornar True."""
        tracker = ErrorTracker(threshold=3)
        tracker.track("python_interpreter", "TypeError")
        tracker.track("python_interpreter", "TypeError")
        result = tracker.track("python_interpreter", "TypeError")
        assert result is True

    def test_track_reseta_ao_mudar_tipo_de_erro(self):
        """Erro de tipo diferente na mesma ferramenta reseta o contador."""
        tracker = ErrorTracker(threshold=3)
        tracker.track("python_interpreter", "TypeError")
        tracker.track("python_interpreter", "TypeError")
        # Muda o tipo de erro — deve resetar
        tracker.track("python_interpreter", "FileNotFoundError")
        # Dois TypeErrors não devem acionar (contador resetado)
        tracker.track("python_interpreter", "TypeError")
        result = tracker.track("python_interpreter", "TypeError")
        assert result is False

    def test_track_reseta_ao_mudar_ferramenta(self):
        """Erros em ferramentas diferentes não se acumulam."""
        tracker = ErrorTracker(threshold=3)
        tracker.track("python_interpreter", "TypeError")
        tracker.track("python_interpreter", "TypeError")
        # Muda para outra ferramenta
        result = tracker.track("web_reader", "TypeError")
        assert result is False

    def test_track_continua_apos_limiar(self):
        """Após atingir o limiar, cada chamada subsequente continua retornando True."""
        tracker = ErrorTracker(threshold=3)
        for _ in range(3):
            tracker.track("python_interpreter", "TypeError")
        result = tracker.track("python_interpreter", "TypeError")
        assert result is True

    def test_get_message_retorna_string_descritiva(self):
        """get_message() deve retornar a mensagem de recuperação formatada."""
        tracker = ErrorTracker(threshold=3)
        msg = tracker.get_message("python_interpreter", "TypeError", 3)
        assert "python_interpreter" in msg
        assert "TypeError" in msg
        assert "3" in msg
        assert "[ATENÇÃO DO SISTEMA]" in msg


# ---------------------------------------------------------------------------
# V12.2.1 — Integração: mensagem injetada após 3 erros consecutivos
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_agent_loop_injeta_mensagem_sistema_apos_3_erros_consecutivos():
    """Após 3 TypeError consecutivos na mesma ferramenta, uma mensagem de
    sistema [ATENÇÃO DO SISTEMA] deve ser incluída nas mensagens enviadas
    ao LLM na próxima chamada."""

    tool_erro = _make_tool("python_interpreter", raises=TypeError("no module named matplotlib"))

    # 3 rounds de tool call com erro + 1 resposta final
    responses = [
        # Iteração 1: chama a ferramenta (vai falhar com TypeError)
        LLMResponse(text="", tool_calls=[ToolCall(id="c1", name="python_interpreter", arguments={"arg": "1"})]),
        # Iteração 2: chama novamente
        LLMResponse(text="", tool_calls=[ToolCall(id="c2", name="python_interpreter", arguments={"arg": "2"})]),
        # Iteração 3: chama novamente (3º erro consecutivo)
        LLMResponse(text="", tool_calls=[ToolCall(id="c3", name="python_interpreter", arguments={"arg": "3"})]),
        # Iteração 4: resposta final (o LLM agora recebe a mensagem de alerta)
        LLMResponse(text="Resultado final simplificado.", tool_calls=[]),
    ]

    provider = _make_provider(responses)

    with patch("src.llm.agent_loop.get_provider", return_value=provider):
        result = await run_agent_loop(
            prompt="Gerar gráfico",
            instruction="Você é um agente.",
            tools=[tool_erro],
            max_iterations=10,
        )

    assert result == "Resultado final simplificado."

    # Verificar que na 4ª chamada ao LLM, a mensagem de alerta está presente
    fourth_call_messages = provider.generate.call_args_list[3][1]["messages"]
    all_content = " ".join(
        m.get("content", "") or ""
        for m in fourth_call_messages
        if isinstance(m.get("content"), str)
    )
    assert "[ATENÇÃO DO SISTEMA]" in all_content, (
        "Mensagem de alerta não encontrada nas mensagens da 4ª chamada ao LLM"
    )


# ---------------------------------------------------------------------------
# V12.2.3 — Ferramenta removida após 4 falhas
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_agent_loop_remove_ferramenta_apos_4_falhas():
    """Após 4 chamadas com falha à mesma ferramenta, ela deve ser removida
    da lista de tools disponíveis nas iterações seguintes."""

    tool_erro = _make_tool("python_interpreter", raises=RuntimeError("sandbox unavailable"))

    # 4 iterações com erro + 1 resposta final sem tools
    responses = [
        LLMResponse(text="", tool_calls=[ToolCall(id=f"c{i}", name="python_interpreter", arguments={}) for _ in range(1)])
        for i in range(4)
    ]
    responses.append(LLMResponse(text="Resposta sem ferramenta.", tool_calls=[]))

    provider = _make_provider(responses)

    with patch("src.llm.agent_loop.get_provider", return_value=provider):
        result = await run_agent_loop(
            prompt="Processar dados",
            instruction="",
            tools=[tool_erro],
            max_iterations=10,
        )

    assert result == "Resposta sem ferramenta."

    # Na 5ª chamada, python_interpreter não deve estar nos tools
    fifth_call_kwargs = provider.generate.call_args_list[4][1]
    tools_passed = fifth_call_kwargs.get("tools") or []
    tool_names = [t.get("function", {}).get("name") for t in tools_passed]
    assert "python_interpreter" not in tool_names, (
        "python_interpreter deveria ter sido removido após 4 falhas"
    )


# ---------------------------------------------------------------------------
# V12.2.2 — Detecção de resposta declarativa
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_agent_loop_detecta_resposta_declarativa_e_faz_retry():
    """Uma resposta que contém apenas declarações de intenção ('Vou criar',
    'Vou fazer') sem tool calls deve ser interceptada e um retry realizado."""

    declarative_response = "Vou criar o arquivo agora e processar os dados."
    final_response = "Arquivo criado com sucesso e dados processados."

    responses = [
        # Resposta declarativa (sem tool calls, sem resultado concreto)
        LLMResponse(text=declarative_response, tool_calls=[]),
        # Retry com resposta concreta
        LLMResponse(text=final_response, tool_calls=[]),
    ]

    provider = _make_provider(responses)

    with patch("src.llm.agent_loop.get_provider", return_value=provider):
        result = await run_agent_loop(
            prompt="Processar CSV",
            instruction="",
            tools=[],
            max_iterations=10,
        )

    # O resultado final deve ser a resposta concreta
    assert result == final_response

    # O LLM deve ter sido chamado 2 vezes (1 declarativa + 1 retry)
    assert provider.generate.call_count == 2, (
        f"Esperava 2 chamadas ao LLM, recebeu {provider.generate.call_count}"
    )

    # A segunda chamada deve incluir o prompt de recuperação
    second_call_messages = provider.generate.call_args_list[1][1]["messages"]
    all_content = " ".join(
        m.get("content", "") or ""
        for m in second_call_messages
        if isinstance(m.get("content"), str)
    )
    assert "resultado concreto" in all_content.lower() or "abordagem" in all_content.lower(), (
        "Prompt de recuperação não encontrado na 2ª chamada ao LLM"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_agent_loop_nao_intercepta_resposta_concreta():
    """Respostas concretas com dados reais NÃO devem ser interceptadas."""
    concrete_response = "Aqui estão os dados processados: [1, 2, 3, 4, 5]."

    provider = _make_provider([LLMResponse(text=concrete_response, tool_calls=[])])

    with patch("src.llm.agent_loop.get_provider", return_value=provider):
        result = await run_agent_loop(
            prompt="Listar dados",
            instruction="",
            tools=[],
            max_iterations=10,
        )

    assert result == concrete_response
    # Apenas 1 chamada — não houve retry desnecessário
    assert provider.generate.call_count == 1
