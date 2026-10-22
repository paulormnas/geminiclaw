"""Migração para os registros de resultado (``scripts/migrate_v18_9_result_records.py``)."""

from __future__ import annotations

import pytest

from scripts.migrate_v18_9_result_records import migrate
from src.knowledge.graph_store import InMemoryGraphStore
from tests.support.curator_graph import ORQ, CuratorGraph

pytestmark = pytest.mark.unit


def _world():
    store = InMemoryGraphStore()
    graph = CuratorGraph(store).setup_project()
    hip, abordagem = graph.hipotese(), graph.abordagem()
    graph.tentativa(hip, abordagem, valor=0.80, seed=1)
    graph.tentativa(hip, abordagem, valor=0.82, seed=2)
    return store, graph, hip, abordagem


def test_simulacao_nao_escreve_nada():
    store, graph, hip, abordagem = _world()
    nos_antes, arestas_antes = len(store._nodes), len(store._edges)  # noqa: SLF001

    report = migrate(store, apply=False)

    assert report.aplicado is False and report.hipoteses == 1 and report.abordagens == 1
    assert len(store._nodes) == nos_antes and len(store._edges) == arestas_antes  # noqa: SLF001
    assert "n_atingiu_alvo" not in store.get_node(hip).properties


def test_aplicar_cria_registros_contagens_e_atalhos_e_e_idempotente():
    store, graph, hip, abordagem = _world()

    report = migrate(store, apply=True)

    assert report.registros == 1
    assert store.get_node(hip).properties["n_atingiu_alvo"] == 2
    (registro,) = store.find_nodes("RegistroResultado", {})
    assert registro.properties["n_atingiu_alvo"] == 2
    funcionou = [e for e in store._edges if e.rel_type == "FUNCIONOU_PARA"]  # noqa: SLF001
    assert len(funcionou) == 1 and funcionou[0].properties["registro_id"] == registro.id

    nos, arestas = len(store._nodes), len(store._edges)  # noqa: SLF001
    migrate(store, apply=True)
    assert (len(store._nodes), len(store._edges)) == (nos, arestas)  # noqa: SLF001


def test_atalho_antigo_sem_registro_e_contestado():
    store, graph, hip, abordagem = _world()
    sem_tentativas = graph.abordagem("Sem tentativas")
    store.create_edge(
        sem_tentativas, "FUNCIONOU_PARA", graph.problema, {"metrica": "r2", "melhor_valor": 0.9, "n_exp": 3}, actor=ORQ
    )

    simulado = migrate(store, apply=False)
    assert simulado.atalhos_contestados == 1
    (antes,) = [e for e in store._edges if e.rel_type == "FUNCIONOU_PARA" and e.src_id == sem_tentativas]  # noqa: SLF001
    assert antes.properties["status"] == "confirmada"

    migrate(store, apply=True)
    (depois,) = [e for e in store._edges if e.rel_type == "FUNCIONOU_PARA" and e.src_id == sem_tentativas]  # noqa: SLF001
    assert depois.properties["status"] == "contestada"
