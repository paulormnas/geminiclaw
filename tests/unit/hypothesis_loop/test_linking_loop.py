"""``v18.7-hypothesis-linking``: o laço com o plano de passos finos da bateria V18.6 e o checkpoint da origem."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.orchestration.exploration import ExplorationSession
from src.session.continuity import Checkpoint, CheckpointError
from tests.support.exploration_world import LoopHarness, hyp, plan
from tests.support.linking_world import ACURACIA, sub

RF = {"nome": "random forest", "tipo": "algoritmo"}

pytestmark = pytest.mark.unit


def _fine_plan() -> dict:
    return plan(
        [
            sub("eda", task_type="eda", criteria=None, approach={"nome": "análise exploratória", "tipo": "algoritmo"}),
            sub("preprocessar_dados", criteria=("proporção de nulos <= 0",)),
            sub("baseline_majoritario", task_type="validation", papel="referencia", criteria=None,
                depends_on=["preprocessar_dados"]),
            sub("treinar_knn", hypothesis_ref="h1", criteria=("acurácia no teste >= 0.9",),
                depends_on=["preprocessar_dados"]),
            sub("treinar_rf", approach=RF, depends_on=["preprocessar_dados"]),
        ],
        [hyp("h1")],
    )


@pytest.mark.asyncio
async def test_plano_de_passos_finos_executa_inteiro(tmp_path):
    """Regressão da bateria V18.6: nenhuma retirada e todas as subtarefas no DAG executado."""
    events: list[tuple[str, dict]] = []
    h = LoopHarness(tmp_path, plans=[_fine_plan(), _fine_plan()],
                    world_kw={"metrica": "acuracia", "sinonimos": ACURACIA})
    real = ExplorationSession.__init__

    def init(self, *a, **kw):
        kw["telemetry"] = lambda t, p: events.append((t, p))
        real(self, *a, **kw)

    with patch.object(ExplorationSession, "__init__", init):
        await h.run()
    assert sorted(h.ran) == ["baseline_majoritario", "eda", "preprocessar_dados", "treinar_knn", "treinar_rf"]
    cycle = next(p for t, p in events if t == "hypothesis_cycle")
    assert cycle["retiradas_por_motivo"] == {} and cycle["subtarefas_retiradas"] == 0
    origins = [n.properties["origem"] for n in h.hypotheses()]
    assert sorted(origins) == ["researcher", "sistema"]
    # a origem da hipótese do sistema foi ao checkpoint junto com o plano
    assert list(h.checkpoint().hipoteses_do_sistema.values()) == [["treinar_rf"]]


@pytest.mark.asyncio
async def test_papel_e_ligacoes_gravados_no_grafo_pelo_laco(tmp_path):
    """O laço passa o papel decidido e as hipóteses servidas à ingestão: ``PREPARA``, ``TESTA`` e ``papel`` no grafo."""
    h = LoopHarness(tmp_path, plans=[_fine_plan(), _fine_plan()],
                    world_kw={"metrica": "acuracia", "sinonimos": ACURACIA})
    await h.run()
    store = h.w.store

    def out(node_id: str, rel: str) -> set[str]:
        graph = store.neighbors(node_id, [rel], direction="out", depth=1)
        return {e.dst_id for e in graph.edges if e.src_id == node_id and e.rel_type == rel}

    by_task = {n.properties["caminho_artefatos"].rsplit("/", 1)[-1]: n
               for n in store.find_nodes("Experimento", {"projeto_id": h.w.pid}, limit=50)}
    hs = next(n.id for n in h.hypotheses() if n.properties["origem"] == "sistema")
    h1 = next(n.id for n in h.hypotheses() if n.properties["origem"] == "researcher")
    papel = {name: node.properties.get("papel") for name, node in by_task.items()}
    assert papel == {"eda": "preparacao", "preprocessar_dados": "preparacao", "baseline_majoritario": "referencia",
                     "treinar_knn": "teste", "treinar_rf": "teste"}
    assert out(by_task["eda"].id, "PREPARA") == {h.w.problem.id}
    assert out(by_task["preprocessar_dados"].id, "PREPARA") == {h1, hs}
    assert out(by_task["treinar_knn"].id, "TESTA") == {h1} and out(by_task["treinar_rf"].id, "TESTA") == {hs}
    assert out(by_task["baseline_majoritario"].id, "TESTA") == set()


def test_checkpoint_guarda_e_valida_a_origem_das_hipoteses_do_sistema():
    cp = Checkpoint(session_id="s1", hipoteses_do_sistema={"hs-1": ["treinar_rf"]})
    again = Checkpoint.from_dict(json.loads(json.dumps(cp.to_dict())), expected_session_id="s1")
    assert again.hipoteses_do_sistema == {"hs-1": ["treinar_rf"]}
    legacy = cp.to_dict()
    legacy.pop("hipoteses_do_sistema")  # checkpoint anterior à V18.7
    assert Checkpoint.from_dict(legacy, expected_session_id="s1").hipoteses_do_sistema == {}
    bad = cp.to_dict()
    bad["hipoteses_do_sistema"] = {"hs 1 inválido": ["x"]}
    with pytest.raises(CheckpointError):
        Checkpoint.from_dict(bad, expected_session_id="s1")


def test_restaura_a_origem_da_retomada(tmp_path):
    from tests.support.linking_world import LinkingCycle

    c = LinkingCycle(tmp_path)
    c.session.restore_system_origin({"hs-1": ["treinar_rf"], "hs-2": []})
    assert c.session.system_origin == {"hs-1": {"treinar_rf"}}
    assert c.session.system_origin_snapshot() == {"hs-1": ["treinar_rf"]}
