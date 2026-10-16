"""Gate persistente contra o PostgreSQL real (persistent-human-gate 1.1, 1.5, 2.1, 2.6): dois "processos" (sessão e terminal)."""

from __future__ import annotations

import psycopg
import pytest

from src.gate.persistent_gate import PersistentGate, TerminalGate
from src.gate.types import (
    GateAlreadyResolved,
    GateAuthorizationRefused,
    GateInvalidRequest,
    GatePendingLimitReached,
    Source,
)
from src.knowledge.gate_approver import OPCOES, PersistentGateApprover
from src.knowledge.hypothesis_cycle import ApprovalItem
from tests.support.pg import MIGRATIONS_V187, pg_db, skip_if_no_postgres, temp_database_url  # noqa: F401

pytestmark = [pytest.mark.integration, skip_if_no_postgres]

CHAIN = ["sessao-a"]
AUTORIZAR_NEGAR = ("autorizar", "negar")


def test_migracao_do_gate_aplicada_duas_vezes(temp_database_url):  # noqa: F811
    with psycopg.connect(temp_database_url, autocommit=True) as conn:
        for migration in MIGRATIONS_V187:
            conn.execute(migration.read_text(encoding="utf-8"))
        tables = {r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()}
    assert {"gate_requests", "session_inbox"} <= tables


def test_pedido_idempotente_e_unico_pendente(pg_db):  # noqa: F811
    session, terminal = PersistentGate(), TerminalGate()
    first = session.request("aprovar_hipotese", "h1", "Aprovar h1?", OPCOES, session_id="sessao-a")
    assert session.request("aprovar_hipotese", "h1", "Aprovar h1?", OPCOES, session_id="sessao-a").id == first.id
    assert [r.id for r in terminal.pending()] == [first.id]
    assert terminal.get(first.id).opcoes == OPCOES


def test_so_o_terminal_resolve_e_a_segunda_resposta_e_recusada(pg_db):  # noqa: F811
    """Scenario: pedido já resolvido recusado; fonte não humana ignorada (caso 13, na camada da aplicação)."""
    session, terminal = PersistentGate(), TerminalGate()
    assert not hasattr(session, "answer")  # a sessão não tem como responder
    req = session.request("aprovar_oportunidade", "o1", "Aprovar?", AUTORIZAR_NEGAR, session_id="sessao-a")
    for source in (Source.ASK_RESEARCHER, Source.RESEARCHER_CONSULT, Source.AGENT, Source.DOCUMENT):
        assert terminal.answer(req.id, source=source, approved=True).estado == "pendente"
    assert terminal.answer(req.id, source="terminal", approved=True).estado == "pendente"  # string solta não vale
    done = terminal.answer(req.id, source=Source.TERMINAL, approved=True)
    assert (done.estado, done.resolvido_por, done.resposta) == ("autorizada", "terminal", {"acao": "autorizar"})
    with pytest.raises(GateAlreadyResolved):
        terminal.answer(req.id, source=Source.CLI, approved=False)
    assert terminal.get(req.id).estado == "autorizada"


def test_resposta_fora_das_opcoes_e_recusada_no_banco_real(pg_db):  # noqa: F811
    session, terminal = PersistentGate(), TerminalGate()
    req = session.request(
        "decidir_continuidade", "x:saturacao", "Continuar?", ("continuar", "parar"),
        motivo="saturacao", session_id="sessao-a",
    )
    with pytest.raises(GateInvalidRequest):
        terminal.answer(req.id, source=Source.TERMINAL, resposta={"acao": "orientar", "orientacao": "x"})
    assert terminal.get(req.id).estado == "pendente"
    got = terminal.answer(req.id, source=Source.TERMINAL, resposta={"acao": "parar"})
    assert got.estado == "autorizada" and got.resposta == {"acao": "parar"}


def test_consumo_de_uso_unico_preso_ao_objeto_e_a_sessao(pg_db):  # noqa: F811
    """Scenarios: reuso recusado, autorização de outra sessão, modo sem limite preso ao lançamento e consumido uma vez."""
    session, terminal = PersistentGate(), TerminalGate()
    req = session.request("ativar_modo_sem_limite", "launch-1", "Ativar?", AUTORIZAR_NEGAR)  # terminal, sem sessão
    with pytest.raises(GateAuthorizationRefused) as err:
        session.consume_authorized("ativar_modo_sem_limite", "launch-1", [])
    assert err.value.motivo == "nao_autorizada"
    terminal.answer(req.id, source=Source.TERMINAL, approved=True)
    with pytest.raises(GateAuthorizationRefused) as err:
        session.consume_authorized("ativar_modo_sem_limite", "launch-1", CHAIN)  # a sessão não aceita pedido da CLI
    assert err.value.motivo == "outra_sessao"
    with pytest.raises(GateAuthorizationRefused) as err:
        session.consume_authorized("ativar_modo_sem_limite", "launch-2", [])
    assert err.value.motivo == "nao_encontrada"
    assert session.consume_authorized("ativar_modo_sem_limite", "launch-1", []).consumido is True
    with pytest.raises(GateAuthorizationRefused) as err:
        session.consume_authorized("ativar_modo_sem_limite", "launch-1", [])
    assert err.value.motivo == "ja_consumida"


def test_autorizacao_de_outra_sessao_e_recusada(pg_db):  # noqa: F811
    session, terminal = PersistentGate(), TerminalGate()
    req = session.request("aprovar_hipotese", "h1", "p", OPCOES, session_id="sessao-b")
    terminal.answer(req.id, source=Source.TERMINAL, resposta={"acao": "aprovar"})
    with pytest.raises(GateAuthorizationRefused) as err:
        session.consume_authorized("aprovar_hipotese", "h1", CHAIN)
    assert err.value.motivo == "outra_sessao"
    assert session.consume_authorized("aprovar_hipotese", "h1", ["sessao-b"]).id == req.id


def test_pedido_respondido_com_a_sessao_fora_e_aplicado_na_retomada(pg_db):  # noqa: F811
    session, terminal = PersistentGate(), TerminalGate()
    pending = session.request("responder_pergunta_agente", "t1", "Qual a semente?", (), session_id="sessao-a")
    other = session.request("aprovar_hipotese", "h9", "p", OPCOES, session_id="sessao-a")
    terminal.answer(pending.id, source=Source.TERMINAL, resposta={"texto": "42"})
    chain = ["sessao-a", "sessao-b"]  # a retomada lê a cadeia inteira
    assert [r.id for r in session.answered_unconsumed(chain)] == [pending.id]
    assert [r.id for r in session.pending(chain)] == [other.id]
    assert session.answered_unconsumed(chain)[0].resposta == {"acao": "responder", "texto": "42"}
    assert session.mark_consumed(pending.id) is True and session.mark_consumed(pending.id) is False
    assert session.answered_unconsumed(chain) == []
    assert session.mark_obsolete(other.id) is True and session.pending(chain) == []


def test_teto_de_pedidos_pendentes_por_sessao(pg_db, monkeypatch):  # noqa: F811
    from src import config

    monkeypatch.setattr(config, "GATE_MAX_PENDING_PER_SESSION", 2)
    session = PersistentGate()
    session.request("aprovar_hipotese", "h1", "p", OPCOES, session_id="sessao-a")
    session.request("aprovar_hipotese", "h2", "p", OPCOES, session_id="sessao-a")
    with pytest.raises(GatePendingLimitReached):
        session.request("aprovar_hipotese", "h3", "p", OPCOES, session_id="sessao-a")
    session.request("aprovar_hipotese", "h1", "p", OPCOES, session_id="sessao-a")  # idempotente: não conta como novo
    session.request("aprovar_hipotese", "h1", "p", OPCOES, session_id="sessao-b")  # outra sessão: outro teto


def test_texto_do_pedido_e_sanitizado_e_limitado(pg_db, monkeypatch):  # noqa: F811
    from src import config

    monkeypatch.setattr(config, "GATE_QUESTION_MAX_CHARS", 30)
    req = PersistentGate().request("aprovar_hipotese", "h1", "a\x1b[31m" + "b" * 100, OPCOES, session_id="sessao-a")
    assert "\x1b" not in req.pergunta and len(req.pergunta) <= 30


def test_leitura_sem_consumo_do_adendo(pg_db):  # noqa: F811
    session, terminal = PersistentGate(), TerminalGate()
    req = session.request("ativar_adendo_regimento", "sha-abc", "Ativar o adendo?", AUTORIZAR_NEGAR, session_id="sessao-a")
    assert session.authorized_reference("ativar_adendo_regimento", "sha-abc") is False
    terminal.answer(req.id, source=Source.CLI, approved=True)
    assert session.authorized_reference("ativar_adendo_regimento", "sha-abc") is True
    assert session.authorized_reference("ativar_adendo_regimento", "sha-abc") is True
    assert session.get(req.id).consumido is False


def test_aprovador_de_ponta_a_ponta_com_dois_processos(pg_db):  # noqa: F811
    """Scenario: aprovação, rejeição e edição de hipótese pelo gate persistente."""
    terminal = TerminalGate()
    approver = PersistentGateApprover(PersistentGate(), "sessao-a", CHAIN)
    items = [ApprovalItem(h, f"Hipótese {h}", "J", "agente", 0.5) for h in ("h1", "h2", "h3", "h4")]
    assert approver(items) == {}
    by_ref = {r.referencia: r for r in terminal.pending(CHAIN)}
    terminal.answer(by_ref["h1"].id, source=Source.TERMINAL, resposta={"acao": "aprovar"})
    terminal.answer(by_ref["h2"].id, source=Source.TERMINAL, resposta={"acao": "rejeitar", "motivo": "fora do escopo"})
    terminal.answer(by_ref["h3"].id, source=Source.TERMINAL, resposta={"acao": "editar", "enunciado": "Novo texto"})
    decisions = approver(items)
    assert set(decisions) == {"h1", "h2", "h3"}  # h4 segue pendente
    assert decisions["h1"].action == "aprovar" and decisions["h2"].motivo == "fora do escopo"
    assert (decisions["h3"].action, decisions["h3"].enunciado) == ("editar", "Novo texto")
    assert approver(items) == {}  # consumidas
    assert approver.previously_approved("h1", CHAIN) is True
    assert approver.previously_approved("h2", CHAIN) is False  # rejeitada não conta como aprovada
