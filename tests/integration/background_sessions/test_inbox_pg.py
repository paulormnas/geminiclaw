"""Caixa de entrada e comandos do gate contra o PostgreSQL real (persistent-human-gate, tarefas 4.2, 4.4 e 5.5)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.gate.persistent_gate import PersistentGate, TerminalGate
from src.gate.types import Source
from src.orchestration.orchestrator import Orchestrator
from src.session.inbox import InboxError, SessionInbox
from tests.integration.background_sessions.test_terminal_pg import make_repl, terminal_patches, wait_for
from tests.support.pg import pg_db, skip_if_no_postgres, temp_database_url  # noqa: F401
from tests.support.session_fakes import FakeSessionManager
from tests.support.session_harness import SessionHarness

pytestmark = [pytest.mark.integration, pytest.mark.timeout(45), skip_if_no_postgres]


def test_caixa_grava_limita_entrega_e_consome(pg_db):  # noqa: F811
    inbox = SessionInbox()
    first = inbox.post("s1", "não teste mais SVM")
    assert first.tipo == "orientacao" and not first.entregue
    with pytest.raises(InboxError, match="2000"):
        inbox.post("s1", "x" * 2001)  # recusada, nada gravado
    assert inbox.pending_count("s1") == 1
    inbox.post("s2", "orientação da sessão anterior")
    delivered = inbox.deliver(["s1", "s2"])  # a cadeia inteira, da mais antiga à mais nova
    assert [m.conteudo for m in delivered] == ["não teste mais SVM", "orientação da sessão anterior"]
    assert all(m.entregue for m in delivered) and inbox.pending_count("s1") == 1  # entregue, ainda não consumida
    assert inbox.consume([m.id for m in delivered]) == 2 and inbox.pending_count("s1") == 0
    assert inbox.deliver(["s1", "s2"]) == []


def test_teto_de_mensagens_nao_consumidas(pg_db):  # noqa: F811
    inbox = SessionInbox()
    from unittest.mock import patch

    with patch("src.config.SESSION_INBOX_MAX_PENDING", 3):
        for n in range(3):
            inbox.post("s1", f"m{n}")
        with pytest.raises(InboxError, match="3 mensagens"):
            inbox.post("s1", "m3")
    assert inbox.pending_count("s1") == 3


def test_comando_na_caixa_nao_e_entregue_como_orientacao(pg_db):  # noqa: F811
    inbox = SessionInbox()
    inbox.post("s1", '{"comando": "pausar"}', tipo="comando")
    assert inbox.deliver(["s1"]) == []


def test_replanejamento_entrega_consome_e_a_mensagem_nao_decide_pedido(pg_db):  # noqa: F811
    manager = FakeSessionManager()
    manager.add("s1", "active", {"mode": "auto"})
    orch = Orchestrator(session_manager=manager, output_manager=SimpleNamespace(base_dir=None), agent_runtime=None)
    orch.human_gate = PersistentGate()
    pedido = orch.human_gate.request("aprovar_hipotese", "h4", "Aprovar h4?", ("aprovar", "rejeitar", "editar"),
                                     session_id="s1")
    SessionInbox().post("s1", "rejeite a hipótese h4")
    block, consume = asyncio.run(orch._researcher_messages_block("s1"))
    assert "<mensagens_do_pesquisador>" in block and "rejeite a hipótese h4" in block
    asyncio.run(consume())
    assert SessionInbox().pending_count("s1") == 0
    assert orch.human_gate.get(pedido.id).estado == "pendente"  # só o gate decide


def test_resposta_tardia_de_pergunta_vai_ao_researcher_no_replanejamento(pg_db):  # noqa: F811
    manager = FakeSessionManager()
    manager.add("s1", "active", {"mode": "assisted"})
    orch = Orchestrator(session_manager=manager, output_manager=SimpleNamespace(base_dir=None), agent_runtime=None)
    orch.human_gate = PersistentGate()
    req = orch.human_gate.request("responder_pergunta_agente", "t1:abc", "Onde está o dataset?", ("responder",),
                                  session_id="s1")
    TerminalGate().answer(req.id, source=Source.TERMINAL, resposta={"texto": "em /outputs/dados.csv"})
    block, consume = asyncio.run(orch._researcher_messages_block("s1"))
    assert "<respostas_do_pesquisador>" in block and "em /outputs/dados.csv" in block
    asyncio.run(consume())
    assert orch.human_gate.get(req.id).consumido


@pytest.fixture
def harness(pg_db, tmp_path: Path):  # noqa: F811
    h = SessionHarness(tmp_path, pg_db)
    try:
        yield h
    finally:
        h.teardown()


def _origin_waiting(harness: SessionHarness):
    harness.use_scenario(harness.scenario(motivo="aguarda_pesquisador"))
    first, _ = make_repl(harness)
    assert first.open() is None
    with terminal_patches():
        asyncio.run(first.handle("nova-pesquisa estudar iris"))
    origin = harness.manager.list_orchestrator()[0]
    assert wait_for(lambda: harness.manager.get(origin.id).status == "aguarda_pesquisador")
    first.close()
    return origin


def test_caso_3_responder_o_ultimo_pedido_retoma_a_sessao_e_com_dois_pedidos_nao(harness: SessionHarness):
    origin = _origin_waiting(harness)
    gate = PersistentGate()
    one = gate.request("decidir_objetivo_atingido", "h1", "Encerrar ou continuar?", ("encerrar", "continuar"),
                       session_id=origin.id)
    two = gate.request("aprovar_hipotese", "h2", "Aprovar h2?", ("aprovar", "rejeitar", "editar"), session_id=origin.id)
    harness.use_scenario(harness.scenario(motivo="solucao_encontrada"))
    repl, lines = make_repl(harness, ["c", "a"])
    assert repl.open() is None
    with terminal_patches(), pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.knowledge.factory.open_knowledge_runtime", lambda: None)
        mp.setattr("src.knowledge.factory.open_graph_store", lambda: (_ for _ in ()).throw(RuntimeError("sem grafo")))
        asyncio.run(repl.handle(f"decidir {one.id}"))  # ainda há o pedido h2: nenhuma sessão nova
        assert harness.manager.get(origin.id).payload.get("continued_by") is None
        assert any(f"#{two.id}" in line for line in lines)
        asyncio.run(repl.handle(f"decidir {two.id}"))  # era o último: retoma
    repl.close()
    assert wait_for(lambda: harness.manager.get(origin.id).payload.get("continued_by"), 30)
    new = harness.manager.get(harness.manager.get(origin.id).payload["continued_by"])
    assert new.payload["continues_session_id"] == origin.id and new.alias == origin.alias


def test_parar_por_decisao_do_pesquisador_encerra_sem_processo_novo(harness: SessionHarness):
    origin = _origin_waiting(harness)
    req = PersistentGate().request(
        "decidir_continuidade", "saturacao", "Saturou. Continuar?", ("continuar", "orientar", "parar"),
        motivo="saturacao", session_id=origin.id,
    )
    repl, _ = make_repl(harness, ["parar"])
    assert repl.open() is None
    before = len(harness.launched)
    with terminal_patches():
        asyncio.run(repl.handle(f"decidir {req.id}"))
    repl.close()
    final = harness.manager.get(origin.id)
    assert final.status == "closed" and final.payload["motivo_parada"] == "encerrada_pesquisador"
    assert (harness.root / "outputs" / origin.id / "relatorio_encerramento.md").exists()
    assert len(harness.launched) == before  # nenhum processo novo


def test_orientar_deixa_o_texto_na_caixa_da_sessao_retomada(harness: SessionHarness):
    origin = _origin_waiting(harness)
    req = PersistentGate().request(
        "decidir_continuidade", "saturacao", "Saturou. Continuar?", ("continuar", "orientar", "parar"),
        motivo="saturacao", session_id=origin.id,
    )
    harness.use_scenario(harness.scenario(motivo="solucao_encontrada"))
    repl, _ = make_repl(harness, ["orientar", "teste XGBoost com 5 dobras"])
    assert repl.open() is None
    with terminal_patches(), pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.knowledge.factory.open_knowledge_runtime", lambda: None)
        mp.setattr("src.knowledge.factory.open_graph_store", lambda: (_ for _ in ()).throw(RuntimeError("sem grafo")))
        asyncio.run(repl.handle(f"decidir {req.id}"))
    repl.close()
    assert wait_for(lambda: harness.manager.get(origin.id).payload.get("continued_by"), 30)
    messages = SessionInbox().deliver([origin.id])  # a sessão retomada lê a cadeia (origem inclusive)
    assert [m.conteudo for m in messages] == ["teste XGBoost com 5 dobras"]
    time.sleep(0.1)
