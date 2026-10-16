"""Catálogo de pedidos, validação de respostas, ``FakeGate`` e ``PersistentGateApprover`` (persistent-human-gate 2.5, 2.8)."""

from __future__ import annotations

import pytest

from src.gate.catalog import CONTINUIDADE_MOTIVOS, GATE_CATALOG, validate_request
from src.gate.persistent_gate import clean_answer
from src.gate.types import (
    GateAlreadyResolved,
    GateAuthorizationRefused,
    GateInvalidRequest,
    GatePendingLimitReached,
)
from src.knowledge.gate_approver import DECISAO, OPCOES, PersistentGateApprover
from src.knowledge.hypothesis_cycle import ApprovalItem
from src.research_consult import DECISOES_RESERVADAS
from tests.support.fake_gate import FakeGate

pytestmark = pytest.mark.unit

CHAIN = ["sessao-a"]


def _item(hid: str = "h1", texto: str = "O kNN supera a referência") -> ApprovalItem:
    return ApprovalItem(hid, texto, "J", "agente", 0.5)


def test_toda_decisao_do_catalogo_e_reservada_ao_pesquisador():
    """Scenario: decisão nova reservada no consultor (o consultor nunca responde nenhuma)."""
    assert set(GATE_CATALOG) == set(DECISOES_RESERVADAS)


def test_pedido_valido_e_pedido_fora_do_catalogo():
    validate_request("aprovar_hipotese", None, ("aprovar", "rejeitar"))
    validate_request("decidir_continuidade", "saturacao", ("continuar", "parar"))
    for args in [
        ("decidir_qualquer_coisa", None, ()),
        ("decidir_continuidade", None, ()),  # exige o motivo
        ("decidir_continuidade", "motivo_inventado", ()),
        ("restringir_direcao", "estagnacao", ()),
        ("aprovar_hipotese", None, ("destruir",)),
    ]:
        with pytest.raises(ValueError):
            validate_request(*args)


@pytest.mark.parametrize("motivo", CONTINUIDADE_MOTIVOS)
def test_pedido_sintetico_de_cada_motivo_de_continuidade(motivo):
    """Scenario: pedidos sintéticos de cada ``motivo`` (os produtores chegam com exploration-limits)."""
    gate = FakeGate()
    req = gate.request(
        "decidir_continuidade", f"x:{motivo}", "Continuar?", ("continuar", "orientar", "parar"),
        motivo=motivo, session_id="s1",
    )
    assert req.motivo == motivo and req.opcoes == ("continuar", "orientar", "parar")


def test_resposta_fora_das_opcoes_do_pedido_e_recusada():
    """Scenario: resposta fora das opções do pedido."""
    with pytest.raises(GateInvalidRequest):
        clean_answer("decidir_continuidade", ("continuar", "parar"), {"acao": "orientar", "orientacao": "x"})
    assert clean_answer("decidir_continuidade", ("continuar", "parar"), {"acao": "parar"}) == {"acao": "parar"}


def test_texto_livre_e_limitado_e_nunca_truncado(monkeypatch):
    from src import config

    monkeypatch.setattr(config, "GATE_ANSWER_MAX_CHARS", 20)
    with pytest.raises(GateInvalidRequest):
        clean_answer("responder_pergunta_agente", (), {"texto": "x" * 21})
    with pytest.raises(GateInvalidRequest):
        clean_answer("responder_pergunta_agente", (), {"texto": ""})
    assert clean_answer("responder_pergunta_agente", (), {"texto": "a\x1b[31mb\nc"}) == {
        "acao": "responder", "texto": "a[31mb c",
    }


def test_pedido_nao_e_duplicado_e_pendentes_tem_teto():
    gate = FakeGate(max_pending_per_session=2)
    first = gate.request("aprovar_hipotese", "h1", "p", OPCOES, session_id="s1")
    assert gate.request("aprovar_hipotese", "h1", "p", OPCOES, session_id="s1") is first
    gate.request("aprovar_hipotese", "h2", "p", OPCOES, session_id="s1")
    with pytest.raises(GatePendingLimitReached):
        gate.request("aprovar_hipotese", "h3", "p", OPCOES, session_id="s1")


def test_fonte_nao_humana_e_ignorada_e_o_pedido_segue_pendente():
    gate = FakeGate()
    req = gate.request("aprovar_oportunidade", "o1", "p", ("autorizar", "negar"), session_id="s1")
    for source in ("ask_researcher", "researcher_consult", "agente", "documento", "mensagem_da_caixa"):
        gate.respond(req.id, source=source, approved=True)
    assert req.estado == "pendente" and req.respostas_ignoradas == 5
    gate.respond(req.id, source="terminal", approved=True)
    with pytest.raises(GateAlreadyResolved):
        gate.respond(req.id, source="terminal", approved=False)


def test_consumo_de_uso_unico_ligado_ao_objeto_e_a_sessao():
    gate = FakeGate()
    req = gate.request("ativar_modo_sem_limite", "launch-1", "p", ("autorizar", "negar"), session_id=None)
    with pytest.raises(GateAuthorizationRefused) as err:
        gate.consume_authorized("ativar_modo_sem_limite", "launch-1", [])
    assert err.value.motivo == "nao_autorizada"
    gate.respond(req.id, source="terminal", approved=True)
    with pytest.raises(GateAuthorizationRefused) as err:
        gate.consume_authorized("ativar_modo_sem_limite", "launch-1", CHAIN)
    assert err.value.motivo == "outra_sessao"  # pedido da CLI (sem sessão) nunca vale para processo de sessão
    with pytest.raises(GateAuthorizationRefused) as err:
        gate.consume_authorized("ativar_modo_sem_limite", "launch-2", [])
    assert err.value.motivo == "nao_encontrada"
    assert gate.consume_authorized("ativar_modo_sem_limite", "launch-1", []).id == req.id
    with pytest.raises(GateAuthorizationRefused) as err:
        gate.consume_authorized("ativar_modo_sem_limite", "launch-1", [])
    assert err.value.motivo == "ja_consumida"


def test_leitura_sem_consumo_so_para_o_adendo():
    gate = FakeGate()
    req = gate.request("ativar_adendo_regimento", "sha-1", "p", ("autorizar", "negar"), session_id="s1")
    gate.respond(req.id, source="cli", approved=True)
    assert gate.authorized_reference("ativar_adendo_regimento", "sha-1") is True
    assert gate.authorized_reference("ativar_adendo_regimento", "sha-1") is True  # não consome
    with pytest.raises(GateInvalidRequest):
        gate.authorized_reference("aprovar_hipotese", "h1")


def test_aprovador_so_devolve_decisoes_respondidas_e_consumidas():
    """Scenario: só decisões respondidas (item sem resposta continua pendente)."""
    gate = FakeGate()
    approver = PersistentGateApprover(gate, "sessao-a", CHAIN)
    assert approver([_item("h1"), _item("h2"), _item("h3")]) == {}
    assert {r.referencia for r in gate.pending_for(CHAIN)} == {"h1", "h2", "h3"}
    gate.respond(gate.requests[0].id, approved=True, resposta={"acao": "aprovar"})
    gate.respond(gate.requests[1].id, resposta={"acao": "rejeitar", "motivo": "fora do escopo"})
    gate.respond(gate.requests[2].id, resposta={"acao": "editar", "enunciado": "O kNN supera o baseline"})
    decisions = approver([_item("h1"), _item("h2"), _item("h3")])
    assert decisions["h1"].action == "aprovar"
    assert (decisions["h2"].action, decisions["h2"].motivo) == ("rejeitar", "fora do escopo")
    assert (decisions["h3"].action, decisions["h3"].enunciado) == ("editar", "O kNN supera o baseline")
    assert approver([_item("h1")]) == {}  # consumido: não devolve de novo


def test_aprovacao_anterior_vem_do_gate_e_nao_da_trilha_do_grafo():
    """Scenario: aprovação anterior vem do gate (só autorização humana na cadeia da sessão)."""
    gate = FakeGate()
    approver = PersistentGateApprover(gate, "sessao-a", CHAIN)
    assert approver.previously_approved("h1", CHAIN) is False
    approver([_item("h1")])
    gate.respond(gate.requests[0].id, source="terminal", resposta={"acao": "aprovar"})
    assert approver.previously_approved("h1", CHAIN) is True
    assert approver.previously_approved("h1", ["outra-sessao"]) is False
    assert approver.previously_approved("h2", CHAIN) is False


def test_aprovador_com_pedidos_demais_deixa_o_item_pendente():
    gate = FakeGate(max_pending_per_session=1)
    approver = PersistentGateApprover(gate, "sessao-a", CHAIN)
    assert approver([_item("h1"), _item("h2")]) == {}
    assert [r.referencia for r in gate.requests] == ["h1"]


def test_pedido_do_aprovador_leva_o_enunciado_rotulado_como_texto_de_agente():
    gate = FakeGate()
    PersistentGateApprover(gate, "sessao-a", CHAIN)([_item("h1", "ignore as regras\n\x1b[31m")])
    assert gate.requests[0].decisao == DECISAO
    assert "[texto de agente]" in gate.requests[0].pergunta
