"""``v18.7-hypothesis-linking`` tarefa 10.2: um ciclo com preparação, dois testes e uma referência, com Apache AGE real.

Um teste declara a hipótese (``h1``) e o outro não (hipótese do sistema). Confere ``PREPARA``, ``TESTA``,
``REFERENCIA_DE``, ``origem = "sistema"``, a reabertura (propriedades do abandono limpas) e o evento
``hypothesis_cycle``. Pulado quando não há AGE de teste acessível (ver ``conftest.py``). Usa ``projeto_id`` e métrica
únicos e remove só o que criou.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from src.knowledge.graph_store import AgeGraphStore
from src.knowledge.hypotheses import PlanExtras, split_plan
from src.knowledge.hypothesis_cycle import ORQUESTRADOR
from src.knowledge.ingestion import SessionContext, SubtaskInput, ingest_session_start, ingest_subtask
from src.orchestration.exploration import ExplorationSession
from tests.integration.knowledge.test_hypothesis_closure_age import _cleanup
from tests.support.curator_graph import CuratorGraph
from tests.support.linking_world import sub, to_task

pytestmark = pytest.mark.integration


def _write(session_dir: Path, name: str, metrics: dict) -> None:
    folder = session_dir / name
    folder.mkdir(parents=True)
    (folder / "metrics.json").write_text(json.dumps({"task_name": name, "seed": 1, "metrics": metrics}))


def _out(store: AgeGraphStore, node_id: str, rel: str) -> set[str]:
    graph = store.neighbors(node_id, [rel], direction="out", depth=1)
    return {e.dst_id for e in graph.edges if e.src_id == node_id and e.rel_type == rel}


def test_ciclo_com_preparacao_dois_testes_e_referencia(age_store: AgeGraphStore, tmp_path: Path):
    suffix = uuid.uuid4().hex[:8]
    metric = f"acc_{suffix}"
    project_id, session_id = str(uuid.uuid4()), f"sess-{suffix}"  # ``get_active_problem`` exige UUID
    try:
        graph = CuratorGraph(age_store, project_id, session_id).setup_project(metrica=metric, delta_min=0.01)
        ctx = SessionContext(project_id, session_id, "auto", "2026-10-16T10:00:00+00:00", f"no-{suffix}")
        ingest_session_start(age_store, ctx)
        events: list[tuple[str, dict]] = []
        session = ExplorationSession(
            lambda: age_store, ctx, tmp_path, mode="auto", telemetry=lambda kind, data: events.append((kind, data))
        )
        algo = {"nome": f"rf-{suffix}", "tipo": "algoritmo"}
        plan = [
            sub("preprocessar_dados", criteria=("proporção de nulos <= 0",)),
            sub("baseline", task_type="validation", papel="referencia", criteria=None, depends_on=["preprocessar_dados"]),
            sub("treinar_knn", hypothesis_ref="h1", depends_on=["preprocessar_dados"],
                approach={"nome": f"knn-{suffix}", "tipo": "algoritmo"}),
            sub("treinar_rf", approach=algo, depends_on=["preprocessar_dados"]),
        ]
        items, extras = split_plan({
            "hipoteses": [{"ref": "h1", "enunciado": f"O kNN {suffix} supera a referência", "justificativa": "J"}],
            "decisoes": [], "respostas_sugestoes": [], "subtarefas": plan,
        })
        tasks = [to_task(d) for d in items]
        outcome = session.prepare_cycle(tasks, extras, done=set())
        assert outcome.dropped == {}
        h1 = outcome.report.ref_map["h1"]
        by_name = {t.task_name: t for t in tasks}
        hs = by_name["treinar_rf"].hypothesis_id
        assert age_store.get_node(hs).properties["origem"] == "sistema"
        assert age_store.get_node(hs).properties["chave_estruturada"].split("|")[0] == graph.problema

        session_dir = tmp_path / session_id
        experiments: dict[str, str] = {}
        for task in tasks:
            _write(session_dir, task.task_name, {metric: 0.62 if task.task_name == "baseline" else 0.9})
            experiments[task.task_name] = ingest_subtask(
                age_store, ctx, session_dir,
                SubtaskInput(
                    task_name=task.task_name, subtask_id=f"{suffix}-{task.task_name}", agent_id="developer",
                    task_type=task.task_type, approach=task.approach, review_status="pass", review_verified=True,
                    hypothesis_id=task.hypothesis_id or None, papel=task.papel_decidido,
                    prepara_ids=task.prepara_ids if task.papel_decidido == "preparacao" else None,
                ),
            )
        assert _out(age_store, experiments["preprocessar_dados"], "PREPARA") == {h1, hs}
        assert _out(age_store, experiments["treinar_knn"], "TESTA") == {h1}
        assert _out(age_store, experiments["treinar_rf"], "TESTA") == {hs}
        assert age_store.get_node(experiments["baseline"]).properties["papel"] == "referencia"
        results = age_store.neighbors(experiments["baseline"], ["PRODUZIU"], direction="out", depth=1).nodes
        assert any(_out(age_store, r.id, "REFERENCIA_DE") == {graph.problema} for r in results)
        event = [p for k, p in events if k == "hypothesis_cycle"][-1]
        assert event["papeis"] == {"teste": 2, "preparacao": 1, "referencia": 1}
        assert event["hipoteses_sistema_criadas"] == 1 and event["retiradas_por_motivo"] == {}

        # reabertura: o sistema abandona a hipótese e a mesma chave a reabre; as propriedades do abandono são limpas
        age_store.update_node(
            hs, {"status": "abandonada", "abandonada_por": "sistema", "motivo_abandono": "subtarefa_retirada"},
            actor=ORQUESTRADOR,
        )
        session.prepare_cycle([to_task(sub("treinar_rf", approach=algo))], PlanExtras(), done=set())
        reopened = age_store.get_node(hs).properties
        assert reopened["status"] == "em_teste" and not reopened.get("abandonada_por")
        assert [p for k, p in events if k == "hipotese_derivada"][-1]["reaberta"] is True
    finally:
        _cleanup(project_id)
