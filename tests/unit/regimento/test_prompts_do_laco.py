"""Prompts nas chamadas reais do laço do agente: formato do plano uma vez e system do Developer em toda chamada."""

from unittest.mock import patch

import pytest

from src.agents.regimento import encerrar_sessao, iniciar_sessao
from src.llm.agent_loop import run_agent_loop
from src.llm.base import LLMResponse, ToolCall
from src.utils.egress_fragments import dumps_messages
from tests.support.fake_recording_provider import FakeRecordingProvider
from tests.support.hypothesis_world import HypothesisWorld

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_formato_do_plano_aparece_uma_vez_e_o_bloco_de_exploracao_so_leva_dado(tmp_path):
    """Scenario: Formato uma vez."""
    from src.agents.researcher.agent import root_agent
    from src.agents.subtask_contract import build_researcher_plan_context
    from src.orchestration.exploration import ExplorationSession

    world = HypothesisWorld()
    session = ExplorationSession(lambda: world.store, world.ctx, tmp_path, mode="auto")
    bloco = session.prompt_block()
    assert "FORMATO DO PLANO" not in bloco and "<dado_nao_confiavel" in bloco

    prompt = build_researcher_plan_context(
        original_task="Classificar amostras", project_block="", mode="explore", plan_text="[]",
        feedback="ciclo 1 concluído", exploration_block=bloco,
    )
    provider = FakeRecordingProvider(script=['{"subtarefas": []}'])
    _, token = iniciar_sessao("auto", "limiar")
    try:
        with patch("src.llm.agent_loop.get_provider", return_value=provider):
            await run_agent_loop(prompt=prompt, instruction=root_agent.instruction, tools=[])
    finally:
        encerrar_sessao(token)

    chamada = provider.calls[0]
    assert (chamada.system or "").count("FORMATO DO PLANO") == 1
    mensagens = dumps_messages([m for m in chamada.messages if m.get("role") != "system"])  # a cópia ``system`` é a mesma
    assert "FORMATO DO PLANO" not in mensagens


@pytest.mark.asyncio
async def test_developer_reenviado_a_cada_chamada_com_o_mesmo_system():
    """Scenario: Developer reenviado a cada chamada."""
    from src.agents.developer.agent import AGENT_INSTRUCTION, root_agent

    def passo(a: str = "") -> str:
        return "ok"

    passo.__name__ = "passo"
    provider = FakeRecordingProvider(script=[
        LLMResponse(text="1", tool_calls=[ToolCall(id="c1", name="passo", arguments={})]),
        LLMResponse(text="2", tool_calls=[ToolCall(id="c2", name="passo", arguments={})]),
        LLMResponse(text="pronto", tool_calls=[]),
    ])
    _, token = iniciar_sessao("auto", "limiar")
    try:
        with patch("src.llm.agent_loop.get_provider", return_value=provider):
            await run_agent_loop(prompt="Faça.", instruction=root_agent.instruction, tools=[passo])
    finally:
        encerrar_sessao(token)

    assert len(provider.calls) == 3
    sistemas = {c.system for c in provider.calls}
    assert len(sistemas) == 1
    (system,) = sistemas
    assert system.startswith(AGENT_INSTRUCTION)
    assert "REGIMENTO DA PESQUISA (versão 1; objetivo limiar; modo auto)" in system


def test_prompt_do_developer():
    """Scenario: Developer."""
    from src.agents.developer.agent import AGENT_INSTRUCTION

    assert "contrato" in AGENT_INSTRUCTION and "Validator" in AGENT_INSTRUCTION and "/inputs/" in AGENT_INSTRUCTION
    assert "input_snapshot/" not in AGENT_INSTRUCTION and "input_context/" not in AGENT_INSTRUCTION
    assert "seed do enunciado" in AGENT_INSTRUCTION and "senão use 42" in AGENT_INSTRUCTION
    assert "params.json" in AGENT_INSTRUCTION
