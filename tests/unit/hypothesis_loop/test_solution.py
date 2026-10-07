"""Critério "solução encontrada" e honestidade epistemológica (v18-hypothesis-loop §8, cenário 6.6)."""

from __future__ import annotations

import pytest

from agents.researcher.agent import AGENT_INSTRUCTION
from src.exploration import PLAN_FORMAT_INSTRUCTION
from src.knowledge.hypothesis_cycle import HypothesisCycle
from tests.support.hypothesis_world import PESQUISADOR, HypothesisWorld

pytestmark = pytest.mark.unit


def _cycle(w: HypothesisWorld) -> HypothesisCycle:
    return HypothesisCycle(w.store, project_id=w.pid, session_id=w.sid)


def _attempts(w, hid, values, **kw):
    for i, value in enumerate(values):
        w.attempt(hid, valor=value, no=f"N{i}", sessao=f"s{i}", seed=i + 1, **kw)


def test_solucao_com_veredito_moderado_e_alvo_atingido_por_resultado_validado():
    w = HypothesisWorld()  # alvo 0,8; delta_min 0,05; baseline 0,7
    hid = w.hypothesis("H", status="em_teste")
    _attempts(w, hid, [0.85, 0.86, 0.9])
    status = _cycle(w).check_solution()
    assert status.found and status.hypothesis_id == hid and status.verdict >= 0.3 and status.best_value == 0.9


def test_veredito_baixo_nao_e_solucao_mesmo_com_alvo_atingido():
    w = HypothesisWorld()
    hid = w.hypothesis("H", status="em_teste")
    _attempts(w, hid, [0.95])  # uma só tentativa: evidência insuficiente (veredito < 0,3)
    assert not _cycle(w).check_solution().found


def test_veredito_alto_sem_atingir_o_alvo_nao_e_solucao():
    w = HypothesisWorld(alvo=0.95)
    hid = w.hypothesis("H", status="em_teste")
    _attempts(w, hid, [0.8, 0.82, 0.84])  # melhora o baseline em >= delta_min, mas o melhor (0,84) < alvo
    from src.knowledge.service import KnowledgeService

    assert KnowledgeService(w.store).verdict_for_hypothesis(hid)[0].veredito >= 0.3  # o veredito não é o gargalo
    assert not _cycle(w).check_solution().found


def test_resultado_nao_validado_nunca_conta_como_solucao():
    """Honestidade: só resultado *validado* sustenta a solução; divergente e não validado não."""
    w = HypothesisWorld()
    hid = w.hypothesis("H", status="em_teste")
    _attempts(w, hid, [0.85, 0.86, 0.9], validacao="validado")  # veredito moderado; o melhor validado é 0,9
    w.attempt(hid, valor=0.99, no="Z", sessao="sz", seed=9, validacao="nao_validado")
    status = _cycle(w).check_solution()
    assert status.found is True and status.best_value == 0.9  # o 0,99 não validado é ignorado
    w2 = HypothesisWorld(alvo=0.9)
    h2 = w2.hypothesis("H", status="em_teste")
    _attempts(w2, h2, [0.85, 0.86, 0.87], validacao="validado")
    w2.attempt(h2, valor=0.99, no="Z", sessao="sz", seed=9, validacao="divergente_documentado")
    assert not _cycle(w2).check_solution().found


def test_hipotese_abandonada_nao_sustenta_a_solucao():
    w = HypothesisWorld()
    hid = w.hypothesis("H", status="em_teste")
    _attempts(w, hid, [0.85, 0.86, 0.9])
    w.store.update_node(hid, {"status": "abandonada"}, actor=PESQUISADOR)
    assert not _cycle(w).check_solution().found


def test_sem_alvo_vale_a_melhoria_minima_sobre_o_baseline():
    w = HypothesisWorld(alvo=None, delta_min=0.05)
    hid = w.hypothesis("H", status="em_teste")
    _attempts(w, hid, [0.8, 0.82, 0.85])  # +0,10 a +0,15 sobre o baseline 0,70 (>= delta_min)
    assert _cycle(w).check_solution().found


def test_veredito_limiar_vem_da_configuracao(monkeypatch):
    w = HypothesisWorld()
    hid = w.hypothesis("H", status="em_teste")
    _attempts(w, hid, [0.85, 0.86])  # veredito ~0,25
    assert not _cycle(w).check_solution().found
    monkeypatch.setattr("src.config.SOLUTION_MIN_VERDICT", 0.2)
    assert _cycle(w).check_solution().found


def test_hipotese_refutada_nao_vira_fato():
    """Hipótese refutada só muda de status pelo veredito; nenhum atalho FUNCIONOU_PARA/FALHOU_PARA é criado aqui."""
    w = HypothesisWorld()
    hid = w.hypothesis("H", status="em_teste")
    _attempts(w, hid, [0.55, 0.52, 0.5, 0.45])
    from src.knowledge.service import KnowledgeService

    KnowledgeService(w.store).recompute_hypothesis(hid)
    assert _cycle(w).sync_statuses([hid]) == {hid: "refutada"}
    assert w.raw.find_nodes("Descoberta", {"projeto_id": w.pid}) == []
    assert not [e for e in w.raw._edges if e.rel_type in ("FUNCIONOU_PARA", "FALHOU_PARA")]  # noqa: SLF001


def test_instrucao_do_researcher_orienta_hipoteses_decisoes_e_sugestoes():
    """Tarefa 1.2: formular hipóteses, decisões com alternativas descartadas e responder às sugestões."""
    for needle in ("hypothesis_ref", "decisão", "sugestão", "aprovadas pelo pesquisador", "DADO"):
        assert needle in AGENT_INSTRUCTION
    for key in ('"hipoteses"', '"decisoes"', '"respostas_sugestoes"', '"subtarefas"', '"descartados"',
                "sem caminhos promissores"):
        assert key in PLAN_FORMAT_INSTRUCTION
