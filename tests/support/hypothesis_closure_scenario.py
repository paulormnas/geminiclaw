"""Sessão simulada de ``v18.6-hypothesis-closure``: uma hipótese refutada e outra validada, pela regra de réplicas.

Roda sobre qualquer ``GraphStore`` (em memória nos testes unitários; Apache AGE real no teste de integração). A
refutada recebe um resultado negativo pela ingestão (``review_outcome = resultado_negativo``) mais duas tentativas
fracas; a validada recebe seis tentativas acima do alvo. Devolve os nós para as asserções.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.knowledge.graph_store import GraphStore
from src.knowledge.hypothesis_cycle import HypothesisCycle
from src.knowledge.ingestion import SessionContext, SubtaskInput, ingest_session_start, ingest_subtask
from src.knowledge.service import KnowledgeService
from tests.support.curator_graph import ORQ, PESQUISADOR, CuratorGraph


def run_closure_scenario(store: GraphStore, session_root: Path, suffix: str) -> dict[str, Any]:
    """Monta o projeto, ingere as tentativas, recalcula as contagens e fecha as hipóteses pela regra de réplicas."""
    metric = "accuracy"  # nome conhecido do revisor; o vocabulário de um banco compartilhado pode ter outro nó
    project_id, session_id = f"proj-{suffix}", f"sess-{suffix}"
    graph = CuratorGraph(store, project_id, session_id).setup_project(metrica=metric, delta_min=0.01)
    store.update_node(
        graph.problema,
        {"criterio_sucesso": {"metrica": metric, "metrica_id": graph.metrica, "delta_min": 0.01, "alvo": 0.95}},
        actor=PESQUISADOR,
    )
    ctx = SessionContext(project_id, session_id, "auto", "2026-10-13T10:00:00+00:00", f"no-{suffix}")
    ingest_session_start(store, ctx)
    refuted, validated = graph.hipotese("RL atinge 0,95"), graph.hipotese("RF atinge 0,95")

    session_dir = session_root / session_id
    folder = session_dir / "treinar_rl"
    folder.mkdir(parents=True)
    (folder / "params.json").write_text(json.dumps({"task_name": "treinar_rl", "seed": 7, "parameters": {"C": 1}}))
    (folder / "metrics.json").write_text(json.dumps(
        {"task_name": "treinar_rl", "seed": 7, "parameters": {"C": 1}, "metrics": {"test_accuracy": 0.933}}
    ))
    exp_id = ingest_subtask(
        store, ctx, session_dir,
        SubtaskInput(
            task_name="treinar_rl", subtask_id=f"sub-{suffix}", agent_id="developer", review_status="fail",
            review_verified=True, review_outcome="resultado_negativo", hypothesis_id=refuted,
            validation_criteria=["acurácia no teste >= 0.95"],
        ),
    )
    # Num banco compartilhado a resolução de "accuracy" pode cair em outro nó Metrica: liga à métrica do Problema.
    for resultado in store.find_nodes("Resultado", {"projeto_id": project_id, "nome_original": "test_accuracy"}):
        linked = store.neighbors(resultado.id, ["MEDE"], direction="out", depth=1).nodes
        if not any(n.id == graph.metrica for n in linked):
            store.create_edge(resultado.id, "MEDE", graph.metrica, {}, actor=ORQ)
    for n, valor in enumerate((0.60, 0.55, 0.50, 0.58, 0.52, 0.57)):
        graph.tentativa(refuted, None, valor=valor, baseline=None, no=f"R{n}", sessao=f"r{n}-{suffix}", seed=n + 1)
    for n, valor in enumerate((0.97, 0.96, 0.98, 0.99, 0.96, 0.97)):
        graph.tentativa(validated, None, valor=valor, baseline=None, no=f"V{n}", sessao=f"v{n}-{suffix}", seed=n + 1)

    service = KnowledgeService(store)
    facts = {hid: service.recompute_hypothesis(hid) for hid in (refuted, validated)}
    changed = HypothesisCycle(store, project_id=project_id, session_id=session_id).sync_statuses([refuted, validated])
    return {"refuted": refuted, "validated": validated, "experiment": exp_id, "facts": facts,
            "changed": changed, "graph": graph}


__all__ = ["run_closure_scenario", "ORQ"]
