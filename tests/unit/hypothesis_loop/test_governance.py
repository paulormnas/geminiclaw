"""Governança por SessionMode, prioridade, status e avaliação de decisões (v18-hypothesis-loop §3 a §5)."""

from __future__ import annotations

import pytest

from src.human_gate import HumanGate, Source
from src.knowledge.hypothesis_cycle import (
    ApprovalDecision,
    HypothesisCycle,
    terminal_approver,
)
from tests.support.controlled_embedding_provider import pair_vectors
from tests.support.hypothesis_world import AGENTE, DIM, ORQ, HypothesisWorld

pytestmark = pytest.mark.unit


def _cycle(w: HypothesisWorld, **kw) -> HypothesisCycle:
    return HypothesisCycle(w.store, project_id=w.pid, session_id=w.sid, index=w.index, **kw)


def _status(w, hid):
    return w.raw.get_node(hid).properties["status"]


# -- assisted ----------------------------------------------------------------------------------------------


def test_modo_assistido_hipotese_do_researcher_nao_executa_sem_aprovacao():
    """Scenario: Modo assistido — a hipótese do Researcher só executa após aprovação."""
    w = HypothesisWorld(mode="assisted")
    hid = w.hypothesis("H do researcher")
    sel = _cycle(w).select([hid], mode="assisted", approver=lambda items: {})
    assert sel.execute == [] and sel.pending_approval == [hid] and _status(w, hid) == "proposta"


def test_modo_assistido_aprovada_executa_e_vira_em_teste_por_acao_do_pesquisador():
    w = HypothesisWorld(mode="assisted")
    hid = w.hypothesis("H do researcher")
    sel = _cycle(w).select([hid], mode="assisted", approver=lambda items: {hid: ApprovalDecision("aprovar")})
    assert sel.execute == [hid] and _status(w, hid) == "em_teste"
    assert any(e["actor"] == "pesquisador" for e in w.raw.audit_history(hid))  # a aprovação é do pesquisador


def test_modo_assistido_rejeitada_fica_abandonada_com_motivo_auditado():
    """Scenario: Modo assistido — se rejeitada, fica abandonada com motivo (autor pesquisador)."""
    w = HypothesisWorld(mode="assisted")
    hid = w.hypothesis("H do researcher")
    decision = ApprovalDecision("rejeitar", motivo="fora do escopo do projeto")
    sel = _cycle(w).select([hid], mode="assisted", approver=lambda items: {hid: decision})
    assert sel.execute == [] and sel.rejected == {hid: "fora do escopo do projeto"} and _status(w, hid) == "abandonada"
    history = w.raw.audit_history(hid)
    assert any(e["actor"] == "pesquisador" and e["changes"].get("motivo") == "fora do escopo do projeto"
               for e in history)


def test_modo_assistido_edicao_do_enunciado_aprova_com_o_texto_novo():
    w = HypothesisWorld(mode="assisted")
    hid = w.hypothesis("H antiga")
    decision = ApprovalDecision("editar", enunciado="H reescrita pelo pesquisador")
    sel = _cycle(w).select([hid], mode="assisted", approver=lambda items: {hid: decision})
    assert sel.execute == [hid]
    assert w.raw.get_node(hid).properties["enunciado"] == "H reescrita pelo pesquisador"


def test_modo_assistido_hipotese_do_pesquisador_executa_sem_aprovacao():
    """Scenario: Modo assistido — hipótese do pesquisador executa."""
    w = HypothesisWorld(mode="assisted")
    hid = w.hypothesis("H do pesquisador", origem="pesquisador")
    sel = _cycle(w).select([hid], mode="assisted", approver=None)
    assert sel.execute == [hid] and _status(w, hid) == "em_teste"


def test_aprovacao_em_lote_uma_chamada_por_ciclo():
    w = HypothesisWorld(mode="assisted")
    ids = [w.hypothesis(f"H{i}") for i in range(3)]
    calls: list[int] = []

    def approver(items):
        calls.append(len(items))
        return {i.id: ApprovalDecision("aprovar") for i in items}

    sel = _cycle(w).select(ids, mode="assisted", approver=approver)
    assert calls == [3] and sorted(sel.execute) == sorted(ids)


def test_falha_do_aprovador_nao_aprova_nada():
    w = HypothesisWorld(mode="assisted")
    hid = w.hypothesis("H")

    def boom(items):
        raise RuntimeError("terminal quebrou")

    sel = _cycle(w).select([hid], mode="assisted", approver=boom)
    assert sel.execute == [] and sel.pending_approval == [hid]


def test_sem_tty_nada_e_aprovado():
    """Sem terminal interativo o aprovador devolve vazio: as hipóteses ficam pendentes (falha fechada)."""
    w = HypothesisWorld(mode="assisted")
    hid = w.hypothesis("H")
    out: list[str] = []
    sel = _cycle(w).select([hid], mode="assisted", approver=terminal_approver(interactive=False, output_fn=out.append))
    assert sel.execute == [] and sel.pending_approval == [hid] and out


def test_aprovador_de_terminal_le_a_decisao_do_pesquisador():
    w = HypothesisWorld(mode="assisted")
    a, b, c = (w.hypothesis(f"H{i}") for i in range(3))
    answers = iter(["a", "r", "faltou dado", "e", "H3 corrigida"])
    approver = terminal_approver(input_fn=lambda _p: next(answers), output_fn=lambda _t: None, interactive=True)
    sel = _cycle(w).select([a, b, c], mode="assisted", approver=approver)
    assert set(sel.execute) == {a, c} and list(sel.rejected) == [b]
    assert w.raw.get_node(c).properties["enunciado"] == "H3 corrigida"


def test_modo_desconhecido_e_tratado_como_assistido():
    w = HypothesisWorld()
    hid = w.hypothesis("H")
    sel = _cycle(w).select([hid], mode="qualquer", approver=lambda items: {})
    assert sel.execute == [] and sel.pending_approval == [hid]


def test_resposta_do_consultor_nao_aprova_hipotese():
    """O consultor/ask_researcher nunca é aprovador: a origem não é humana e a hipótese segue pendente."""
    w = HypothesisWorld(mode="assisted")
    hid = w.hypothesis("H")
    gate = HumanGate()
    req = gate.request("aprovar_oportunidade", hid)
    gate.answer(req.id, source=Source.RESEARCHER_CONSULT, approved=True)
    assert not gate.authorized(req.id)
    assert _cycle(w).select([hid], mode="assisted", approver=None).execute == []


# -- semi / auto ---------------------------------------------------------------------------------------------


def test_modo_autonomo_executa_as_duas_de_maior_prioridade():
    """Scenario: Modo autônomo — 4 propostas, HYPOTHESES_PER_CYCLE=2: as 2 de maior prioridade executam."""
    w = HypothesisWorld(mode="auto")
    ids = [w.hypothesis(f"H{i}") for i in range(4)]
    custos = {ids[0]: "alto", ids[1]: "baixo", ids[2]: "medio", ids[3]: "baixo"}
    sel = _cycle(w, per_cycle=2).select(ids, mode="auto", custos=custos)
    ranked = sorted(ids, key=lambda i: (-sel.priorities[i], i))
    assert sel.execute == ranked[:2] and sel.deferred == ranked[2:]
    assert ids[0] in sel.deferred  # o de custo alto perde para os baratos (mesmos demais termos)
    for hid in sel.execute:
        assert _status(w, hid) == "em_teste"
    for hid in sel.deferred:
        assert _status(w, hid) == "proposta"


def test_modo_semi_tambem_usa_prioridade_e_respeita_a_config(monkeypatch):
    monkeypatch.setattr("src.config.HYPOTHESES_PER_CYCLE", 1)
    w = HypothesisWorld(mode="semi")
    ids = [w.hypothesis(f"H{i}") for i in range(3)]
    sel = _cycle(w).select(ids, mode="semi")
    assert len(sel.execute) == 1 and len(sel.deferred) == 2


def test_pesquisador_nao_consome_a_cota_do_ciclo():
    w = HypothesisWorld(mode="auto")
    mine = w.hypothesis("minha", origem="pesquisador")
    ids = [w.hypothesis(f"H{i}") for i in range(3)]
    sel = _cycle(w, per_cycle=2).select([mine, *ids], mode="auto")
    assert mine in sel.execute and len(sel.execute) == 3


def test_hipoteses_concluidas_ou_abandonadas_nao_executam_de_novo():
    w = HypothesisWorld(mode="auto")
    done, refuted, gone = (w.hypothesis(n, status=s) for n, s in
                           (("a", "validada"), ("b", "refutada"), ("c", "abandonada")))
    sel = _cycle(w).select([done, refuted, gone], mode="auto")
    assert sel.execute == [] and sorted(sel.excluded) == sorted([done, refuted, gone])


def test_prioridade_formula_e_pesos_configuraveis():
    """Prioridade = 0,35·relevância + 0,30·apoio + 0,20·novidade + 0,15·(1-custo) (sem índice: termos neutros)."""
    w = HypothesisWorld()
    hid = w.hypothesis("H")
    node = w.raw.get_node(hid)
    cycle = _cycle(w)
    # sem índice: relevância 0,5; apoio 0,5 (sem experiência); novidade 1 (nada testado); custo baixo -> 1
    assert cycle.priority(node, "baixo") == pytest.approx(0.35 * 0.5 + 0.30 * 0.5 + 0.20 * 1 + 0.15 * 1)
    assert cycle.priority(node, "alto") == pytest.approx(0.35 * 0.5 + 0.30 * 0.5 + 0.20 * 1)
    weighted = _cycle(w, weights=(1.0, 0.0, 0.0, 0.0))
    assert weighted.priority(node, "alto") == pytest.approx(0.5)


def test_prioridade_novidade_cai_com_hipotese_ja_testada_semelhante():
    w = HypothesisWorld(index=True)
    a, b = pair_vectors(DIM, 0, 0.95)
    w.provider.vectors["gama-testada"] = a
    w.provider.vectors["gama-nova"] = b
    w.provider.vectors["Previsão de rendimento"] = pair_vectors(DIM, 3, 1.0)[0]
    w.hypothesis("gama-testada", status="refutada")
    fresh = w.hypothesis("gama-nova")
    node = w.raw.get_node(fresh)
    assert _cycle(w)._novelty(node) == pytest.approx(0.05, abs=0.02)  # noqa: SLF001


def test_apoio_previo_usa_o_melhor_veredito_de_funcionou_para_e_zera_com_falha_forte():
    w = HypothesisWorld()
    abordagem = w.graph.abordagem("GB")
    hid = w.hypothesis("H")
    w.store.create_edge(hid, "PROPOE", abordagem, {}, actor=AGENTE)
    node = w.raw.get_node(hid)
    disc = w.discovery("funciona", veredito=0.62)
    w.store.create_edge(abordagem, "FUNCIONOU_PARA", w.problem.id,
                        {"metrica": "r2", "melhor_valor": 0.9, "n_exp": 3, "descoberta_id": disc},
                        actor=ORQ)
    assert _cycle(w)._prior_support(node, w.problem) == pytest.approx(0.62)  # noqa: SLF001
    w2 = HypothesisWorld()
    abordagem2 = w2.graph.abordagem("GB")
    hid2 = w2.hypothesis("H")
    w2.store.create_edge(hid2, "PROPOE", abordagem2, {}, actor=AGENTE)
    bad = w2.discovery("nao_funciona", veredito=-0.7)
    w2.store.create_edge(abordagem2, "FALHOU_PARA", w2.problem.id,
                         {"motivo": "m", "n_exp": 3, "descoberta_id": bad},
                         actor=ORQ)
    assert _cycle(w2)._prior_support(w2.raw.get_node(hid2), w2.problem) == 0.0  # noqa: SLF001


# -- status e decisões ---------------------------------------------------------------------------------------


def _hypothesis_with_attempts(w, values):
    hid = w.hypothesis("H", status="em_teste")
    for i, value in enumerate(values):
        w.attempt(hid, valor=value, no=f"N{i}", sessao=f"s{i}", seed=i + 1)
    from src.knowledge.service import KnowledgeService

    KnowledgeService(w.store).recompute_hypothesis(hid)
    return hid


def test_avaliacao_posterior_da_decisao_nao_acertada():
    """Scenario: Avaliação posterior — veredito -0,4 da hipótese escolhida: resultado_posterior="nao_acertada"."""
    w = HypothesisWorld()
    hid = _hypothesis_with_attempts(w, [0.55, 0.52, 0.5, 0.45])
    verdict = w.raw.get_node(hid).properties["veredito"]
    assert verdict <= -0.3
    decision = w.store.create_node("Decisao", w.base(contexto="c", justificativa="j", justificativa_criacao="t",
                                                      nos_consultados=[]), actor=AGENTE)
    w.store.create_edge(decision, "ESCOLHEU", hid, {}, actor=AGENTE)
    out = _cycle(w).evaluate_decisions()
    assert out == {decision: "nao_acertada"}
    assert w.raw.get_node(decision).properties["resultado_posterior"] == "nao_acertada"
    note = [e for e in w.raw.audit_history(decision) if e["changes"].get("avaliacao")][0]
    assert note["changes"]["veredito"] == pytest.approx(verdict, abs=1e-3) and note["actor"] == "orquestrador"
    assert _cycle(w).evaluate_decisions() == {}  # idempotente: só decisões sem avaliação


def test_avaliacao_posterior_acertada_e_abaixo_do_limiar_nao_avalia():
    w = HypothesisWorld()
    hid = _hypothesis_with_attempts(w, [0.85, 0.86, 0.9])
    weak = _hypothesis_with_attempts(w, [0.85])
    decisions = {}
    for target in (hid, weak):
        d = w.store.create_node("Decisao", w.base(contexto="c", justificativa="j", justificativa_criacao="t",
                                                   nos_consultados=[]), actor=AGENTE)
        w.store.create_edge(d, "ESCOLHEU", target, {}, actor=AGENTE)
        decisions[target] = d
    out = _cycle(w).evaluate_decisions()
    assert out == {decisions[hid]: "acertada"}
    assert "resultado_posterior" not in w.raw.get_node(decisions[weak]).properties


def test_status_validada_e_refutada_so_pelo_veredito_calculado():
    w = HypothesisWorld()
    good = _hypothesis_with_attempts(w, [0.85, 0.86, 0.9])
    bad = _hypothesis_with_attempts(w, [0.55, 0.52, 0.5, 0.45])
    weak = _hypothesis_with_attempts(w, [0.85])
    rejected = w.hypothesis("rejeitada pelo pesquisador", status="abandonada")
    w.store.update_node(rejected, {"veredito": 0.9}, actor=ORQ)
    changed = _cycle(w).sync_statuses([good, bad, weak, rejected])
    assert changed == {good: "validada", bad: "refutada"}
    assert _status(w, weak) == "em_teste" and _status(w, rejected) == "abandonada"


def test_hipotese_concluida_conclui_a_oportunidade_em_investigacao():
    w = HypothesisWorld()
    opp = w.opportunity(status="aprovada")
    hid = _hypothesis_with_attempts(w, [0.85, 0.86, 0.9])
    w.store.create_edge(opp, "GEROU", hid, {}, actor=ORQ)
    w.store.update_node(opp, {"status": "em_investigacao"}, actor=ORQ)
    _cycle(w).sync_statuses([hid])
    assert w.raw.get_node(opp).properties["status"] == "concluida"
