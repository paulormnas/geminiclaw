"""Eventos de progresso contra o PostgreSQL real (session-continuity 1.5; casos 1, 4 e 10 do ADR 023)."""

from __future__ import annotations

import time

import psycopg
import pytest

import src.session.events as events
from src.gate.persistent_gate import PersistentGate, set_created_hook
from src.session.events import EventReader, EventWriter, purge
from src.session.manager import SessionManager
from tests.support.pg import MIGRATIONS_V187, pg_db, skip_if_no_postgres, temp_database_url  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.timeout(15), skip_if_no_postgres]


@pytest.fixture(autouse=True)
def _limpa_escritores():
    events.reset_writers()
    yield
    events.reset_writers()
    set_created_hook(None)


def test_migracao_aplicada_duas_vezes(temp_database_url):  # noqa: F811
    with psycopg.connect(temp_database_url, autocommit=True) as conn:
        for migration in MIGRATIONS_V187:
            conn.execute(migration.read_text(encoding="utf-8"))
        assert conn.execute("SELECT to_regclass('session_events')").fetchone()[0] == "session_events"


def test_seq_sem_lacuna_e_ordem(pg_db):  # noqa: F811
    writer = EventWriter("s1")
    for i in range(5):
        writer.emit("subtarefa_iniciada", {"subtarefa": f"t{i}"})
    writer.close()
    lidos = EventReader().since(0, session_ids=["s1"])
    assert [e.seq for e in lidos] == [1, 2, 3, 4, 5]
    assert [e.resumo for e in lidos][0] == "t0 iniciada"
    assert [e.seq for e in EventReader().tail("s1", 2)] == [4, 5]
    assert EventReader().since(lidos[2].id, session_ids=["s1"])[0].seq == 4


def test_seq_continua_na_retomada_e_com_escritores_concorrentes(pg_db):  # noqa: F811
    EventWriter("s1").emit("sessao_iniciada", {"modo": "auto", "papeis": 1}, wait=True)
    outro_processo = EventWriter("s1")  # novo escritor (retomada ou terminal): o banco continua a contagem
    outro_processo.emit("falha", {"apelido": "a-01"}, wait=True)
    assert [e.seq for e in EventReader().tail("s1", 10)] == [1, 2]


def test_evento_final_antes_do_status(pg_db):  # noqa: F811
    """Scenario: Evento final antes do status (caso 1) e seq sem lacuna."""
    manager = SessionManager()
    session = manager.create("orchestrator")
    events.emit_event(session.id, "sessao_iniciada", {"modo": "auto", "papeis": 2}, wait=True)
    events.emit_event(session.id, "subtarefa_iniciada", {"subtarefa": "t"}, wait=True)
    final = manager.update(session.id, status="closed", payload={"motivo_parada": "solucao_encontrada"})
    lidos = EventReader().tail(session.id, 10)
    assert [e.seq for e in lidos] == [1, 2, 3]
    parada = lidos[-1]
    assert parada.tipo == "parada" and "solucao_encontrada" in parada.resumo
    assert parada.criado_em <= str(final.updated_at) or parada.criado_em[:19] <= str(final.updated_at)[:19]
    manager.update(session.id, status="closed")  # sem mudança de status: nenhum evento novo
    assert len(EventReader().tail(session.id, 10)) == 3


def test_suspensao_cita_o_terminal_fechado(pg_db):  # noqa: F811
    """Scenario: Suspensão (caso 4)."""
    manager = SessionManager()
    session = manager.create("orchestrator")
    manager.update(session.id, status="suspensa_sem_pesquisador", payload={"motivo_parada": "suspensa_sem_pesquisador"})
    (evento,) = EventReader().tail(session.id, 5)
    assert evento.tipo == "suspensao" and "terminal fechado" in evento.resumo


def test_sessao_de_agente_nao_gera_evento_final(pg_db):  # noqa: F811
    manager = SessionManager()
    agente = manager.create("developer")
    manager.update(agente.id, status="closed")
    assert EventReader().tail(agente.id, 5) == []


def test_falha_gravada_pelo_terminal(pg_db):  # noqa: F811
    """Scenario: Falha gravada pelo terminal (caso 10)."""
    manager = SessionManager()
    session = manager.create("orchestrator")
    manager.register_process(session.id, pid=999999, host="h", process_started_at=None, terminal_id=None,
                             alias="iris-01", resumo="r")
    atual = manager.get(session.id)
    marcada = manager.mark_interrupted(session.id, atual.updated_at)
    assert marcada is not None
    (evento,) = EventReader().tail(session.id, 5)
    assert evento.tipo == "falha" and "retomar iris-01" in evento.resumo


def test_pendente_aparece_ja_sem_flush_da_telemetria(pg_db):  # noqa: F811
    """Scenario: Pendente aparece já."""
    set_created_hook(lambda req: events.emit_event(req.session_id, "decisao_pendente", {
        "decisao": req.decisao, "pedido_id": req.id, "referencia": req.referencia,
    }))
    inicio = time.monotonic()
    pedido = PersistentGate().request("aprovar_hipotese", "h4", "Aprovar h4?", ("aprovar", "rejeitar", "editar"),
                                      session_id="s-pend")
    events.flush_all()
    lidos = EventReader().since(0, session_ids=["s-pend"])
    assert time.monotonic() - inicio < 1.0
    assert [e.tipo for e in lidos] == ["decisao_pendente"]
    assert f"decidir {pedido.id}" in lidos[0].resumo and "aprovar a hipótese h4" in lidos[0].resumo
    PersistentGate().request("aprovar_hipotese", "h4", "Aprovar h4?", ("aprovar", "rejeitar", "editar"),
                             session_id="s-pend")  # idempotente: não repete o evento
    events.flush_all()
    assert len(EventReader().since(0, session_ids=["s-pend"])) == 1


def test_retencao_zero_nao_apaga_e_30_apaga_so_a_terminada(pg_db):  # noqa: F811
    manager = SessionManager()
    fechada, aguardando = manager.create("orchestrator"), manager.create("orchestrator")
    manager.update(fechada.id, status="closed", payload={"motivo_parada": "solucao_encontrada"})
    manager.update(aguardando.id, status="aguarda_pesquisador", payload={"motivo_parada": "aguarda_pesquisador"})
    with psycopg.connect(pg_db, autocommit=True) as conn:
        conn.execute("UPDATE agent_sessions SET updated_at = now() - interval '400 days' WHERE id = ANY(%s)",
                     ([fechada.id, aguardando.id],))
    assert purge(0) == 0
    assert len(EventReader().tail(fechada.id, 5)) == 1
    assert purge(30) == 1
    assert EventReader().tail(fechada.id, 5) == []
    assert len(EventReader().tail(aguardando.id, 5)) == 1  # não finalizada: nunca apagada


def test_leitor_sem_sessoes_devolve_vazio_e_last_id(pg_db):  # noqa: F811
    assert EventReader().since(0, session_ids=[]) == []
    assert EventReader().last_id() == 0
    EventWriter("x").emit("parada", {"motivo": "erro"}, wait=True)
    assert EventReader().last_id() > 0


def test_processo_real_deixa_sessao_iniciada_e_parada_em_ordem(pg_db, tmp_path):  # noqa: F811
    """Scenario: Evento final antes do status, com o processo da sessão real (laço roteirizado, sem chamada paga)."""
    from tests.support.session_harness import SessionHarness

    harness = SessionHarness(tmp_path, pg_db)
    try:
        launched = harness.launch(scenario=harness.scenario(motivo="solucao_encontrada"))
        session = harness.wait_registered(launched)
        assert harness.wait_exit(launched) == 0
        final = harness.wait_status(session.id, ("closed", "success", "failed"))
    finally:
        harness.teardown()
    lidos = EventReader().tail(session.id, 20)
    assert [e.seq for e in lidos] == list(range(1, len(lidos) + 1))
    assert lidos[0].tipo == "sessao_iniciada" and "modo" in lidos[0].resumo
    assert lidos[-1].tipo == "parada" and "solucao_encontrada" in lidos[-1].resumo
    assert lidos[-1].criado_em[:19] <= str(final.updated_at)[:19]
