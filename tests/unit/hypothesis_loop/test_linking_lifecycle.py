"""``v18.7-hypothesis-linking``: ciclo de vida, aprovação por modo e reabertura da hipótese do sistema."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.knowledge.system_hypotheses import metric_ref
from tests.support import exploration_graph as eg
from tests.support.fake_gate import FakeGate
from tests.support.hypothesis_world import ORQ, PESQUISADOR
from tests.support.linking_world import LinkingCycle, sub

RF = {"nome": "random forest", "tipo": "algoritmo"}

pytestmark = pytest.mark.unit


def _plan_for(name: str) -> dict:
    """Teste sem ``hypothesis_ref`` cuja abordagem produz a chave de ``eg.hipotese(origem="sistema", enunciado=name)``."""
    return sub("treinar_x", approach={"nome": f"abordagem-{name}", "tipo": "algoritmo"})


def _abandoned_by_system(c: LinkingCycle, name: str = "HS1", motivo: str = "subtarefa_retirada") -> str:
    return eg.hipotese(c.w, origem="sistema", enunciado=name, status="abandonada", abandonada_por="sistema",
                       motivo_abandono=motivo)


def _props(c: LinkingCycle, hid: str) -> dict:
    node = c.w.store.get_node(hid)
    assert node is not None
    return node.properties


# -- ciclo de vida ----------------------------------------------------------------------------------------------


def test_retentativas_esgotadas_sem_execucao(tmp_path):
    """Scenario: Retentativas esgotadas sem execução."""
    c = LinkingCycle(tmp_path)
    c.run([sub("treinar_rf", approach=RF)])
    (hs,) = c.system_hypotheses()
    c.session.after_cycle(["treinar_rf"])
    props = _props(c, hs.id)
    assert props["status"] == "abandonada" and props["abandonada_por"] == "sistema"
    assert props["motivo_abandono"] == "tentativas_esgotadas_sem_execucao"
    assert hs.id not in [n.id for n in c.session.cycle.untested_hypotheses()]
    assert c.events_of("hipotese_sistema_abandonada")[0]["motivo_abandono"] == "tentativas_esgotadas_sem_execucao"


def test_reabertura_pela_chave_no_automatico(tmp_path):
    """Scenario: Reabertura pela chave."""
    c = LinkingCycle(tmp_path, mode="auto")
    hs1 = _abandoned_by_system(c)
    c.run([_plan_for("HS1")])
    props = _props(c, hs1)
    assert props["status"] == "em_teste" and not props.get("abandonada_por") and not props.get("motivo_abandono")
    assert c.events_of("hipotese_derivada")[0]["reaberta"] is True
    assert c.tasks["treinar_x"].hypothesis_id == hs1
    assert [e for e in c.w.store.audit_log if e["node_id"] == hs1 and "reabertura" in e["changes"]]  # histórico


def test_reabertura_no_assistido_com_aprovacao_no_gate(tmp_path):
    """Scenario: Reabertura no assistido com aprovação no gate."""
    gate = FakeGate()
    c = LinkingCycle(tmp_path, mode="assisted", approver=gate)
    hs1 = _abandoned_by_system(c)
    gate.seed("aprovar_hipotese", hs1, estado="autorizada", resolvido_por="terminal")
    outcome = c.run([_plan_for("HS1")])
    assert _props(c, hs1)["status"] == "em_teste" and "treinar_x" in {t.task_name for t in outcome.tasks}


def test_reabertura_no_assistido_sem_aprovacao_no_gate(tmp_path):
    """Scenario: Reabertura no assistido sem aprovação no gate (a trilha do grafo não é prova)."""
    gate = FakeGate()
    c = LinkingCycle(tmp_path, mode="assisted", approver=gate)
    hs1 = _abandoned_by_system(c)
    c.w.store.record_audit_note(hs1, PESQUISADOR, {"decisao": "aprovada"})
    outcome = c.run([_plan_for("HS1")])
    assert _props(c, hs1)["status"] == "proposta"
    assert outcome.dropped == {"treinar_x": "hipotese_aguarda_aprovacao"}


def test_reabertura_no_assistido_com_pedido_negado_ou_nao_humano_nao_vale(tmp_path):
    gate = FakeGate()
    c = LinkingCycle(tmp_path, mode="assisted", approver=gate)
    hs1 = _abandoned_by_system(c)
    gate.seed("aprovar_hipotese", hs1, estado="autorizada", resolvido_por="agente")
    c.run([_plan_for("HS1")])
    assert _props(c, hs1)["status"] == "proposta"


def test_interface_provisoria_antes_do_gate(tmp_path):
    """Scenario: Interface provisória antes do gate (``NoGateApprovalPort``: ``previously_approved`` é falso)."""
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: {})
    hs1 = _abandoned_by_system(c)
    c.w.store.record_audit_note(hs1, PESQUISADOR, {"decisao": "aprovada"})  # "aprovada antes" pelo Approver injetado
    outcome = c.session.book.system_hypothesis(
        task_name="treinar_x", approach={"nome": "abordagem-HS1", "tipo": "algoritmo"}, text="",
        metric=c.session._metric(), motivo="sem_hypothesis_ref",
    )
    assert outcome.reopened and _props(c, hs1)["status"] == "proposta"


def test_aguardar_aprovacao_nao_abandona(tmp_path):
    """Scenario: Aguardar aprovação não abandona."""
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: {})
    outcome = c.run([sub("treinar_rf", approach=RF)])
    (hs,) = c.system_hypotheses()
    assert outcome.dropped == {"treinar_rf": "hipotese_aguarda_aprovacao"}
    assert _props(c, hs.id)["status"] == "proposta"
    c.run([sub("treinar_rf", approach=RF)])  # o ciclo seguinte também a deixa pendente
    assert _props(c, hs.id)["status"] == "proposta"


def test_abandono_do_pesquisador_nao_reabre(tmp_path):
    """Scenario: Abandono do pesquisador não reabre."""
    c = LinkingCycle(tmp_path)
    hs = eg.hipotese(c.w, origem="sistema", enunciado="HSK", status="abandonada", abandonada_por="pesquisador")
    outcome = c.run([_plan_for("HSK")])
    assert outcome.dropped == {"treinar_x": "hipotese_equivalente_a_hipotese_abandonada"}
    assert _props(c, hs)["status"] == "abandonada"


def test_hipotese_com_tentativa_nao_e_abandonada_pelo_replanejamento(tmp_path):
    """Scenario: Hipótese do sistema com tentativa não é abandonada."""
    c = LinkingCycle(tmp_path)
    c.run([sub("treinar_svm", approach={"nome": "svm", "tipo": "algoritmo"})])
    (hs,) = c.system_hypotheses()
    c.w.store.update_node(hs.id, {"n_tentativas": 2}, actor=ORQ)
    c.run([sub("outra", approach=RF)])  # o plano novo não traz mais ``treinar_svm``
    assert _props(c, hs.id)["status"] != "abandonada"


# -- replanejamento ---------------------------------------------------------------------------------------------


def test_item_removido_da_fila(tmp_path):
    """Scenario: Item removido da fila (em ``removidas_pelo_replanejamento``, fora de ``retiradas_por_motivo``)."""
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: {})
    first = c.run([sub("treinar_svm", approach={"nome": "svm", "tipo": "algoritmo"})])
    assert first.dropped == {"treinar_svm": "hipotese_aguarda_aprovacao"}
    c.run([sub("outra", approach=RF)])
    event = c.events_of("hypothesis_cycle")[-1]
    assert event["removidas_pelo_replanejamento"] == ["treinar_svm"]
    assert "removida_pelo_replanejamento" not in event["retiradas_por_motivo"]


def test_hipotese_do_sistema_da_subtarefa_removida(tmp_path):
    """Scenario: Hipótese do sistema da subtarefa removida."""
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: {})
    c.run([sub("treinar_svm", approach={"nome": "svm", "tipo": "algoritmo"})])
    (hs3,) = c.system_hypotheses()
    c.run([sub("outra", approach=RF)])
    props = _props(c, hs3.id)
    assert props["status"] == "abandonada" and props["abandonada_por"] == "sistema"
    assert props["motivo_abandono"] == "removida_pelo_replanejamento"
    assert c.events_of("hypothesis_cycle")[-1]["hipoteses_sistema_abandonadas"] == 1


def test_subtarefa_retirada_pela_governanca_abandona_a_hipotese_sem_tentativa(tmp_path):
    """Retirada por dependência de subtarefa rejeitada: a única origem saiu, a hipótese do sistema é abandonada."""
    c = LinkingCycle(tmp_path, mode="auto")
    h = c.w.hypothesis("rejeitada", status="abandonada", abandonada_por="pesquisador")
    c.run([sub("base", hypothesis_ref=h), sub("depois", approach=RF, depends_on=["base"])],
          [{"ref": h, "id": h, "enunciado": "x", "justificativa": "j"}])
    (hs,) = c.system_hypotheses()
    assert _props(c, hs.id)["status"] == "abandonada" and _props(c, hs.id)["motivo_abandono"] == "subtarefa_retirada"


# -- aprovação por modo -----------------------------------------------------------------------------------------


def test_assistido_a_hipotese_do_sistema_aguarda_o_pesquisador(tmp_path):
    """Scenario: Assistido (o item tem ``origem = sistema``)."""
    seen = []
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: seen.extend(items) or {})
    outcome = c.run([sub("treinar_rf", approach=RF)])
    assert outcome.dropped == {"treinar_rf": "hipotese_aguarda_aprovacao"}
    assert [i.origem for i in seen] == ["sistema"]


def test_aprovacao_pelo_gate_persistente(tmp_path):
    """Scenario: Aprovação pelo gate persistente (pedido ``aprovar_hipotese``; ``terminal_approver`` não é chamado)."""
    terminal = MagicMock()
    gate = FakeGate(terminal_approver=terminal)
    c = LinkingCycle(tmp_path, mode="assisted", approver=gate)
    outcome = c.run([sub("treinar_rf", approach=RF)])
    (hs,) = c.system_hypotheses()
    assert [r.referencia for r in gate.pending()] == [hs.id] and gate.pending()[0].decisao == "aprovar_hipotese"
    assert outcome.dropped == {"treinar_rf": "hipotese_aguarda_aprovacao"} and terminal.call_count == 0
    gate.answer(gate.pending()[0].id, source="terminal", estado="autorizada")
    again = c.run([sub("treinar_rf", approach=RF)])
    assert "treinar_rf" in {t.task_name for t in again.tasks} and again.dropped == {}
    assert terminal.call_count == 0 and _props(c, hs.id)["status"] == "em_teste"


def test_automatico_nao_chama_o_aprovador(tmp_path):
    """Scenario: Automático."""
    approver = MagicMock()
    c = LinkingCycle(tmp_path, mode="auto", approver=approver)
    outcome = c.run([sub("treinar_rf", approach=RF)])
    (hs,) = c.system_hypotheses()
    assert hs.id in outcome.selection.execute and _props(c, hs.id)["status"] == "em_teste"
    assert approver.call_count == 0


def test_fonte_do_enunciado_mostrada_no_assistido(tmp_path):
    """Scenario: Fonte mostrada no assistido (o item traz ``origem`` e ``enunciado_fonte``)."""
    seen = []
    c = LinkingCycle(tmp_path, mode="assisted", approver=lambda items: seen.extend(items) or {})
    c.run([sub("treinar_rf", approach=RF, hypothesis="random forest melhora a acuracia")])
    assert [(i.origem, i.enunciado_fonte) for i in seen] == [("sistema", "texto_livre")]


def test_metric_ref_le_nome_e_sinonimos(tmp_path):
    c = LinkingCycle(tmp_path)
    ref = metric_ref(c.w.store.get_node(c.w.graph.metrica))
    assert ref.nome == "acuracia" and set(ref.sinonimos) == {"accuracy", "test_accuracy"}
