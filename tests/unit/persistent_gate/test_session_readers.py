"""Leitores do terminal dentro da sessão, agora pelo gate persistente (persistent-human-gate, tarefas 2.3, 2.4, 3.1-3.5)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.cli.session_process import SessionRunner
from src.cli.unlimited import confirm_unlimited
from src.gate.persistent_gate import session_gate, terminal_gate
from src.gate.types import Source
from src.knowledge.gate_approver import PersistentGateApprover, PersistentGateConfirmer
from src.knowledge.hypothesis_cycle import ApprovalDecision, ApprovalItem, SolutionStatus
from src.orchestration.exploration import ExplorationSession
from src.orchestration.orchestrator import AgentTask, Orchestrator
from src.orchestration.usage import UsageBudget, clear_suspension, request_suspension
from src.research_consult import PENDING_MESSAGE
from src.session.launcher import LaunchSpec
from tests.support.exploration_world import LoopHarness, hyp, plan, task
from tests.support.fake_gate import FakeGate
from tests.support.session_fakes import FakeSessionManager

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _flags():
    clear_suspension()
    with patch("src.config.GATE_POLL_SECONDS", 0.01), patch("src.config.CURATOR_ENABLED", False):
        yield
    clear_suspension()


def item(hid: str = "h1") -> ApprovalItem:
    return ApprovalItem(id=hid, enunciado="R2 > 0,9", origem="researcher", justificativa="j", prioridade=0.5)


# -- aprovador e confirmador (3.1) -----------------------------------------------------------------------------


def test_aprovador_na_retomada_reaproveita_o_pedido_respondido_da_sessao_anterior():
    gate = FakeGate()
    first = PersistentGateApprover(gate, "s1")
    first([item()])  # cria o pedido na sessão anterior (o pesquisador responde depois)
    (req,) = gate.requests
    gate.respond(req.id, resposta={"acao": "aprovar"})
    resumed = PersistentGateApprover(gate, "s2", ["s2", "s1"])
    decisions = resumed([item()])
    assert decisions == {"h1": ApprovalDecision("aprovar")}
    assert len(gate.requests) == 1  # nenhum pedido duplicado na sessão nova
    assert resumed([item()]) == {}  # uso único: já consumido


def test_aprovador_na_retomada_mantem_o_pedido_pendente_da_anterior_sem_duplicar():
    gate = FakeGate()
    PersistentGateApprover(gate, "s1")([item()])
    assert PersistentGateApprover(gate, "s2", ["s2", "s1"])([item()]) == {}
    assert len(gate.requests) == 1 and gate.requests[0].session_id == "s1"


def solution() -> SolutionStatus:
    return SolutionStatus(True, hypothesis_id="h1", verdict=0.8, best_value=0.93)


def test_confirmador_pendente_depois_respondido_e_de_uso_unico():
    gate = FakeGate()
    confirm = PersistentGateConfirmer(gate, "s1")
    assert confirm(solution()) is None  # cria o pedido e segue pendente
    (req,) = gate.requests
    assert req.decisao == "decidir_objetivo_atingido" and req.referencia == "h1" and req.opcoes == ("encerrar", "continuar")
    gate.respond(req.id, resposta={"acao": "encerrar"})
    assert confirm(solution()) == "encerrar"
    assert confirm(solution()) is None  # consumido


def test_confirmador_ignora_resposta_de_fonte_nao_humana():
    gate = FakeGate()
    confirm = PersistentGateConfirmer(gate, "s1")
    confirm(solution())
    gate.respond(gate.requests[0].id, source="agente", resposta={"acao": "encerrar"})
    assert confirm(solution()) is None and gate.requests[0].estado == "pendente"


# -- espera do assisted no laço (3.3 e 3.5) --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assisted_espera_a_resposta_e_continua_sem_contar_ocioso(tmp_path):
    gate = session_gate()
    calls: list[int] = []
    seen: dict[str, int] = {}

    def approver(items):
        calls.append(len(items))
        exploration = h.orch.get_exploration(h.w.sid)
        if len(calls) == 1:  # o pesquisador responde logo depois da primeira consulta
            req = gate.request("aprovar_hipotese", items[0].id, "?", ("aprovar", "rejeitar", "editar"),
                               session_id=h.w.sid)
            gate.respond(req.id, resposta={"acao": "aprovar"})
            return {}
        seen["idle"] = exploration.idle_cycles
        return {items[0].id: ApprovalDecision("aprovar")}

    h = LoopHarness(tmp_path, mode="assisted", plans=[plan([task("t1")], [hyp("h1")])], approver=approver)
    await h.run()
    assert len(calls) >= 2 and "t1" in h.ran  # esperou, recebeu a aprovação e executou
    assert seen["idle"] == 0  # a espera não incrementou idle_cycles


@pytest.mark.asyncio
async def test_assisted_sem_terminal_fecha_com_suspensao_em_vez_de_esperar_para_sempre(tmp_path):
    def approver(items):
        request_suspension()  # o terminal saiu durante a espera
        return {}

    h = LoopHarness(tmp_path, mode="assisted", plans=[plan([task("t1")], [hyp("h1")])], approver=approver)
    await asyncio.wait_for(h.run(), 20)
    assert h.ran == [] and h.stop_reason == "suspensa_sem_pesquisador"


@pytest.mark.asyncio
async def test_semi_com_pedido_pendente_nao_espera_e_vai_a_aguarda_pesquisador(tmp_path):
    h = LoopHarness(tmp_path, mode="semi", plans=[plan([task("t1")], [hyp("h1")])], approver=lambda items: {})
    h.w.hypothesis("H")  # nenhuma aprovação é pedida em semi; o laço não pode bloquear
    await asyncio.wait_for(h.run(), 20)
    assert h.stop_reason != "suspensa_sem_pesquisador"


# -- ask_researcher no assisted (3.2) --------------------------------------------------------------------------


def make_orchestrator() -> Orchestrator:
    manager = FakeSessionManager()
    manager.add("s1", "active", {"mode": "assisted"})
    return Orchestrator(session_manager=manager, output_manager=SimpleNamespace(base_dir=None), agent_runtime=None)


async def ask(orch: Orchestrator, question: str = "Onde está o dataset?") -> str:
    task_ = AgentTask(agent_id="researcher", prompt="p", task_name="t1")
    return await orch._ask_researcher_core(question, "ctx", "motivo", ["A"], task_, "s1")


@pytest.mark.asyncio
async def test_pergunta_do_agente_respondida_a_tempo_chega_ao_agente():
    orch = make_orchestrator()
    gate = orch.human_gate

    async def answer_soon():
        while not gate.requests:
            await asyncio.sleep(0.005)
        gate.respond(gate.requests[0].id, resposta={"texto": "Use /outputs/dados.csv"})

    with patch("src.config.GATE_ASK_WAIT_SECONDS", 5):
        answered, _ = await asyncio.gather(ask(orch), answer_soon())
    assert answered == "Use /outputs/dados.csv"
    assert gate.requests[0].decisao == "responder_pergunta_agente" and gate.requests[0].consumido
    interaction = orch.session_manager.get("s1").payload["researcher_interactions"][0]
    assert interaction["respondido_por"] == "pesquisador" and interaction["researcher_response"] == answered


@pytest.mark.asyncio
async def test_pergunta_do_agente_sem_resposta_a_tempo_vira_pendencia_e_o_pedido_continua():
    orch = make_orchestrator()
    with patch("src.config.GATE_ASK_WAIT_SECONDS", 0.05):
        answer = await ask(orch)
    assert answer == PENDING_MESSAGE
    assert [r.estado for r in orch.human_gate.requests] == ["pendente"]
    interaction = orch.session_manager.get("s1").payload["researcher_interactions"][0]
    assert interaction["respondido_por"] == "pendente_pesquisador"


@pytest.mark.asyncio
async def test_espera_da_pergunta_termina_se_o_terminal_saiu():
    orch = make_orchestrator()
    request_suspension()
    with patch("src.config.GATE_ASK_WAIT_SECONDS", 30):
        assert await asyncio.wait_for(ask(orch), 5) == PENDING_MESSAGE


@pytest.mark.asyncio
async def test_pergunta_nao_duplica_o_pedido_e_resposta_nao_humana_nao_vale():
    orch = make_orchestrator()
    with patch("src.config.GATE_ASK_WAIT_SECONDS", 0.05):
        await ask(orch, "mesma pergunta")
        await ask(orch, "mesma pergunta")
    assert len(orch.human_gate.requests) == 1
    orch.human_gate.respond(orch.human_gate.requests[0].id, source="agente", resposta={"texto": "forjada"})
    assert orch.human_gate.requests[0].estado == "pendente"


def test_decisao_reservada_do_agente_vai_ao_gate_com_a_sessao():
    orch = make_orchestrator()
    orch._register_reserved("aprovar_oportunidade", AgentTask(agent_id="researcher", prompt="p", task_name="t1"), "s1")
    (req,) = orch.human_gate.requests
    assert (req.decisao, req.session_id, req.referencia) == ("aprovar_oportunidade", "s1", "t1")


# -- modo sem limite preso ao lançamento (2.4) ---------------------------------------------------------------


def test_confirmacao_do_modo_sem_limite_usa_o_launch_id_como_referencia():
    gate = FakeGate()
    budget = UsageBudget.from_config(unlimited=True)
    confirm_unlimited(budget, "cli", input_fn=lambda _p: "sem limite", isatty=lambda: True, gate=gate,
                      reference="launch-123")
    (req,) = gate.requests
    assert req.decisao == "ativar_modo_sem_limite" and req.referencia == "launch-123"
    assert req.estado == "autorizada" and req.resolvido_por == "terminal"


def make_runner(launch_id: str = "launch-123") -> SessionRunner:
    spec = LaunchSpec(
        tipo="nova", prompt="p", modo="auto", orcamento={}, contexto={"dir": "x", "digest": "d"},
        primeiro_plano=True, launch_id=launch_id,
    )
    return SessionRunner(spec)


def test_processo_da_sessao_confere_e_consome_a_autorizacao_do_lancamento():
    terminal_gate().resolve("ativar_modo_sem_limite", "launch-123", source=Source.TERMINAL, approved=True)
    runner = make_runner()
    assert runner._check_unlimited_authorization() is None
    assert "ja_consumida" in runner._check_unlimited_authorization()  # uso único


def test_processo_da_sessao_recusa_o_modo_sem_pedido_ou_de_outro_lancamento():
    terminal_gate().resolve("ativar_modo_sem_limite", "launch-OUTRO", source=Source.TERMINAL, approved=True)
    refusal = make_runner()._check_unlimited_authorization()
    assert refusal is not None and "nao_encontrada" in refusal
    terminal_gate().resolve("ativar_modo_sem_limite", "launch-123", source=Source.TERMINAL, approved=False)
    assert "nao_autorizada" in make_runner()._check_unlimited_authorization()


# -- exploração padrão usa o gate (3.1) --------------------------------------------------------------------------


def test_exploracao_sem_aprovador_injetado_usa_o_gate_persistente():
    ctx = SimpleNamespace(session_id="s1", project_id="p1", continues_session_id=None)
    exploration = ExplorationSession(lambda: None, ctx, "outputs/s1", mode="assisted",
                                     session_chain=lambda: ["s1", "s0"])
    assert isinstance(exploration._approver, PersistentGateApprover)
    assert isinstance(exploration._gate_confirmer(), PersistentGateConfirmer)
    assert exploration._chain() == ["s1", "s0"]
