"""Testes do gate de decisões reservadas ao pesquisador (v17-curator-agent, tarefa 6.99).

Aprovar Oportunidade, confirmar Problema, aprovar termo de vocabulário, autorizar escrita em instrumento e ativar o
modo sem limite exigem ação explícita do pesquisador (terminal/CLI): a resposta de ``ask_researcher``, inclusive a do
Researcher consultor, nunca conta como autorização. Nenhum teste usa rede ou provedor pago.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.agent_runtime.context import bind_agent_context, current_context
from src.human_gate import ESTADO_AUTORIZADA, ESTADO_NEGADA, ESTADO_PENDENTE, HUMAN_SOURCES, HumanGate
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.problem import ProblemDraft
from src.knowledge.projects import ProjectError, confirm_problem, create_project
from src.knowledge.provenance import Actor
from src.research_consult import DECISOES_RESERVADAS
from src.skills.human_feedback.skill import HumanFeedbackSkill
from tests.unit.test_researcher_consult import Harness, ScriptedProvider, _answer

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    token = current_context.set(None)
    tel = MagicMock()
    monkeypatch.setattr("src.orchestrator.get_telemetry", lambda: tel)
    monkeypatch.setattr("src.llm.metering.get_telemetry", lambda: tel)
    yield
    current_context.reset(token)


@pytest.mark.parametrize("decisao", DECISOES_RESERVADAS)
def test_gate_com_resposta_do_consultor_continua_pendente(decisao):
    """Tarefa 6.99 — a resposta do consultor (ou de qualquer fonte não humana) deixa a decisão pendente."""
    gate = HumanGate()
    req = gate.request(decisao, "subtarefa-1")

    for fonte in ("researcher_consult", "ask_researcher", "consultor", "agente", "curator", "documento", ""):
        resposta = gate.answer(req.id, source=fonte, approved=True)
        assert resposta.estado == ESTADO_PENDENTE

    assert gate.authorized(req.id) is False
    assert gate.get(req.id).respostas_ignoradas == 7
    assert [r.id for r in gate.pending()] == [req.id]


def test_so_o_pesquisador_no_terminal_ou_cli_resolve_o_pedido():
    """Tarefa 6.99 — ação explícita do pesquisador (terminal/CLI) autoriza ou nega; sem TTY nada é autorizado."""
    gate = HumanGate()
    autorizado, negado, sem_tty = (gate.request("aprovar_oportunidade") for _ in range(3))

    gate.ask_in_terminal(autorizado.id, input_fn=lambda _: "s", interactive=True)
    gate.ask_in_terminal(negado.id, input_fn=lambda _: "n", interactive=True)
    gate.ask_in_terminal(sem_tty.id, input_fn=lambda _: "s", interactive=False)

    assert HUMAN_SOURCES == {"terminal", "cli"}
    assert gate.get(autorizado.id).estado == ESTADO_AUTORIZADA and gate.authorized(autorizado.id)
    assert gate.get(autorizado.id).resolvido_por == "terminal"
    assert gate.get(negado.id).estado == ESTADO_NEGADA and not gate.authorized(negado.id)
    assert gate.get(sem_tty.id).estado == ESTADO_PENDENTE
    cli = gate.request("confirmar_problema")
    assert gate.answer(cli.id, source="cli", approved=True).estado == ESTADO_AUTORIZADA
    # Uma vez decidido pelo humano, uma resposta posterior de outra fonte não reabre nem altera.
    assert gate.answer(cli.id, source="researcher_consult", approved=False).estado == ESTADO_AUTORIZADA


def test_decisao_desconhecida_nao_e_registrada():
    """Fail-fast — só as decisões reservadas conhecidas entram no gate."""
    with pytest.raises(ValueError):
        HumanGate().request("decidir_qualquer_coisa")


@pytest.mark.asyncio
@pytest.mark.parametrize("decisao", DECISOES_RESERVADAS)
async def test_pedido_reservado_do_agente_fica_pendente_e_o_consultor_nao_e_chamado(tmp_path: Path, decisao):
    """Tarefa 6.99 — ask_researcher (semi/auto) sobre decisão reservada: pendente no gate, consultor não responde."""
    provider = ScriptedProvider([_answer("Aprovado, pode prosseguir.")])
    h = Harness(tmp_path, provider, mode="semi")
    bind_agent_context(h.ctx())

    result = await HumanFeedbackSkill().run(
        question="Podemos prosseguir?", why_cant_proceed="decisão reservada", decisao_reservada=decisao
    )

    assert "reservada ao pesquisador" in result.output.lower()
    assert provider.calls == []  # o consultor nunca foi chamado
    (pedido,) = h.orch.human_gate.pending()
    assert pedido.decisao == decisao
    # Mesmo que a resposta do consultor chegasse ao gate, ela não autoriza.
    assert h.orch.human_gate.answer(pedido.id, source="researcher_consult", approved=True).estado == ESTADO_PENDENTE
    assert h.orch.human_gate.authorized(pedido.id) is False


@pytest.mark.asyncio
async def test_pergunta_reservada_sem_autodeclaracao_tambem_vai_ao_gate(tmp_path: Path):
    """Tarefa 6.99 — a classificação por palavras-chave (falha fechada) também registra o pedido pendente."""
    h = Harness(tmp_path, ScriptedProvider([_answer("ok")]), mode="auto")
    bind_agent_context(h.ctx())

    await HumanFeedbackSkill().run(question="Posso aprovar o termo de vocabulário 'quimica'?", why_cant_proceed="x")

    (pedido,) = h.orch.human_gate.pending()
    assert pedido.decisao == "aprovar_termo_vocabulario"


def test_confirmar_problema_por_quem_nao_e_o_pesquisador_e_recusado():
    """Tarefa 6.99 — a confirmação do Problema só aceita o ator pesquisador (resposta de agente não vale)."""
    store = InMemoryGraphStore()
    pid = create_project(store, "P", "O", [])
    draft = ProblemDraft(titulo="T", resumo="R", metrica="r2", delta_min=0.05)

    atores = (Actor(kind="agente", role="researcher"), Actor(kind="agente", role="curator"), Actor(kind="orquestrador"))
    for ator in atores:
        with pytest.raises(ProjectError):
            confirm_problem(store, pid, draft, confirmed_by=ator, sentido_metrica="maior_melhor")
    assert store.find_nodes("Problema", {}) == []
