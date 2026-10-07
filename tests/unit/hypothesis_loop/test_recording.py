"""Gravação de hipóteses, decisões e respostas no grafo (v18-hypothesis-loop, specs `hypothesis-loop`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.human_gate import HumanGate
from src.knowledge.errors import GraphStoreError
from src.knowledge.hypotheses import (
    HypothesisBook,
    HypothesisError,
    PendingSuggestion,
    split_plan,
)
from src.knowledge.ingestion import SubtaskInput, ingest_subtask
from tests.support.controlled_embedding_provider import pair_vectors
from tests.support.hypothesis_world import AGENTE, DIM, HypothesisWorld

pytestmark = pytest.mark.unit


def _book(w: HypothesisWorld, pending=None, gate=None) -> HypothesisBook:
    return HypothesisBook(w.store, w.ctx, index=w.index, pending_suggestions=lambda: pending or [],
                          gate=gate or HumanGate())


def _extras(**plan):
    base = {"subtarefas": [{"task_name": "t"}]}
    base.update(plan)
    return split_plan(base)[1]


def _nodes(w, label):
    return w.raw.find_nodes(label, {"projeto_id": w.pid}, limit=1000)


def _out(w, node_id, rel):
    sub = w.raw.neighbors(node_id, [rel], direction="out", depth=1)
    by_id = {n.id: n for n in sub.nodes}
    return [(by_id[e.dst_id], e) for e in sub.edges if e.src_id == node_id and e.rel_type == rel]


def _write_task(session_dir: Path, task: str, value: float = 0.8) -> None:
    folder = session_dir / task
    folder.mkdir(parents=True, exist_ok=True)
    params = {"task_name": task, "seed": 1, "parameters": {"n": 1}}
    (folder / "params.json").write_text(json.dumps(params), encoding="utf-8")
    payload = {**params, "metrics": {"r2": value}}
    (folder / "metrics.json").write_text(json.dumps(payload), encoding="utf-8")


def test_plano_com_hipotese(tmp_path):
    """Scenario: Plano com hipótese — Hipotese(proposta) SOBRE o Problema; os experimentos TESTA ela."""
    w = HypothesisWorld()
    extras = _extras(hipoteses=[{"ref": "h1", "enunciado": "GB supera a regressão linear", "justificativa": "J",
                                 "abordagem": {"nome": "gradient boosting", "tipo": "algoritmo"}}])
    report = _book(w).record(extras)
    hid = report.ref_map["h1"]
    node = w.raw.get_node(hid)
    assert node.properties["status"] == "proposta" and node.properties["origem"] == "researcher"
    assert [n.id for n, _ in _out(w, hid, "SOBRE")] == [w.problem.id]
    assert [n.properties["nome"] for n, _ in _out(w, hid, "PROPOE")] == ["gradient boosting"]

    session_dir = tmp_path / w.sid
    session_dir.mkdir()
    for name in ("treino_a", "treino_b"):
        _write_task(session_dir, name)
        sub = SubtaskInput(task_name=name, subtask_id=f"id-{name}", agent_id="developer", review_status="pass",
                           review_verified=True, hypothesis_id=hid, hypothesis="texto antigo ignorado")
        ingest_subtask(w.raw, w.ctx, session_dir, sub)
    experiments = _nodes(w, "Experimento")
    assert len(experiments) == 2
    for exp in experiments:
        assert [n.id for n, _ in _out(w, exp.id, "TESTA")] == [hid]
    assert len(_nodes(w, "Hipotese")) == 1  # a hipótese provisória da V17 não é criada


def test_hipotese_repetida_reutiliza_a_existente_por_similaridade():
    """Scenario: Hipótese repetida — similaridade 0,94 reutiliza o nó existente."""
    w = HypothesisWorld(index=True)
    a, b = pair_vectors(DIM, 0, 0.94)
    w.provider.vectors["alfa-original"] = a
    w.provider.vectors["alfa-parafrase"] = b
    existing = w.hypothesis("alfa-original: GB supera a regressão", status="em_teste")
    report = _book(w).record(_extras(hipoteses=[{"ref": "h1", "enunciado": "alfa-parafrase com outras palavras"}]))
    assert report.ref_map["h1"] == existing and report.reutilizadas == [existing]
    assert len(_nodes(w, "Hipotese")) == 1


def test_hipotese_abaixo_do_limiar_cria_no_novo():
    w = HypothesisWorld(index=True)
    a, b = pair_vectors(DIM, 0, 0.60)
    w.provider.vectors["beta-original"] = a
    w.provider.vectors["beta-outra"] = b
    w.hypothesis("beta-original", status="em_teste")
    report = _book(w).record(_extras(hipoteses=[{"ref": "h1", "enunciado": "beta-outra"}]))
    assert len(report.criadas) == 1 and len(_nodes(w, "Hipotese")) == 2


def test_sem_indice_a_deduplicacao_e_por_enunciado_normalizado():
    w = HypothesisWorld()
    existing = w.hypothesis("O Modelo atinge 0,85!", status="em_teste")
    report = _book(w).record(_extras(hipoteses=[{"ref": "h1", "enunciado": "o modelo atinge 0 85"}]))
    assert report.ref_map["h1"] == existing


def test_hipotese_equivalente_a_abandonada_nao_volta():
    """Uma hipótese rejeitada pelo pesquisador não é reproposta por repetição do enunciado."""
    w = HypothesisWorld()
    w.hypothesis("Idéia X", status="abandonada")
    report = _book(w).record(_extras(hipoteses=[{"ref": "h1", "enunciado": "idéia x"}]))
    assert "h1" not in report.ref_map and report.rejeitadas["h1"] == "equivalente_a_hipotese_abandonada"
    assert len(_nodes(w, "Hipotese")) == 1


def test_id_do_plano_e_conferido_no_grafo():
    """O ``id`` citado precisa ser hipótese do projeto e não estar abandonada; ID inventado é recusado."""
    w = HypothesisWorld()
    ok = w.hypothesis("continua", status="em_teste")
    gone = w.hypothesis("rejeitada", status="abandonada")
    other = w.store.create_node(
        "Hipotese",
        {"projeto_id": "outro", "sessao_id": "x", "enunciado": "alheia", "justificativa": "j", "status": "proposta",
         "origem": "researcher", "justificativa_criacao": "t", "nos_consultados": []},
        actor=AGENTE,
    )
    plan = _extras(hipoteses=[{"ref": "a", "id": ok}, {"ref": "b", "id": gone}, {"ref": "c", "id": other},
                              {"ref": "d", "id": "inventado-123"}])
    report = _book(w).record(plan)
    assert report.ref_map == {"a": ok}
    assert report.rejeitadas == {"b": "hipotese_abandonada", "c": "id_inexistente", "d": "id_inexistente"}


def test_decisao_registra_escolhido_e_descartado_com_motivo():
    """Scenario: Alternativa descartada — ESCOLHEU h1; DESCARTOU {motivo} o nó da alternativa (criado)."""
    w = HypothesisWorld()
    found = w.discovery("funciona")
    extras = _extras(
        hipoteses=[{"ref": "h1", "enunciado": "GB supera a linear", "justificativa": "J"}],
        decisoes=[{
            "contexto": "Escolha do modelo inicial", "escolhido": {"tipo": "Hipotese", "ref": "h1"},
            "descartados": [
                {"tipo": "Abordagem", "nome": "rede neural profunda", "motivo": "dataset pequeno; sobreajuste"},
                {"tipo": "Hipotese", "nome": "SVM resolve tudo", "motivo": "custo alto"},
            ],
            "criterio": "evidencia_previa", "justificativa": "J", "informada_por": [found, "descoberta-forjada"],
        }],
    )
    report = _book(w).record(extras)
    (decision_id,) = report.decisoes
    decision = w.raw.get_node(decision_id)
    assert decision.properties["criterio"] == "evidencia_previa"
    assert "resultado_posterior" not in decision.properties  # só a avaliação posterior o preenche
    (chosen, _), = _out(w, decision_id, "ESCOLHEU")
    assert chosen.id == report.ref_map["h1"]
    discarded = {n.label: (n, e) for n, e in _out(w, decision_id, "DESCARTOU")}
    assert discarded["Abordagem"][0].properties["nome"] == "rede neural profunda"
    assert "sobreajuste" in discarded["Abordagem"][1].properties["motivo"]
    assert discarded["Hipotese"][0].properties["status"] == "abandonada"  # caminho não seguido registrado
    assert discarded["Hipotese"][1].properties["motivo"] == "custo alto"
    assert [n.id for n, _ in _out(w, decision_id, "TOMADA_EM")] == [w.session_node]
    assert [n.id for n, _ in _out(w, decision_id, "INFORMADA_POR")] == [found]  # ID forjado ignorado


def test_decisao_com_hipotese_recusada_nao_e_gravada():
    w = HypothesisWorld()
    w.hypothesis("Idéia X", status="abandonada")
    extras = _extras(
        hipoteses=[{"ref": "h1", "enunciado": "idéia x"}],
        decisoes=[{"contexto": "c", "escolhido": {"tipo": "Hipotese", "ref": "h1"}, "justificativa": "j"}],
    )
    assert _book(w).record(extras).decisoes == []


def test_oportunidade_documentada_nunca_origina_hipotese_e_fica_pendente_no_gate():
    """Nenhuma oportunidade é investigada sem aprovação: o pedido fica pendente e a hipótese é recusada."""
    w = HypothesisWorld()
    opp = w.opportunity()
    gate = HumanGate()
    extras = _extras(hipoteses=[{"ref": "h1", "enunciado": "Investigar X", "derivada_de": [opp]}])
    report = _book(w, gate=gate).record(extras)
    assert report.rejeitadas == {"h1": "oportunidade_nao_aprovada"} and report.oportunidades_pendentes == [opp]
    assert w.raw.get_node(opp).properties["status"] == "documentada"
    assert _nodes(w, "Hipotese") == []
    assert [(r.decisao, r.referencia) for r in gate.pending()] == [("aprovar_oportunidade", opp)]
    _book(w, gate=gate).record(extras)  # repetido: o pedido não duplica
    assert len(gate.pending()) == 1


def test_oportunidade_aprovada_vira_hipotese_com_gerou_e_em_investigacao():
    """Scenario: Oportunidade aprovada — Oportunidade-GEROU->Hipotese e a oportunidade fica em_investigacao."""
    w = HypothesisWorld()
    opp = w.opportunity(status="aprovada")
    report = _book(w).record(_extras(hipoteses=[{"ref": "h1", "enunciado": "Investigar X", "derivada_de": [opp]}]))
    hid = report.ref_map["h1"]
    assert w.raw.get_node(hid).properties["origem"] == "oportunidade"
    assert [n.id for n, _ in _out(w, opp, "GEROU")] == [hid]
    assert w.raw.get_node(opp).properties["status"] == "em_investigacao"
    assert [n.id for n, _ in _out(w, hid, "DERIVADA_DE")] == [opp]


def test_sugestao_aceita_gera_hipotese_curator_derivada_do_fundamento():
    """Scenario: Sugestão aceita — hipótese origem=curator e DERIVADA_DE a descoberta de fundamento."""
    w = HypothesisWorld()
    path = w.discovery("caminho_sem_conclusao", proximo_passo_sugerido="Testar floresta aleatória")
    suggestion = PendingSuggestion("s1", "Testar floresta aleatória", (path,), "caminho_sem_conclusao")
    extras = _extras(
        hipoteses=[{"ref": "h2", "enunciado": "Floresta aleatória supera a linear", "justificativa": "J"}],
        respostas_sugestoes=[{"sugestao_id": "s1", "decisao": "aceita", "motivo": "plausível", "hipotese_ref": "h2"}],
    )
    report = _book(w, [suggestion]).record(extras)
    hid = report.ref_map["h2"]
    assert w.raw.get_node(hid).properties["origem"] == "curator"
    assert [n.id for n, _ in _out(w, hid, "DERIVADA_DE")] == [path]
    assert report.respostas_registradas == {"s1": "aceita"}


def test_sugestao_recusada_fica_registrada_com_motivo_como_descartou():
    w = HypothesisWorld()
    path = w.discovery("caminho_sem_conclusao")
    suggestion = PendingSuggestion("s1", "Testar floresta aleatória", (path,), "caminho_sem_conclusao")
    extras = _extras(respostas_sugestoes=[{"sugestao_id": "s1", "decisao": "recusada", "motivo": "custo alto"}])
    report = _book(w, [suggestion]).record(extras)
    assert report.respostas_registradas == {"s1": "recusada"}
    (decision_id,) = report.decisoes
    ((target, edge),) = _out(w, decision_id, "DESCARTOU")
    assert target.properties["status"] == "abandonada" and target.properties["origem"] == "curator"
    assert "custo alto" in edge.properties["motivo"]
    assert [n.id for n, _ in _out(w, target.id, "DERIVADA_DE")] == [path]


def test_aceita_sem_hipotese_correspondente_vira_recusa_registrada():
    w = HypothesisWorld()
    suggestion = PendingSuggestion("s1", "Testar X", (), "caminho_sem_conclusao")
    extras = _extras(respostas_sugestoes=[{"sugestao_id": "s1", "decisao": "aceita", "motivo": "sim",
                                           "hipotese_ref": "inexistente"}])
    assert _book(w, [suggestion]).record(extras).respostas_registradas == {"s1": "recusada"}


def test_resposta_a_sugestao_desconhecida_e_ignorada():
    w = HypothesisWorld()
    extras = _extras(respostas_sugestoes=[{"sugestao_id": "forjada", "decisao": "recusada", "motivo": "m"}])
    report = _book(w).record(extras)
    assert report.respostas_registradas == {} and report.decisoes == []


def test_sem_problema_confirmado_nao_grava():
    from src.knowledge.graph_store import InMemoryGraphStore
    from src.knowledge.ingestion import SessionContext
    from src.knowledge.projects import create_project

    store = InMemoryGraphStore()
    pid = create_project(store, "P", "O", [])
    ctx = SessionContext(pid, "s", "auto", "2026-10-07T00:00:00+00:00", "no")
    with pytest.raises(HypothesisError):
        HypothesisBook(store, ctx).record(_extras(hipoteses=[{"ref": "h1", "enunciado": "X"}]))
    assert issubclass(HypothesisError, GraphStoreError)


def test_aceita_com_hipotese_sem_relacao_nao_empresta_proveniencia_da_oportunidade():
    """Scenario: Sugestão aceita sem relação — não herda DERIVADA_DE/GEROU nem muda a oportunidade aprovada."""
    w = HypothesisWorld()
    opp = w.opportunity("Investigar a variação de temperatura no ensaio", status="aprovada")
    text = "Investigar a variação de temperatura no ensaio"
    suggestion = PendingSuggestion("s1", text, (opp,), "oportunidade_aprovada")
    extras = _extras(
        hipoteses=[
            {"ref": "h1", "enunciado": "Normalizar os dados melhora o desempenho do modelo", "justificativa": "J"}
        ],
        respostas_sugestoes=[{"sugestao_id": "s1", "decisao": "aceita", "motivo": "ok", "hipotese_ref": "h1"}],
    )
    report = _book(w, [suggestion]).record(extras)
    hid = report.ref_map["h1"]
    assert w.raw.get_node(hid).properties["origem"] == "researcher"
    assert _out(w, hid, "DERIVADA_DE") == [] and _out(w, opp, "GEROU") == []
    assert w.raw.get_node(opp).properties["status"] == "aprovada"
    assert report.respostas_registradas == {"s1": "recusada"}


def test_aceita_com_derivada_de_explicito_igual_ao_fundamento_liga_a_oportunidade():
    w = HypothesisWorld()
    opp = w.opportunity("Investigar a variação de temperatura no ensaio", status="aprovada")
    text = "Investigar a variação de temperatura no ensaio"
    suggestion = PendingSuggestion("s1", text, (opp,), "oportunidade_aprovada")
    extras = _extras(
        hipoteses=[{"ref": "h1", "enunciado": "Hipótese redigida de outro modo", "justificativa": "J",
                    "derivada_de": [opp]}],
        respostas_sugestoes=[{"sugestao_id": "s1", "decisao": "aceita", "motivo": "ok", "hipotese_ref": "h1"}],
    )
    report = _book(w, [suggestion]).record(extras)
    hid = report.ref_map["h1"]
    assert [n.id for n, _ in _out(w, opp, "GEROU")] == [hid]
    assert report.respostas_registradas == {"s1": "aceita"}


def _aceita_com_indice(enunciado: str):
    w = HypothesisWorld(index=True)
    a, near = pair_vectors(DIM, 0, 0.95)
    _, far = pair_vectors(DIM, 0, 0.30)
    w.provider.vectors.update({"gama-sug": a, "gama-perto": near, "gama-longe": far})
    path = w.discovery("caminho_sem_conclusao", proximo_passo_sugerido="gama-sug")
    suggestion = PendingSuggestion("s1", "gama-sug", (path,), "caminho_sem_conclusao")
    extras = _extras(
        hipoteses=[{"ref": "h1", "enunciado": enunciado, "justificativa": "J"}],
        respostas_sugestoes=[{"sugestao_id": "s1", "decisao": "aceita", "motivo": "ok", "hipotese_ref": "h1"}],
    )
    return _book(w, [suggestion]).record(extras)


def test_aceita_com_indice_exige_similaridade_semantica_com_o_texto_da_sugestao():
    assert _aceita_com_indice("gama-longe").respostas_registradas == {"s1": "recusada"}
    assert _aceita_com_indice("gama-perto").respostas_registradas == {"s1": "aceita"}
