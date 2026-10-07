"""Detecção de paradas inesperadas e batimento (v18-research-continuity)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.continuity import CheckpointRecorder, plan_entry, read_checkpoint
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.projects import create_project
from src.orchestrator import AgentTask, Orchestrator
from src.output_manager import OutputManager
from src.session import SessionManager
from tests.support.session_fakes import FakeSessionManager

pytestmark = pytest.mark.unit


def _orch(tmp_path: Path, sm, store) -> Orchestrator:
    return Orchestrator(
        session_manager=sm,
        output_manager=OutputManager(str(tmp_path / "out"), str(tmp_path / "logs")),
        agent_runtime=MagicMock(),
        knowledge_store_factory=lambda: store,
    )


def _crashed_session(tmp_path: Path, sm: FakeSessionManager, orch: Orchestrator, pid: str | None):
    """Sessão com 1 subtarefa concluída e 1 em andamento, sem batimento há 1 h (queda de energia)."""
    sdir = orch.output_manager.init_session("sessao-queda")
    rec = CheckpointRecorder.start(
        sdir, session_id="sessao-queda", project_id=pid, continues_session_id=None, prompt="p", modo="auto"
    )
    rec.set_plan([
        plan_entry(AgentTask(agent_id="developer", prompt="a", task_name="coleta", subtask_id="s-1")),
        plan_entry(AgentTask(agent_id="developer", prompt="b", task_name="treino", subtask_id="s-2")),
    ])
    rec.subtask_finished("coleta", status="concluida", tentativas=1, resumo="ok")
    rec.subtask_started("treino", 1)
    sm.add("sessao-queda", "active", {"project_id": pid, "prompt": "p"} if pid else {"prompt": "p"},
           updated_delta=-3600)
    return sdir


@pytest.mark.asyncio
async def test_queda_de_energia(tmp_path):
    """Scenario: Queda de energia — sessão sem batimento vira `interrompida` e o que estava em andamento
    é registrado como falha de infraestrutura (também no grafo)."""
    store = InMemoryGraphStore()
    pid = create_project(store, "P", "O", [])
    sm = FakeSessionManager()
    orch = _orch(tmp_path, sm, store)
    sdir = _crashed_session(tmp_path, sm, orch, pid)
    sm.add("viva", "active", {}, updated_delta=-5)  # batimento recente: intocada

    recovered = await orch.recover_interrupted_sessions()

    assert recovered == ["sessao-queda"]
    assert sm.get("sessao-queda").status == "interrompida"
    assert sm.get("viva").status == "active"
    cp, _ = read_checkpoint(sdir)
    assert (cp.estado, cp.motivo_parada) == ("interrompido", "interrompida")
    assert cp.find("coleta").status == "concluida"
    treino = cp.find("treino")
    assert (treino.status, treino.causa_falha) == ("falhou", "infraestrutura")
    # grafo: Sessao interrompida e Experimento de falha por infraestrutura (categoria queda_de_energia)
    (sessao,) = store.find_nodes("Sessao", {"sessao_id": "sessao-queda"})
    assert sessao.properties["motivo_parada"] == "interrompida"
    (exp,) = store.find_nodes("Experimento", {"subtarefa_id": "s-2"})
    assert exp.properties["status"] == "falha"
    assert exp.properties["causa_falha"] == "infraestrutura"
    assert exp.properties["assinatura_falha"] == "interrupcao_inesperada"


@pytest.mark.asyncio
async def test_recuperacao_idempotente_e_sem_grafo_enfileira(tmp_path):
    sm = FakeSessionManager()

    def down():
        raise ConnectionError("grafo fora")

    orch = _orch(tmp_path, sm, InMemoryGraphStore())
    orch._knowledge_store_factory = down
    pid = "01890000-0000-7000-8000-000000000001"
    sdir = _crashed_session(tmp_path, sm, orch, pid)
    assert await orch.recover_interrupted_sessions() == ["sessao-queda"]
    assert await orch.recover_interrupted_sessions() == []  # já `interrompida`: nada a refazer
    kinds = [json.loads(line)["kind"] for line in (sdir / "knowledge_pending.jsonl").read_text().splitlines()]
    assert "session_end" in kinds and "subtask" in kinds  # reaplicável por `geminiclaw knowledge sync`
    cp, _ = read_checkpoint(sdir)
    assert cp.find("treino").status == "falhou"


@pytest.mark.asyncio
async def test_sessao_sem_checkpoint_e_marcada_sem_derrubar(tmp_path):
    sm = FakeSessionManager()
    orch = _orch(tmp_path, sm, InMemoryGraphStore())
    sm.add("antiga", "active", {}, updated_delta=-3600)
    assert await orch.recover_interrupted_sessions() == ["antiga"]
    assert sm.get("antiga").status == "interrompida"


def test_batimento_periodico_em_thread_independe_do_laco(tmp_path):
    """Batimento (I-5): a thread bate mesmo com o laço de eventos bloqueado e para ao ser interrompida."""
    import time

    from src.heartbeat import SessionHeartbeat

    calls: list[int] = []
    hb = SessionHeartbeat(lambda: calls.append(1) or True, interval=0.01).start()
    time.sleep(0.15)  # bloqueia a thread principal, como um laço de eventos parado
    hb.stop()
    n = len(calls)
    assert n >= 3
    time.sleep(0.05)
    assert len(calls) == n  # parou


def test_falso_positivo_de_obsolescencia_e_reafirmado(tmp_path):
    """I-5: sessão viva marcada `interrompida` por engano volta a `active` e perde o motivo herdado."""
    import time

    from src.heartbeat import SessionHeartbeat

    sm = FakeSessionManager()
    sm.add("viva", "active", {"prompt": "p"}, updated_delta=-3600)
    assert [s.id for s in sm.mark_stale(300)] == ["viva"]  # outro processo a marcou obsoleta
    assert sm.get("viva").payload["motivo_parada"] == "interrompida"
    hb = SessionHeartbeat(lambda: sm.heartbeat("viva"), lambda: sm.reassert_active("viva"), interval=0.01).start()
    time.sleep(0.1)
    hb.stop()
    assert sm.get("viva").status == "active"
    assert "motivo_parada" not in sm.get("viva").payload
    assert hb.reasserted == 1


# -- SessionManager (SQL) ----------------------------------------------------------------------


def _ctx(execute_result):
    conn = MagicMock()
    conn.execute.return_value = execute_result
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, conn


def test_heartbeat_atualiza_so_updated_at_de_sessao_ativa():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": "s1"}
    ctx, conn = _ctx(cursor)
    with patch("src.session.get_connection", return_value=ctx):
        assert SessionManager().heartbeat("s1") is True
    sql = conn.execute.call_args.args[0]
    assert "SET updated_at" in sql and "payload" not in sql and "status = 'active'" in sql
    cursor.fetchone.return_value = None
    with patch("src.session.get_connection", return_value=ctx):
        assert SessionManager().heartbeat("s1") is False


def test_mark_stale_e_atomico_e_condicional():
    row = {"id": "x", "agent_id": "orchestrator", "status": "interrompida",
           "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
           "payload": json.dumps({"motivo_parada": "interrompida"})}
    cursor = MagicMock()
    cursor.fetchall.return_value = [row]
    ctx, conn = _ctx(cursor)
    with patch("src.session.get_connection", return_value=ctx):
        out = SessionManager().mark_stale(300)
    sql, params = conn.execute.call_args.args
    assert "status = 'active'" in sql and "updated_at <" in sql and "agent_id = 'orchestrator'" in sql
    assert datetime.datetime.fromisoformat(params[2]) < datetime.datetime.now(datetime.timezone.utc)
    assert [s.id for s in out] == ["x"] and out[0].payload["motivo_parada"] == "interrompida"
