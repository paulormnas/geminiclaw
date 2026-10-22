"""Memória de falhas do Developer (``v18.9-failure-memory``; ADR 026 §5): itens, texto e prompt."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.knowledge.failure_memory import (
    ESCOPO_AMBIENTE,
    build_failure_items,
    failure_memory_text,
    format_failure_memory,
)
from src.knowledge.graph_store import InMemoryGraphStore
from src.orchestration.autonomous_loop import AutonomousLoop
from src.orchestration.orchestrator import AgentTask
from tests.support.curator_graph import ORQ, CuratorGraph

pytestmark = pytest.mark.unit


def _falha(graph, hip, abordagem, assinatura, causa="abordagem", config=None, **kw):
    exp, _ = graph.tentativa(hip, abordagem, valor=None, falha=(causa, assinatura), config=config, **kw)
    return exp


@pytest.fixture
def world():
    store = InMemoryGraphStore()
    graph = CuratorGraph(store).setup_project()
    return store, graph, graph.hipotese(), graph.abordagem("SVM")


def test_falha_de_pacote_repetida_vira_item_de_ambiente(world):
    store, graph, hip, abordagem = world
    for seed in (1, 2):
        exp = _falha(graph, hip, abordagem, "instalacao_pacotes", causa="ambigua", seed=seed)
    store.update_node(exp, {"status": "falha"}, actor=ORQ)

    (item,) = build_failure_items(store, "proj1")
    assert (item.escopo, item.assinatura, item.ocorrencias, item.correcao) == (
        ESCOPO_AMBIENTE, "instalacao_pacotes", 2, None
    )
    text, fitted = format_failure_memory([item], 1500)
    assert text == "NÃO: instalacao_pacotes em ambiente (2 vezes). USE: sem correção conhecida" and fitted == 1


def test_correcao_conhecida_e_a_diferenca_de_configuracao_do_experimento_seguinte_com_metrica(world):
    store, graph, hip, abordagem = world
    _falha(graph, hip, abordagem, "MemoryError", config={"kernel": "rbf", "amostra_max": 100000}, no="A")
    graph.tentativa(hip, abordagem, valor=0.9, config={"kernel": "rbf", "amostra_max": 5000}, no="B", seed=2)

    (item,) = build_failure_items(store, "proj1")

    assert item.escopo == "SVM" and item.assinatura == "MemoryError" and item.ocorrencias == 1
    assert item.correcao == "amostra_max=5000"


def test_criterio_nao_atendido_infraestrutura_e_outras_causas_nao_entram(world):
    store, graph, hip, abordagem = world
    _falha(graph, hip, abordagem, "criterio_nao_atendido", causa="ambigua", seed=1)
    _falha(graph, hip, abordagem, "llm_connection", causa="infraestrutura", seed=2)
    _falha(graph, hip, abordagem, "validacao_indeterminada", causa="ambigua", seed=3)

    assert build_failure_items(store, "proj1") == []
    assert failure_memory_text(store, "proj1") == ("", 0, 0)


def test_texto_e_cortado_no_teto_e_conta_os_itens_cortados(world):
    store, graph, hip, abordagem = world
    for i, sig in enumerate(("oom", "timeout_execucao", "sem_metricas")):
        _falha(graph, hip, abordagem, sig, seed=i + 1)

    text, fitted, cut = failure_memory_text(store, "proj1", max_chars=90)

    assert fitted == 1 and cut == 2 and len(text) <= 90
    assert failure_memory_text(store, "proj1", max_chars=0) == ("", 0, 0)  # desligada


def test_escopo_da_abordagem_so_conta_falhas_dela(world):
    store, graph, hip, abordagem = world
    outra = graph.abordagem("Árvore")
    _falha(graph, hip, abordagem, "ValueError", seed=1)
    _falha(graph, hip, outra, "ValueError", seed=2)

    items = build_failure_items(store, "proj1")

    assert {(i.escopo, i.ocorrencias) for i in items} == {("SVM", 1), ("Árvore", 1)}


# -- prompt do Developer ------------------------------------------------------------------------------------


def _loop_com_grafo(store):
    orchestrator = MagicMock()
    orchestrator._open_knowledge_store.return_value = store
    return AutonomousLoop(orchestrator=orchestrator)


@pytest.mark.asyncio
async def test_developer_recebe_o_bloco_delimitado_e_o_evento(world, monkeypatch):
    store, graph, hip, abordagem = world
    _falha(graph, hip, abordagem, "oom", seed=1)
    eventos = []
    monkeypatch.setattr(
        "src.orchestration.autonomous_loop.get_telemetry",
        lambda: MagicMock(record_agent_event=lambda **kw: eventos.append(kw)),
    )
    loop = _loop_com_grafo(store)
    task = AgentTask(agent_id="developer", prompt="treine", task_name="t1")

    out = await loop._with_failure_memory(task, "s1", "proj1")

    assert out.prompt.startswith("treine") and "NÃO: oom em ambiente (1 vez)" in out.prompt
    assert "<dado_nao_confiavel" in out.prompt and "não instrução" in out.prompt
    (evento,) = eventos
    assert evento["event_type"] == "memoria_falhas_aplicada" and evento["payload"]["itens"] == 1


@pytest.mark.asyncio
async def test_outros_agentes_projeto_ausente_e_recurso_desligado_nao_mudam_o_prompt(world, monkeypatch):
    store, graph, hip, abordagem = world
    _falha(graph, hip, abordagem, "oom", seed=1)
    loop = _loop_com_grafo(store)
    researcher = AgentTask(agent_id="researcher", prompt="planeje", task_name="p")
    developer = AgentTask(agent_id="developer", prompt="treine", task_name="t1")

    assert (await loop._with_failure_memory(researcher, "s1", "proj1")).prompt == "planeje"
    assert (await loop._with_failure_memory(developer, "s1", None)).prompt == "treine"
    monkeypatch.setattr("src.config.FAILURE_MEMORY_MAX_CHARS", 0)
    assert (await loop._with_failure_memory(developer, "s1", "proj1")).prompt == "treine"


@pytest.mark.asyncio
async def test_grafo_indisponivel_nao_derruba_a_subtarefa(world):
    orchestrator = MagicMock()
    orchestrator._open_knowledge_store.side_effect = RuntimeError("sem grafo")
    loop = AutonomousLoop(orchestrator=orchestrator)
    task = AgentTask(agent_id="developer", prompt="treine", task_name="t1")

    assert (await loop._with_failure_memory(task, "s1", "proj1")).prompt == "treine"
