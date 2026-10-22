"""Transições de status pela regra de réplicas e revisão dos efeitos (spec ``hypothesis-loop``; ADR 026 §3)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.knowledge.errors import HumanConfirmationRequiredError
from src.knowledge.hypothesis_cycle import ORQUESTRADOR, ORQUESTRADOR_REABERTURA, HypothesisCycle
from tests.support.hypothesis_world import AGENTE, CURATOR, ORQ, PESQUISADOR, HypothesisWorld
from tests.support.linking_world import LinkingCycle, sub

pytestmark = pytest.mark.unit


def _set(c: LinkingCycle, hid: str, **props) -> None:
    c.w.store.update_node(hid, props, actor=ORQ)


def _counts(c: LinkingCycle, hid: str, acima: int, abaixo: int, tentativas: int = 1) -> None:
    _set(c, hid, n_atingiu_alvo=acima, n_abaixo_alvo=abaixo, n_tentativas=tentativas)


def _decision(c: LinkingCycle, hid: str, result: str | None) -> str:
    did = c.w.store.create_node(
        "Decisao", c.w.base(contexto="c", justificativa="j", justificativa_criacao="t", nos_consultados=[]), actor=AGENTE
    )
    c.w.store.create_edge(did, "ESCOLHEU", hid, {}, actor=AGENTE)
    if result:
        c.w.store.update_node(did, {"resultado_posterior": result}, actor=ORQ)
    return did


@pytest.fixture(autouse=True)
def _rule():
    with patch("src.config.HYPOTHESIS_MIN_REPLICAS", 2), patch("src.config.HYPOTHESIS_MIN_REFUTATIONS", 2):
        yield


def test_replicacao_que_contesta_a_validacao(tmp_path):
    """Scenario: Replicação que contesta a validação."""
    c = LinkingCycle(tmp_path)
    h1 = c.w.hypothesis("H1", status="validada")
    _counts(c, h1, 1, 0)
    c.session.after_cycle()
    assert c.status(h1) == "em_teste"
    (event,) = c.events_of("hipotese_transicao")
    assert event["status_anterior"] == "validada" and event["status_novo"] == "em_teste"
    assert event["regra"] == "reabertura" and event["hipotese_id"] == h1
    assert (event["n_atingiu_alvo"], event["n_abaixo_alvo"]) == (1, 0)


def test_mudanca_de_lado(tmp_path):
    """Scenario: Mudança de lado (a decisão ``acertada`` passa a ``nao_acertada``)."""
    c = LinkingCycle(tmp_path)
    h1 = c.w.hypothesis("H1", status="validada")
    decision = _decision(c, h1, "acertada")
    _counts(c, h1, 0, 2)
    c.session.after_cycle()
    assert c.status(h1) == "refutada"
    assert c.w.store.get_node(decision).properties["resultado_posterior"] == "nao_acertada"
    assert any(e["changes"].get("reavaliacao") == "nao_acertada" for e in c.w.store.audit_log if e["node_id"] == decision)


def test_oportunidade_reaberta_e_decisao_reavaliada(tmp_path):
    """Scenario: Oportunidade reaberta."""
    c = LinkingCycle(tmp_path)
    h1 = c.w.hypothesis("H1", status="validada")
    opp = c.w.opportunity(status="concluida")
    c.w.store.create_edge(opp, "GEROU", h1, {}, actor=ORQ)
    decision = _decision(c, h1, "acertada")
    _counts(c, h1, 1, 0)
    c.session.after_cycle()
    assert c.w.store.get_node(opp).properties["status"] == "em_investigacao"
    assert not c.w.store.get_node(decision).properties.get("resultado_posterior")


def test_mudanca_de_lado_mantem_a_oportunidade_concluida(tmp_path):
    c = LinkingCycle(tmp_path)
    h1 = c.w.hypothesis("H1", status="validada")
    opp = c.w.opportunity(status="concluida")
    c.w.store.create_edge(opp, "GEROU", h1, {}, actor=ORQ)
    _counts(c, h1, 0, 3)
    c.session.after_cycle()
    assert c.w.store.get_node(opp).properties["status"] == "concluida"


def test_nada_muda_no_meio_do_ciclo(tmp_path):
    """Scenario: Nada muda no meio do ciclo (``prepare_cycle`` e a governança não transitam)."""
    c = LinkingCycle(tmp_path)
    h1 = c.w.hypothesis("H1", status="validada")
    _counts(c, h1, 1, 0)
    outcome = c.run([sub("segunda", hypothesis_ref=h1)])
    assert "segunda" in {t.task_name for t in outcome.tasks} and c.status(h1) == "validada"


@pytest.mark.parametrize(
    ("status", "acima", "abaixo", "tries", "expected"),
    [
        ("em_teste", 2, 0, 1, "validada"), ("em_teste", 0, 2, 1, "refutada"), ("em_teste", 1, 0, 1, "em_teste"),
        ("em_teste", 1, 2, 1, "em_teste"), ("inconclusiva", 3, 0, 1, "validada"), ("proposta", 2, 0, 1, "validada"),
        ("proposta", 2, 0, 0, "proposta"), ("validada", 0, 2, 1, "refutada"), ("validada", 1, 0, 1, "em_teste"),
        ("validada", 2, 0, 1, "validada"), ("refutada", 2, 0, 1, "validada"), ("refutada", 1, 1, 1, "em_teste"),
        ("refutada", 0, 3, 1, "refutada"), ("abandonada", 2, 0, 1, "abandonada"),
    ],
)
def test_tabela_de_transicoes(tmp_path, status, acima, abaixo, tries, expected):
    c = LinkingCycle(tmp_path)
    h = c.w.hypothesis("H", status=status, abandonada_por="agente" if status == "abandonada" else None)
    _counts(c, h, acima, abaixo, tries)
    HypothesisCycle(c.w.store, project_id=c.w.pid, session_id=c.w.sid).sync_statuses([h])
    assert c.status(h) == expected


def test_a_transicao_grava_a_regra_e_as_contagens(tmp_path):
    c = LinkingCycle(tmp_path)
    h = c.w.hypothesis("H", status="em_teste")
    cycle = HypothesisCycle(c.w.store, project_id=c.w.pid, session_id=c.w.sid)
    _counts(c, h, 2, 0, 2)
    cycle.sync_statuses([h])
    _counts(c, h, 1, 0, 3)
    cycle.sync_statuses([h])
    assert [(t.status_anterior, t.status_novo, t.regra, t.n_atingiu_alvo, t.n_abaixo_alvo) for t in cycle.transitions] == [
        ("validada", "em_teste", "reabertura", 1, 0)
    ]
    notas = [e["changes"] for e in c.w.store.audit_log if e["node_id"] == h and "regra" in e["changes"]]
    assert [n["regra"] for n in notas] == ["replicas_atingiram_alvo", "reabertura"]


def test_estado_depende_so_das_contagens_gravadas_pelo_orquestrador(tmp_path):
    """Sem contagens gravadas (hipótese ainda sem recálculo) o estado não muda."""
    c = LinkingCycle(tmp_path)
    h = c.w.hypothesis("H", status="em_teste")
    HypothesisCycle(c.w.store, project_id=c.w.pid, session_id=c.w.sid).sync_statuses([h])
    assert c.status(h) == "em_teste"


# -- reversão de Oportunidade fora do alcance dos agentes (parecer de segurança, item 3) ------------------------


def test_curator_nao_reverte_a_oportunidade():
    """Scenario: Curator tenta reverter a oportunidade."""
    w = HypothesisWorld()
    opp = w.opportunity(status="concluida")
    with pytest.raises(HumanConfirmationRequiredError):
        w.store.update_node(opp, {"status": "em_investigacao"}, actor=CURATOR)
    assert w.store.get_node(opp).properties["status"] == "concluida"


def test_orquestrador_sem_a_flag_nao_reverte_a_oportunidade():
    """Scenario: Orquestrador sem a flag."""
    w = HypothesisWorld()
    opp = w.opportunity(status="concluida")
    with pytest.raises(HumanConfirmationRequiredError):
        w.store.update_node(opp, {"status": "em_investigacao"}, actor=ORQ)
    w.store.update_node(opp, {"status": "em_investigacao"}, actor=ORQUESTRADOR_REABERTURA)
    assert w.store.get_node(opp).properties["status"] == "em_investigacao"


def test_a_flag_nao_libera_aprovar_ou_rejeitar(tmp_path):
    """O orquestrador (com ou sem a flag) continua sem poder aprovar ou rejeitar ``Oportunidade``."""
    w = HypothesisWorld()
    documentada = w.opportunity()
    for actor in (ORQ, ORQUESTRADOR, ORQUESTRADOR_REABERTURA):
        for status in ("aprovada", "rejeitada"):
            with pytest.raises(HumanConfirmationRequiredError):
                w.store.update_node(documentada, {"status": status}, actor=actor)
    w.store.update_node(documentada, {"status": "aprovada"}, actor=PESQUISADOR)
    with pytest.raises(HumanConfirmationRequiredError):
        w.store.update_node(documentada, {"decidido_por": "orquestrador"}, actor=ORQUESTRADOR_REABERTURA)


def test_plano_com_campo_de_reversao_nao_muda_oportunidade(tmp_path):
    """Scenario: Plano com campo de reversão (o campo é descartado)."""
    c = LinkingCycle(tmp_path)
    opp = c.w.opportunity(status="concluida")
    plan_sub = sub("t", revert_on_reopen=True)
    c.run([plan_sub], revert_on_reopen=True)
    assert not hasattr(c.tasks["t"], "revert_on_reopen")
    c.session.after_cycle()
    assert c.w.store.get_node(opp).properties["status"] == "concluida"
    assert json.dumps(c.events)  # nenhum evento carrega o campo
    assert "revert_on_reopen" not in repr(c.events)
