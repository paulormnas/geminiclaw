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
from src.human_gate import (
    ESTADO_AUTORIZADA,
    ESTADO_NEGADA,
    ESTADO_PENDENTE,
    HUMAN_SOURCES,
    HumanGate,
    Source,
    authorize_from_cli,
)
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

    fontes = (Source.RESEARCHER_CONSULT, Source.ASK_RESEARCHER, Source.AGENT, Source.DOCUMENT,
              "terminal", "cli", "")  # string solta, mesmo "terminal", nunca vale
    for fonte in fontes:
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

    assert HUMAN_SOURCES == {Source.TERMINAL, Source.CLI}
    assert gate.get(autorizado.id).estado == ESTADO_AUTORIZADA and gate.authorized(autorizado.id)
    assert gate.get(autorizado.id).resolvido_por == Source.TERMINAL
    assert gate.get(negado.id).estado == ESTADO_NEGADA and not gate.authorized(negado.id)
    assert gate.get(sem_tty.id).estado == ESTADO_PENDENTE
    cli = gate.request("confirmar_problema")
    assert gate.answer(cli.id, source=Source.CLI, approved=True).estado == ESTADO_AUTORIZADA
    # Uma vez decidido pelo humano, uma resposta posterior de outra fonte não reabre nem altera.
    assert gate.answer(cli.id, source=Source.RESEARCHER_CONSULT, approved=False).estado == ESTADO_AUTORIZADA


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
    assert h.orch.human_gate.answer(pedido.id, source=Source.RESEARCHER_CONSULT, approved=True).estado == ESTADO_PENDENTE
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


# --------------------------------------------------------------------------- integração com os gates reais


@pytest.mark.asyncio
async def test_confirmacao_do_problema_passa_pelo_gate_real(monkeypatch):
    """I7 — ensure_confirmed_problem consulta o gate (origem TERMINAL) antes de confirmar; gate negado não confirma."""
    from src.project_session import ensure_confirmed_problem
    from src.knowledge.problem import ProblemDraft

    class _Negado(HumanGate):
        def authorized(self, request_id):  # um gate que não autoriza (ex.: origem não humana)
            return False

    store = InMemoryGraphStore()
    pid = create_project(store, "P", "O", [])
    draft = ProblemDraft(titulo="T", resumo="R", metrica="r2", alvo=None, delta_min=0.05)

    async def drafter(*_a, **_k):
        return draft

    respostas = iter(["c", "q"])
    negado = _Negado()
    with pytest.raises(Exception):
        await ensure_confirmed_problem(
            store, pid, "p", None, drafter=drafter, interactive=True, input_fn=lambda _: next(respostas),
            output_fn=lambda *_: None, gate=negado,
        )
    assert store.find_nodes("Problema", {"status": "confirmado"}) == []
    assert negado.get(1).decisao == "confirmar_problema"  # o pedido passou pelo gate

    gate = HumanGate()
    detail = await ensure_confirmed_problem(
        store, pid, "p", None, drafter=drafter, interactive=True, input_fn=lambda _: "c",
        output_fn=lambda *_: None, gate=gate,
    )
    assert detail.problema is not None
    (pedido,) = [r for r in gate._requests.values()]  # noqa: SLF001
    assert pedido.estado == ESTADO_AUTORIZADA and pedido.resolvido_por == Source.TERMINAL


def test_vocab_approve_na_cli_passa_pelo_gate_e_resposta_de_agente_nao_aprova(monkeypatch, capsys):
    """I7 — ``vocab approve`` só aprova com a origem CLI; um gate que recusa deixa o termo candidato."""
    from src.cli import _handle_vocab_command
    from src.knowledge.provenance import Actor as _Actor

    store = InMemoryGraphStore()
    termo = store.create_node(
        "Dominio",
        {"termo": "t", "nivel": "area", "status": "candidato", "projeto_id": "vocab", "sessao_id": "s",
         "justificativa_criacao": "j", "nos_consultados": []},
        actor=_Actor(kind="agente", role="researcher"),
    )

    monkeypatch.setattr("src.human_gate.authorize_from_cli", lambda *a, **k: False)
    assert _handle_vocab_command(["approve", termo], store=store) == 1
    assert store.get_node(termo).properties["status"] == "candidato"

    monkeypatch.undo()
    assert _handle_vocab_command(["approve", termo], store=store) == 0
    assert store.get_node(termo).properties["status"] == "aprovado"
    assert authorize_from_cli("aprovar_termo_vocabulario", "x") is True
