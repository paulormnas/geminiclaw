"""Varredura de sessões paradas e encerramento pelo pesquisador (v18.7-background-sessions, tarefas 5.1, 5.4 e 5.5)."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.session.closing import REPORT_NAME, close_by_researcher, render_closing_report
from src.session.continuity import Checkpoint, SubtaskState, read_checkpoint, write_checkpoint
from src.session.watch import SessionWatch
from tests.support.fake_clock import FakeClock
from tests.support.session_fakes import FakeSessionManager

pytestmark = pytest.mark.unit

HOST = "este-host"
START = FakeClock().now()  # início do processo nos cenários (a hora inicial do FakeClock)


def _iso(clock: FakeClock, offset: float = 0.0) -> str:
    return clock.iso(offset)


def _active(manager, clock, sid="a-01", *, pid=100, host=HOST, updated=0.0, beat=0.0, started=0.0):
    sess = manager.add(sid, "active", {"mode": "auto"})
    sess.pid, sess.host, sess.alias = pid, host, sid
    sess.updated_at, sess.loop_beat_at, sess.process_started_at = (
        _iso(clock, updated), _iso(clock, beat), _iso(clock, started)
    )
    return sess


def _watch(manager, clock, *, create_time=None, recover=None, **kw):
    return SessionWatch(
        manager, recover=recover, host=HOST, clock=clock.now, stale_seconds=300, loop_stale_seconds=900,
        create_time=create_time or (lambda pid: START), **kw,
    )


def test_processo_vivo_com_batimento_recente_nao_e_marcado():
    clock, manager = FakeClock(), FakeSessionManager()
    sess = _active(manager, clock)
    assert _watch(manager, clock).sweep() == []
    assert sess.status == "active"


def test_processo_morto_com_sigkill_vira_interrompida_e_chama_a_recuperacao():
    clock, manager = FakeClock(), FakeSessionManager()
    _active(manager, clock)
    recovered = []
    marked = _watch(manager, clock, create_time=lambda pid: None, recover=recovered.append).sweep()
    assert [s.id for s in marked] == ["a-01"] and recovered == marked
    assert manager.get("a-01").status == "interrompida"
    assert manager.get("a-01").payload["motivo_parada"] == "interrompida"


def test_reuso_de_pid_e_marcado_interrompida():
    clock, manager = FakeClock(), FakeSessionManager()
    _active(manager, clock, started=0)
    watch = _watch(manager, clock, create_time=lambda pid: clock.now() + 3600)  # processo vivo, mas 1 h depois
    assert [s.id for s in watch.sweep()] == ["a-01"]


def test_outro_host_nao_confere_pid_so_batimento_e_laco():
    clock, manager = FakeClock(), FakeSessionManager()
    _active(manager, clock, host="outro-host")
    assert _watch(manager, clock, create_time=lambda pid: None).sweep() == []  # sem processo local, batimento recente
    clock.advance(301)
    assert [s.id for s in _watch(manager, clock, create_time=lambda pid: None).sweep()] == ["a-01"]


def test_laco_lento_nao_derruba_a_sessao_mas_laco_travado_sim():
    """Padrões 300/30/900: em t=400 s o batimento está fresco e o laço tem 400 s (lento); em 920 s está travado."""
    clock, manager = FakeClock(), FakeSessionManager()
    sess = _active(manager, clock)
    clock.advance(400)
    sess.updated_at = _iso(clock)  # o batimento (thread) segue atualizando updated_at; loop_beat_at ficou em t=0
    assert _watch(manager, clock).sweep() == [] and sess.status == "active"
    clock.advance(520)  # 920 s sem sinal do laço
    sess.updated_at = _iso(clock)  # batimento ainda recente
    assert [s.id for s in _watch(manager, clock).sweep()] == ["a-01"]


def test_batimento_que_chega_entre_a_leitura_e_a_escrita_impede_a_marcacao():
    clock, manager = FakeClock(), FakeSessionManager()
    sess = _active(manager, clock)
    clock.advance(400)
    watch = _watch(manager, clock, create_time=lambda pid: None)
    real_mark = manager.mark_interrupted

    def racing(session_id, expected):
        sess.updated_at = _iso(clock)  # um batimento chegou agora
        return real_mark(session_id, expected)

    manager.mark_interrupted = racing
    assert watch.sweep() == [] and sess.status == "active"


def test_falha_na_recuperacao_ou_na_leitura_nao_derruba_a_varredura():
    clock, manager = FakeClock(), FakeSessionManager()
    _active(manager, clock)

    def boom(_s):
        raise RuntimeError("grafo fora")

    assert len(_watch(manager, clock, create_time=lambda p: None, recover=boom).sweep()) == 1
    broken = MagicMock()
    broken.list_orchestrator.side_effect = RuntimeError("banco fora")
    assert SessionWatch(broken, host=HOST, clock=clock.now).sweep() == []


# -- encerramento (caso 9) -----------------------------------------------------------------------------------------


def _checkpoint(base: Path, sid: str) -> Checkpoint:
    cp = Checkpoint(session_id=sid, prompt_original="estudar iris", modo="auto", estado="interrompido",
                    motivo_parada="aguarda_pesquisador", consumo={"tokens": 123, "minutos": 4.5})
    cp.subtarefas = [
        SubtaskState(task_name="coleta", agent_id="researcher", status="concluida", resultado_resumo="dados lidos"),
        SubtaskState(task_name="modelo", agent_id="developer", status="pendente"),
    ]
    cp.hipoteses = [{"id": "h1", "enunciado": "R2 maior que 0,9", "status": "em_teste"}]
    write_checkpoint(base / sid, cp)
    return cp


def test_encerrar_grava_closed_relatorio_e_marca_o_curator_pendente(tmp_path: Path):
    manager = FakeSessionManager()
    sess = manager.add("b-01", "aguarda_pesquisador", {"mode": "semi", "motivo_parada": "aguarda_pesquisador"})
    sess.alias, sess.resumo = "b-01", "estudar iris"
    _checkpoint(tmp_path, "b-01")
    report = close_by_researcher(manager, tmp_path, sess)
    assert report == tmp_path / "b-01" / REPORT_NAME and report.exists()
    text = report.read_text(encoding="utf-8")
    assert "b-01" in text and "coleta" in text and "h1" in text and "123" in text
    assert "`aguarda_pesquisador`" in text  # o estado de antes do encerramento
    assert "Curator" in text
    assert manager.get("b-01").status == "closed"
    assert manager.get("b-01").payload["motivo_parada"] == "encerrada_pesquisador"
    cp, _ = read_checkpoint(tmp_path / "b-01")
    assert cp.curator_pendente is True and cp.motivo_parada == "encerrada_pesquisador" and cp.estado == "fechado"


def test_encerrar_sessao_que_voltou_a_active_nao_altera_nada(tmp_path: Path):
    manager = FakeSessionManager()
    sess = manager.add("b-01", "active", {"mode": "semi"})
    assert close_by_researcher(manager, tmp_path, sess) is None
    assert manager.get("b-01").status == "active" and not (tmp_path / "b-01" / REPORT_NAME).exists()


def test_encerrar_sem_checkpoint_ainda_grava_o_relatorio(tmp_path: Path):
    manager = FakeSessionManager()
    sess = manager.add("c-01", "interrompida", {"mode": "auto", "prompt": "tarefa"})
    report = close_by_researcher(manager, tmp_path, sess)
    assert "Sem checkpoint utilizável" in report.read_text(encoding="utf-8")


def test_relatorio_e_deterministico_e_nao_chama_llm():
    manager = FakeSessionManager()
    sess = manager.add("d-01", "suspensa_sem_pesquisador", {"mode": "assisted"})
    when = datetime.datetime(2026, 10, 16, tzinfo=datetime.timezone.utc).isoformat()
    assert render_closing_report(sess, None, when=when) == render_closing_report(sess, None, when=when)
