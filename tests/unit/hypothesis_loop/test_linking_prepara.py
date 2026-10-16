"""``v18.7-hypothesis-linking``: preparação ligada às hipóteses que serve e referência do Problema (spec ``hypothesis-loop``)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.knowledge.ingestion import FactIngestor, SubtaskInput, ingest_subtask
from tests.support.hypothesis_world import ORQ
from tests.support.linking_world import LinkingCycle, sub

pytestmark = pytest.mark.unit


def _write_metrics(session_dir: Path, name: str, metrics: dict) -> None:
    folder = session_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "metrics.json").write_text(
        json.dumps({"task_name": name, "seed": 1, "parameters": {}, "metrics": metrics}), encoding="utf-8"
    )


def _out(w, node_id: str, rel: str):
    sub_graph = w.store.neighbors(node_id, [rel], direction="out", depth=1)
    by_id = {n.id: n for n in sub_graph.nodes}
    return [(by_id[e.dst_id], e) for e in sub_graph.edges if e.src_id == node_id and e.rel_type == rel]


def _ingest(cycle: LinkingCycle, tmp_path: Path, name: str, metrics: dict | None = None, **over) -> str:
    """Ingere a subtarefa como o laço faz: papel e ``prepara_ids`` do ciclo."""
    task = cycle.tasks[name]
    if metrics is not None:
        _write_metrics(tmp_path / "out", name, metrics)
    sub_input = SubtaskInput(
        task_name=name, subtask_id=task.subtask_id, agent_id="developer", task_type=task.task_type,
        agent_status="success", review_status="pass", review_verified=True,
        validation_criteria=list(task.validation_criteria), hypothesis_id=task.hypothesis_id or None,
        papel=task.papel_decidido or None,
        prepara_ids=task.prepara_ids if task.papel_decidido == "preparacao" else None, **over,
    )
    exp = ingest_subtask(cycle.w.store, cycle.w.ctx, tmp_path / "out", sub_input)
    assert exp is not None
    return exp


def test_preparacao_de_duas_hipoteses(tmp_path):
    """Scenario: Preparação de duas hipóteses (``h3`` entra por dependência transitiva)."""
    c = LinkingCycle(tmp_path)
    outcome = c.run(
        [
            sub("preprocessar_dados", criteria=("proporção de nulos <= 0",)),
            sub("treinar_knn", hypothesis_ref="h1", depends_on=["preprocessar_dados"]),
            sub("treinar_rf", hypothesis_ref="h2", depends_on=["preprocessar_dados"]),
            sub("comparar_modelos", hypothesis_ref="h3", depends_on=["treinar_knn"]),
        ],
        [{"ref": r, "enunciado": f"Hipótese {r} bem distinta {i}", "justificativa": "J"}
         for i, r in enumerate(("h1", "h2", "h3"))],
    )
    assert outcome.dropped == {}
    pre = c.tasks["preprocessar_dados"]
    ids = outcome.report.ref_map
    assert sorted(pre.prepara_ids) == sorted(ids.values())
    exp = _ingest(c, tmp_path, "preprocessar_dados", {"proporcao_nulos": 0.0})
    targets = {n.id: e for n, e in _out(c.w, exp, "PREPARA")}
    assert set(targets) == set(ids.values())
    assert all(e.properties["origem"] == "derivado" for e in targets.values())


def test_preparacao_sem_hipotese_dependente_liga_ao_problema(tmp_path):
    """Scenario: Preparação sem hipótese dependente (e nenhuma ``Hipotese`` nasce do campo ``hypothesis``)."""
    c = LinkingCycle(tmp_path)
    c.run([sub("eda", task_type="eda", criteria=None, hypothesis="A EDA revela estrutura nos dados")])
    assert c.tasks["eda"].prepara_ids == []
    exp = _ingest(c, tmp_path, "eda", {"n_linhas": 100.0})
    (target, _), = _out(c.w, exp, "PREPARA")
    assert target.label == "Problema" and target.id == c.w.problem.id
    assert c.w.store.find_nodes("Hipotese", {"projeto_id": c.w.pid}, limit=10) == []
    assert _out(c.w, exp, "TESTA") == []


def test_ligacao_incremental(tmp_path):
    """Scenario: Ligação incremental (o ``Experimento`` existente ganha ``PREPARA``; nenhum novo é criado)."""
    c = LinkingCycle(tmp_path)
    first = c.run(
        [sub("preprocessar_dados", criteria=("proporção de nulos <= 0",)),
         sub("treinar_knn", hypothesis_ref="h1", depends_on=["preprocessar_dados"])],
        [{"ref": "h1", "enunciado": "kNN supera a referência", "justificativa": "J"}],
    )
    exp = _ingest(c, tmp_path, "preprocessar_dados", {"proporcao_nulos": 0.0})
    h1 = first.report.ref_map["h1"]
    assert {n.id for n, _ in _out(c.w, exp, "PREPARA")} == {h1}
    c.finish(first, "preprocessar_dados")
    second = c.run(
        [sub("preprocessar_dados", criteria=("proporção de nulos <= 0",)),
         sub("treinar_svm", hypothesis_ref="h4", depends_on=["preprocessar_dados"])],
        [{"ref": "h4", "enunciado": "SVM com kernel RBF melhora tudo", "justificativa": "J"}],
        done={"preprocessar_dados"},
    )
    h4 = second.report.ref_map["h4"]
    assert second.preparation_links == {"preprocessar_dados": [h4]}
    ingestor = FactIngestor(lambda: c.w.store, c.w.ctx, tmp_path / "out")
    assert ingestor.link_preparation(c.done_tasks["preprocessar_dados"].subtask_id, [h4]) is True
    assert {n.id for n, _ in _out(c.w, exp, "PREPARA")} == {h1, h4}
    assert len(c.w.store.find_nodes("Experimento", {"projeto_id": c.w.pid}, limit=10)) == 1


def test_ligacao_incremental_sem_experimento_registra_o_evento(tmp_path):
    """Preparação sem ``Experimento`` (sem código nem métricas): nada é escrito e o evento é registrado."""
    c = LinkingCycle(tmp_path)
    ingestor = FactIngestor(lambda: c.w.store, c.w.ctx, tmp_path / "out")
    seen = []
    with patch("src.observability.telemetry.get_telemetry") as telemetry:
        telemetry.return_value.record_agent_event.side_effect = lambda **kw: seen.append(kw["event_type"])
        ingestor.link_preparation("sem-experimento", ["h-1"])
    assert seen == ["preparacao_sem_experimento"]


def test_dag_invalido_nao_chega_a_governanca(tmp_path):
    """Scenario: DAG inválido não chega à governança (``prepare_cycle`` não é chamado; feedback cita o grafo)."""
    import asyncio

    from src.orchestration.exploration import ExplorationSession
    from tests.support.exploration_world import LoopHarness, hyp, plan, task

    h = LoopHarness(tmp_path)
    ciclico = plan([task("a", "h1", depends_on=["b"]), task("b", "h1", depends_on=["a"])], [hyp("h1")])
    h.plans = [ciclico, plan([task("a", "h1")], [hyp("h1")])]
    with patch.object(ExplorationSession, "prepare_cycle", autospec=True,
                      side_effect=ExplorationSession.prepare_cycle) as prepare:
        asyncio.run(h.run())
    # o primeiro plano (cíclico) nunca chegou ao prepare_cycle; o segundo, sim
    first_calls = [c for c in prepare.call_args_list if {t.task_name for t in c.args[1]} == {"a", "b"}]
    assert first_calls == []
    assert any("Grafo de dependências inválido" in p for p in h.planner_prompts[1:])


def test_baseline_declarado_registra_a_referencia(tmp_path):
    """Scenario: Baseline declarado (só o ``Resultado`` de M recebe ``REFERENCIA_DE``; o veredito não muda)."""
    c = LinkingCycle(tmp_path)
    h1 = c.w.hypothesis("H1", status="em_teste")
    c.w.attempt(h1, 0.85)
    before = c.w.graph  # noqa: F841
    c.run([sub("baseline_majoritario", task_type="validation", papel="referencia", criteria=None)])
    assert c.tasks["baseline_majoritario"].papel_decidido == "referencia"
    verdict_before = c.w.store.get_node(h1).properties.get("veredito")
    exp = _ingest(c, tmp_path, "baseline_majoritario", {"accuracy": 0.62, "tempo_s": 0.3})
    node = c.w.store.get_node(exp)
    assert node.properties["papel"] == "referencia" and _out(c.w, exp, "TESTA") == []
    results = {n.properties["nome_original"]: n for n, _ in _out(c.w, exp, "PRODUZIU")}
    assert [n.label for n, _ in _out(c.w, results["accuracy"].id, "REFERENCIA_DE")] == ["Problema"]
    assert _out(c.w, results["tempo_s"].id, "REFERENCIA_DE") == []
    assert c.w.store.get_node(h1).properties.get("veredito") == verdict_before


def test_referencia_sem_a_metrica_registra_o_evento(tmp_path):
    """Scenario: Referência sem a métrica."""
    c = LinkingCycle(tmp_path)
    c.run([sub("baseline_majoritario", task_type="validation", papel="referencia", criteria=None)])
    seen = []
    with patch("src.observability.telemetry.get_telemetry") as telemetry:
        telemetry.return_value.record_agent_event.side_effect = lambda **kw: seen.append((kw["event_type"], kw["payload"]))
        _ingest(c, tmp_path, "baseline_majoritario", {"f1_macro": 0.4})
    assert ("referencia_sem_metrica", {"subtarefa": "baseline_majoritario"}) in seen


@pytest.mark.parametrize("papel", ["referencia", "preparacao"])
def test_papel_gravado_no_experimento_sem_testa(tmp_path, papel):
    """Scenario: Papel gravado no experimento (``referencia`` e ``preparacao`` não têm ``TESTA``)."""
    c = LinkingCycle(tmp_path)
    c.run([sub("passo", papel=papel, task_type="validation", criteria=None, hypothesis="algo que seria hipótese")])
    exp = _ingest(c, tmp_path, "passo", {"accuracy": 0.5})
    assert c.w.store.get_node(exp).properties["papel"] == papel and _out(c.w, exp, "TESTA") == []


def test_teste_sem_papel_no_no_antigo_vale_teste(tmp_path):
    """Compatibilidade: nó sem ``papel`` (anterior à V18.7) vale ``teste`` (``experiment_role``)."""
    from src.knowledge.exploration_reads import experiment_role

    c = LinkingCycle(tmp_path)
    eid = c.w.store.create_node(
        "Experimento", c.w.base(subtarefa_id="x", status="sucesso", caminho_artefatos="/x", no_execucao="A"), actor=ORQ
    )
    assert experiment_role(c.w.store.get_node(eid)) == "teste"
