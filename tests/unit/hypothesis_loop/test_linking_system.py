"""``v18.7-hypothesis-linking``: hipótese do sistema para teste sem hipótese aceita (spec ``hypothesis-loop``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.knowledge.exploration_reads import structured_key
from src.knowledge.ingestion import SubtaskInput, ingest_subtask
from tests.support import exploration_graph as eg
from tests.support.linking_world import LinkingCycle, sub

RF = {"nome": "random forest", "tipo": "algoritmo"}

pytestmark = pytest.mark.unit


def _out(w, node_id: str, rel: str):
    graph = w.store.neighbors(node_id, [rel], direction="out", depth=1)
    by_id = {n.id: n for n in graph.nodes}
    return [(by_id[e.dst_id], e) for e in graph.edges if e.src_id == node_id and e.rel_type == rel]


def _abordagem_id(c: LinkingCycle, nome: str) -> str:
    (node,) = c.w.store.find_nodes("Abordagem", {"projeto_id": c.w.pid, "nome": nome}, limit=1)
    return node.id


def test_teste_sem_hipotese_declarada(tmp_path):
    """Scenario: Teste sem hipótese declarada."""
    c = LinkingCycle(tmp_path)
    eg.referencia(c.w, 0.62)
    outcome = c.run([sub("treinar_rf", approach=RF)])
    (hs,) = c.system_hypotheses()
    props = hs.properties
    assert props["origem"] == "sistema" and props["status"] in ("proposta", "em_teste")
    assert props["chave_estruturada"] == structured_key(c.w.problem.id, _abordagem_id(c, "random forest"), c.w.graph.metrica)
    assert props["referencia_fixada"]["valor"] == 0.62 and props["referencia_fixada"]["origem_referencia"] == "referencia_medida"
    assert [n.id for n, _ in _out(c.w, hs.id, "SOBRE")] == [c.w.problem.id]
    assert [n.properties["nome"] for n, _ in _out(c.w, hs.id, "PROPOE")] == ["random forest"]
    assert c.tasks["treinar_rf"].hypothesis_id == hs.id and outcome.dropped == {}
    (event,) = c.events_of("hipotese_derivada")
    assert event["subtarefa"] == "treinar_rf" and event["motivo"] == "sem_hypothesis_ref" and event["hipotese_id"] == hs.id


def test_referencia_fixada_nao_muda(tmp_path):
    """Scenario: Referência fixada não muda."""
    c = LinkingCycle(tmp_path)
    eg.referencia(c.w, 0.62)
    c.run([sub("treinar_rf", approach=RF)])
    eg.referencia(c.w, 0.70)
    c.run([sub("treinar_rf", approach=RF)])
    (hs,) = c.system_hypotheses()
    assert hs.properties["referencia_fixada"]["valor"] == 0.62


def test_sem_referencia_medida(tmp_path):
    """Scenario: Sem referência medida."""
    c = LinkingCycle(tmp_path)
    c.run([sub("treinar_rf", approach=RF)])
    (hs,) = c.system_hypotheses()
    assert hs.properties["referencia_fixada"]["valor"] is None
    assert hs.properties["referencia_fixada"]["origem_referencia"] == "indisponivel"
    assert "não disponível" in hs.properties["enunciado"]


def test_referencia_inexistente_no_plano(tmp_path):
    """Scenario: Referência inexistente no plano (``h9`` não é declarada nem existe no grafo)."""
    c = LinkingCycle(tmp_path)
    outcome = c.run([sub("treinar_knn", hypothesis_ref="h9", criteria=("accuracy >= 0.9",))])
    assert "treinar_knn" not in outcome.dropped
    (event,) = c.events_of("hipotese_derivada")
    assert event["motivo"] == "ref_id_inexistente"


def test_ref_recusada_por_formato_vira_motivo_de_hipotese_derivada(tmp_path):
    """``id_inexistente`` e ``sem_enunciado`` são falha de formato: deriva a hipótese; as outras recusas retiram."""
    from src.knowledge.hypotheses import RecordReport
    from src.orchestration.exploration_linking import resolve_task_refs
    from tests.support.linking_world import to_task

    c = LinkingCycle(tmp_path)
    tasks = [to_task(sub(f"t_{r}", hypothesis_ref=r)) for r in ("a", "b", "c", "d")]
    report = RecordReport(rejeitadas={"a": "sem_enunciado", "b": "id_inexistente", "c": "hipotese_abandonada",
                                      "d": "oportunidade_nao_aprovada"})
    out = resolve_task_refs(c.session.book, tasks, report)
    assert out.motivo == {"t_a": "ref_sem_enunciado", "t_b": "ref_id_inexistente"}
    assert out.dropped == {"t_c": "hipotese_hipotese_abandonada", "t_d": "hipotese_oportunidade_nao_aprovada"}


def test_papel_teste_declarado_sem_hypothesis_ref(tmp_path):
    c = LinkingCycle(tmp_path)
    c.run([sub("estudo", papel="teste", criteria=None)])
    assert [e["motivo"] for e in c.events_of("hipotese_derivada")] == ["papel_teste_declarado"]


def test_variacao_reutiliza_a_hipotese(tmp_path):
    """Scenario: Variação reutiliza a hipótese (``TESTA`` a mesma e ``APLICOU`` com a nova configuração)."""
    c = LinkingCycle(tmp_path)
    c.run([sub("treinar_rf", approach=RF)])
    (hs,) = c.system_hypotheses()
    c.run([sub("treinar_rf_200_arvores", approach=RF, parameters={"n_estimators": 200})])
    assert [h.id for h in c.system_hypotheses()] == [hs.id]
    assert c.tasks["treinar_rf_200_arvores"].hypothesis_id == hs.id
    (event,) = c.events_of("hipotese_derivada")[-1:]
    assert event["reutilizada"] is True and event["reaberta"] is False
    folder = Path(tmp_path) / "out" / "treinar_rf_200_arvores"
    folder.mkdir(parents=True)
    (folder / "metrics.json").write_text(json.dumps({"metrics": {"accuracy": 0.9}}), encoding="utf-8")
    (folder / "params.json").write_text(json.dumps({"seed": 1, "parameters": {"n_estimators": 200}}), encoding="utf-8")
    task = c.tasks["treinar_rf_200_arvores"]
    exp = ingest_subtask(
        c.w.store, c.w.ctx, Path(tmp_path) / "out",
        SubtaskInput(task_name=task.task_name, subtask_id=task.subtask_id, agent_id="developer", task_type="model_impl",
                     approach=RF, hypothesis_id=task.hypothesis_id, papel="teste", review_status="pass",
                     review_verified=True, validation_criteria=["accuracy >= 0.9"]),
    )
    assert [n.id for n, _ in _out(c.w, exp, "TESTA")] == [hs.id]
    ((approach, edge),) = _out(c.w, exp, "APLICOU")
    assert approach.properties["nome"] == "random forest" and edge.properties["config"] == {"n_estimators": 200}


def test_abordagens_diferentes_nao_se_fundem(tmp_path):
    """Scenario: Abordagens diferentes não se fundem (e duas subtarefas iguais compartilham a hipótese)."""
    c = LinkingCycle(tmp_path)
    c.run([
        sub("rf", approach=RF), sub("gb", approach={"nome": "gradient boosting", "tipo": "algoritmo"}),
        sub("rf_outra_semente", approach=RF),
    ])
    keys = {h.properties["chave_estruturada"] for h in c.system_hypotheses()}
    assert len(c.system_hypotheses()) == 2 and len(keys) == 2
    assert c.tasks["rf"].hypothesis_id == c.tasks["rf_outra_semente"].hypothesis_id != c.tasks["gb"].hypothesis_id


def test_texto_livre_afirmativo_vira_enunciado(tmp_path):
    """Scenario: Texto livre afirmativo vira enunciado (``enunciado_fonte = texto_livre`` na auditoria e no evento)."""
    c = LinkingCycle(tmp_path)
    c.run([sub("treinar_svm", approach={"nome": "svm", "tipo": "algoritmo"},
               hypothesis="SVM com kernel RBF supera a referência em acurácia")])
    (hs,) = c.system_hypotheses()
    assert hs.properties["enunciado"] == "SVM com kernel RBF supera a referência em acurácia"
    assert c.events_of("hipotese_derivada")[0]["enunciado_fonte"] == "texto_livre"
    notes = [e["changes"] for e in c.w.store.audit_log if e["node_id"] == hs.id and "enunciado_fonte" in e["changes"]]
    assert notes[0]["enunciado_fonte"] == "texto_livre"


def test_texto_livre_negativo_nao_vira_enunciado(tmp_path):
    """Scenario: Texto livre negativo não vira enunciado."""
    c = LinkingCycle(tmp_path)
    c.run([sub("treinar_svm", approach={"nome": "svm", "tipo": "algoritmo"},
               hypothesis="Não se testa hipótese; produz o modelo")])
    (hs,) = c.system_hypotheses()
    text = hs.properties["enunciado"].lower()
    assert "svm" in text and ("acuracia" in text or "acurácia" in text)
    assert c.events_of("hipotese_derivada")[0]["enunciado_fonte"] == "modelo"


def test_texto_livre_que_nao_cita_a_metrica_usa_o_modelo(tmp_path):
    c = LinkingCycle(tmp_path)
    c.run([sub("treinar_svm", approach={"nome": "svm", "tipo": "algoritmo"}, hypothesis="SVM é um bom modelo")])
    assert c.events_of("hipotese_derivada")[0]["enunciado_fonte"] == "modelo"


def test_teste_sem_abordagem_usa_a_abordagem_do_nome_da_subtarefa(tmp_path):
    """Design §16, questão 2: sem ``approach``, ``Abordagem`` ``tipo = "outro"`` com o nome da subtarefa."""
    c = LinkingCycle(tmp_path)
    c.run([sub("treino_misterioso", criteria=("accuracy >= 0.9",))])
    (hs,) = c.system_hypotheses()
    ((approach, _),) = _out(c.w, hs.id, "PROPOE")
    assert approach.properties["nome"] == "treino_misterioso" and approach.properties["tipo"] == "outro"
    assert any(i["acao"] == "formato" for i in c.session.linkage_feedback())


def test_sem_metrica_a_subtarefa_segue_como_preparacao_do_problema(tmp_path):
    """Design §16, questão 3: sem M resolvida, não inventa hipótese."""
    c = LinkingCycle(tmp_path, approve_metric=False)
    c.w.store.update_node(c.w.graph.metrica, {"sentido": "maior_melhor"}, actor=eg.ORQ)  # metrica existe, mas sem critério
    # remove a métrica do critério do Problema para que ela não resolva
    c.w.store.update_node(c.w.problem.id, {"criterio_sucesso": {"alvo": 0.8}}, actor=eg.PESQUISADOR)
    outcome = c.run([sub("treinar_rf", approach=RF)])
    assert c.system_hypotheses() == [] and outcome.dropped == {}
    assert c.tasks["treinar_rf"].papel_decidido == "preparacao"
