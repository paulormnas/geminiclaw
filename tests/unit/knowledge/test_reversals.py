"""Reversão humana de fusão e de substituição (v17-curator-agent 8.5) e o comando ``graph revert``."""

from __future__ import annotations

import pytest

from src.cli_graph import handle_graph_command
from src.knowledge.curator_tools import CuratorToolkit
from src.knowledge.reversals import ReversalError, revert_merge, revert_substitution
from src.knowledge.service import KnowledgeService
from src.knowledge.similarity_queue import Candidate
from tests.support.controlled_embedding_provider import pair_vectors
from tests.unit.knowledge.conftest import DIM
from tests.unit.knowledge.test_curator_tools import _create, _limits, world  # noqa: F401 - fixture

pytestmark = pytest.mark.unit


def _merged(world):  # noqa: F811
    env, graph, tk, ids = world
    canonica, duplicada = graph.abordagem("ResNet-18"), graph.abordagem("resnet18")
    a, b = sorted([duplicada, canonica])
    env.queue.enqueue(Candidate(
        node_a=a, node_b=b, label_a="Abordagem", label_b="Abordagem", tipo="duplicata", score=0.95,
        entre_dominios=False, entre_projetos=False, prioridade=1.0, text_hash_a="h", text_hash_b="h",
        embedding_model="m", embedding_version="1",
    ))
    par = tk.next_similarity_batch()["pares"][0]
    assert tk.review_similarity(queue_id=par["queue_id"], decisao="confirmar", motivo="mesmo método")["ok"]
    depois = CuratorToolkit(env.store, project_id="proj1", session_id="s2", index=env.index, queue=env.queue,
                            model="m", limits=_limits())
    assert depois.merge_approaches(duplicada_id=duplicada, canonica_id=canonica, motivo="mesmo modelo")["ok"]
    return env, canonica, duplicada


def test_reverter_fusao_reativa_e_contesta_a_aresta_sem_apagar(world):  # noqa: F811
    env, canonica, duplicada = _merged(world)
    service = KnowledgeService(env.raw)
    assert service.canonical_approach(duplicada) == canonica and duplicada in service.merged_approaches(canonica)

    out = revert_merge(env.store, duplicada, "proj1")

    assert out == {"ok": True, "abordagem": duplicada, "arestas_contestadas": [canonica]}
    assert env.raw.get_node(duplicada).properties["status"] == "ativa"
    edge = next(e for e in env.raw._edges if e.rel_type == "FUNDIDA_EM")  # noqa: SLF001 - a aresta continua
    assert edge.properties["status"] == "contestada"
    fresh = KnowledgeService(env.raw)
    assert fresh.canonical_approach(duplicada) == duplicada  # volta a ser canônica de si mesma
    assert duplicada not in fresh.merged_approaches(canonica)
    with pytest.raises(ReversalError, match="não está fundida"):
        revert_merge(env.store, duplicada, "proj1")


def test_reverter_fusao_recusa_outro_projeto_ator_nao_humano_e_no_inexistente(world):  # noqa: F811
    env, canonica, duplicada = _merged(world)
    with pytest.raises(ReversalError, match="outro projeto"):
        revert_merge(env.store, duplicada, "outro-projeto")
    with pytest.raises(ReversalError, match="não encontrada"):
        revert_merge(env.store, "nao-existe", "proj1")
    from src.knowledge.provenance import Actor

    with pytest.raises(ReversalError, match="Só o pesquisador"):
        revert_merge(env.store, duplicada, "proj1", actor=Actor(kind="agente", role="curator"))
    assert env.raw.get_node(duplicada).properties["status"] == "fundida"


def test_reverter_substituicao_reativa_a_descoberta(world):  # noqa: F811
    env, graph, tk, ids = world
    env.provider.vectors["par8b"] = pair_vectors(DIM, 8, 1.0)[0]
    env.provider.vectors["par9b"] = pair_vectors(DIM, 9, 1.0)[0]
    velha = _create(tk, ids, enunciado="par8b")["id"]
    _, res3 = graph.tentativa(ids["hip"], ids["abordagem"], valor=0.82, no="C")
    nova = _create(tk, ids, enunciado="par9b", evidencia_ids=[res3], variacao_de=velha, diferenca="nova evidência")["id"]
    depois = CuratorToolkit(env.store, project_id="proj1", session_id="s2", index=env.index, queue=env.queue,
                            model="m", limits=_limits())
    assert depois.set_discovery_status(id=velha, status="substituida", motivo="superada", substituida_por=nova)["ok"]

    out = revert_substitution(env.store, velha, "proj1")

    assert out["ok"] and out["arestas_contestadas"] == [nova]
    assert env.raw.get_node(velha).properties["status"] == "ativa"
    edge = next(e for e in env.raw._edges if e.rel_type == "SUBSTITUI")  # noqa: SLF001
    assert edge.properties["status"] == "contestada"
    with pytest.raises(ReversalError, match="não está substituída"):
        revert_substitution(env.store, velha, "proj1")


def test_comando_graph_revert_pede_confirmacao_exige_terminal_e_reverte():
    from src.knowledge import projects
    from src.knowledge.graph_store import InMemoryGraphStore
    from src.knowledge.provenance import Actor

    store = InMemoryGraphStore()
    pid = projects.create_project(store, "P", "Obj", [])
    agent = Actor(kind="agente", role="researcher")
    base = {"projeto_id": pid, "sessao_id": "s1", "tipo": "algoritmo", "descricao": "D",
            "justificativa_criacao": "plano", "nos_consultados": []}
    canon = store.create_node("Abordagem", {**base, "nome": "ResNet-18"}, actor=agent)
    dup = store.create_node("Abordagem", {**base, "nome": "resnet18"}, actor=agent)
    store.create_edge(dup, "FUNDIDA_EM", canon, {}, actor=agent)
    store.update_node(dup, {"status": "fundida"}, actor=projects.PESQUISADOR)
    out: list[str] = []
    argv = ["revert", "merge", dup, "--project", pid]

    assert handle_graph_command(argv, store, output_fn=out.append, input_fn=lambda _p: "s", interactive=False) == 1
    assert "terminal interativo" in out[-1] and store.get_node(dup).properties["status"] == "fundida"

    assert handle_graph_command(argv, store, output_fn=out.append, input_fn=lambda _p: "n", interactive=True) == 0
    assert "cancelada" in out[-1] and store.get_node(dup).properties["status"] == "fundida"

    assert handle_graph_command(argv, store, output_fn=out.append, input_fn=lambda _p: "s", interactive=True) == 0
    assert "Revertida" in out[-1] and store.get_node(dup).properties["status"] == "ativa"
    assert handle_graph_command(argv, store, output_fn=out.append, input_fn=lambda _p: "s", interactive=True) == 1
    assert "não está fundida" in out[-1]


def test_prompt_da_decisao_reservada_nao_corta_a_descricao_em_400():
    from src.cli_graph import _DECISION_PROMPT_CHARS

    assert _DECISION_PROMPT_CHARS >= 4000
