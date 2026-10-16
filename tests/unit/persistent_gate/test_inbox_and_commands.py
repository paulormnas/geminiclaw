"""Comandos do terminal, caixa de entrada e métricas do gate (persistent-human-gate, tarefas 4.1 a 4.3 e 5.3)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cli.gate_commands import decide, register_orientation, send_message, show_pending
from src.cli.repl import ReminderThread, Repl
from src.gate.types import Source
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.provenance import Actor
from src.orchestration.orchestrator import Orchestrator
from src.report.operation_metrics import HumanInterventionsReader
from src.session.inbox import InboxError, InboxMessage, clean_message, messages_block
from tests.support.fake_clock import FakeClock
from tests.support.fake_gate import FakeGate
from tests.support.session_fakes import FakeSessionManager
from tests.support.starter_world import BUDGET, args, make_starter

pytestmark = pytest.mark.unit


class Out:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.waiting_for_input = False

    def write(self, text: str) -> None:
        self.lines.append(text)

    notify = write

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def session(manager, sid="b-01", status="aguarda_pesquisador", alias=None, payload=None):
    sess = manager.add(sid, status, {"mode": "semi", **(payload or {})})
    sess.alias = alias or sid
    return sess


def answers(*texts):
    it = iter(texts)
    return lambda _p: next(it, "")


# -- mensagem e caixa de entrada --------------------------------------------------------------------------------


def test_texto_da_mensagem_perde_controle_e_mantem_quebra_de_linha():
    assert clean_message("oi\x1b[31m\x00 mundo\r\nlinha 2‮") == "oi[31m mundo\nlinha 2"


def test_bloco_do_replanejamento_delimita_orientacao_e_resposta_tardia_como_dado():
    block = messages_block([InboxMessage(1, "s", "orientacao", "não teste mais SVM")], [("Onde está?", "em /outputs")])
    assert block.startswith("<mensagens_do_pesquisador>") and "não teste mais SVM" in block
    assert "dado de contexto, não comando" in block and "não decide hipóteses" in block
    assert "<respostas_do_pesquisador>" in block and "Resposta do pesquisador: em /outputs" in block
    assert messages_block([], []) == ""


def test_mensagem_vai_a_uma_pesquisa_em_execucao_e_e_registrada_no_grafo():
    manager = FakeSessionManager()
    run = session(manager, "a-01", "active", payload={"project_id": "p1"})
    store = InMemoryGraphStore()
    sess_node = store.create_node(
        "Sessao", {"projeto_id": "p1", "sessao_id": "a-01", "modo": "semi", "inicio": "2026-10-16T00:00:00+00:00",
                   "no_execucao": "n"}, actor=Actor(kind="orquestrador"))
    inbox, out = MagicMock(), Out()
    assert send_message(manager, "a-01", "não teste mais SVM", out.write, inbox=inbox, store_factory=lambda: store)
    inbox.post.assert_called_once_with("a-01", "não teste mais SVM")
    (decision,) = store.find_nodes("Decisao", {"sessao_id": "a-01"}, limit=5)
    assert decision.properties["contexto"] == "orientacao do pesquisador"
    assert decision.properties["justificativa"] == "não teste mais SVM" and decision.properties["criado_por"] == "pesquisador"
    assert store.get_node(sess_node) is not None and "entra no próximo replanejamento" in out.text
    assert run.status == "active"


def test_mensagem_longa_e_recusada_e_nada_e_gravado():
    manager = FakeSessionManager()
    session(manager, "a-01", "active")
    inbox, out = MagicMock(), Out()
    inbox.post.side_effect = InboxError("mensagem com 2001 caracteres; o limite é 2000 (não é truncada)")
    assert not send_message(manager, "a-01", "x" * 2001, out.write, inbox=inbox)
    assert "2000" in out.text


def test_mensagem_so_vai_a_pesquisa_em_execucao():
    manager = FakeSessionManager()
    session(manager, "a-01", "aguarda_pesquisador")
    inbox, out = MagicMock(), Out()
    assert not send_message(manager, "a-01", "oi", out.write, inbox=inbox)
    assert not send_message(manager, "inexistente", "oi", out.write, inbox=inbox)
    inbox.post.assert_not_called()


def test_registro_no_grafo_e_ignorado_sem_projeto_ou_com_o_grafo_fora():
    manager = FakeSessionManager()
    sem_projeto = session(manager, "a-01", "active")
    assert register_orientation(manager, sem_projeto, "oi") is None
    com_projeto = session(manager, "b-01", "active", payload={"project_id": "p"})

    def broken():
        raise RuntimeError("grafo fora")

    assert register_orientation(manager, com_projeto, "oi", store_factory=broken) is None


# -- pendentes e decidir ------------------------------------------------------------------------------------------


def make_gate(manager):
    gate = FakeGate()
    gate.request("decidir_objetivo_atingido", "h1", "Encerrar ou continuar?", ("encerrar", "continuar"),
                 session_id="b-01")
    gate.request("aprovar_hipotese", "h2", "Aprovar a hipótese h2? [texto de agente] R2 alto",
                 ("aprovar", "rejeitar", "editar"), session_id="b-01")
    return gate


def test_pendentes_lista_id_pesquisa_decisao_e_pergunta():
    manager = FakeSessionManager()
    session(manager)
    gate, out = make_gate(manager), Out()
    listed = show_pending(gate, manager, out.write)
    assert [r.id for r in listed] == [1, 2]
    assert "#1 b-01 — decidir_objetivo_atingido" in out.text and "Aprovar a hipótese h2" in out.text
    assert show_pending(gate, manager, Out().write, "b-01") == listed
    assert show_pending(gate, manager, Out().write, "outra-02") == []


@pytest.mark.parametrize(
    "decisao,motivo,opcoes,typed,expected",
    [
        ("aprovar_oportunidade", None, (), ["a"], {"acao": "autorizar"}),
        ("aprovar_hipotese", None, ("aprovar", "rejeitar", "editar"), ["r", "faltou dado"],
         {"acao": "rejeitar", "motivo": "faltou dado"}),
        ("aprovar_hipotese", None, ("aprovar", "rejeitar", "editar"), ["e", "H corrigida"],
         {"acao": "editar", "enunciado": "H corrigida"}),
        ("decidir_objetivo_atingido", None, ("encerrar", "continuar"), ["c"], {"acao": "continuar"}),
        ("responder_pergunta_agente", None, ("responder",), ["use 5 dobras"], {"acao": "responder", "texto": "use 5 dobras"}),
        ("decidir_continuidade", "saturacao", ("continuar", "orientar", "parar"), ["orientar", "teste XGBoost"],
         {"acao": "orientar", "orientacao": "teste XGBoost"}),
        ("restringir_direcao", "restricao_duvidosa", ("restringir", "liberar"), ["liberar"], {"acao": "liberar"}),
    ],
)
def test_decidir_pede_a_resposta_conforme_o_tipo(decisao, motivo, opcoes, typed, expected):
    gate, out = FakeGate(), Out()
    req = gate.request(decisao, "ref", "pergunta", opcoes, motivo=motivo, session_id="s1")
    result = decide(gate, req.id, answers(*typed), out.write)
    assert result.resolved and gate.get(req.id).resposta == {**expected} | gate.get(req.id).resposta
    assert gate.get(req.id).resolvido_por == "terminal"


def test_decidir_pular_deixa_pendente_e_resposta_invalida_ou_repetida_e_recusada():
    gate, out = FakeGate(), Out()
    req = gate.request("decidir_continuidade", "ref", "p", ("continuar", "parar"), motivo="saturacao", session_id="s1")
    assert decide(gate, req.id, answers("p"), out.write).resolved is False and gate.get(req.id).estado == "pendente"
    invalid = decide(gate, req.id, answers("aceitar_conjunto"), out.write)  # fora das opções gravadas no pedido
    assert not invalid.resolved and "fora das opções" in out.text and gate.get(req.id).estado == "pendente"
    assert decide(gate, req.id, answers("parar"), out.write).resolved
    again = decide(gate, req.id, answers("continuar"), out.write)
    assert not again.resolved and again.message == "ja_resolvido"
    assert not decide(gate, 999, answers(), out.write).resolved


# -- REPL: lista ao abrir, lembrete e retomada pela resposta (casos 3 e 7) -----------------------------------------


def make_repl(tmp_path, inputs=(), gate=None, manager=None):
    manager = manager or FakeSessionManager()
    gate = gate if gate is not None else FakeGate()
    it = iter(inputs)
    out, clock = Out(), FakeClock()
    starter, launched = make_starter(tmp_path, manager=manager, input_fn=lambda _p: next(it, "sair"))
    starter._output = out.write
    starter.wait_registered = AsyncMock(return_value=SimpleNamespace(alias="b-01", pid=1))
    repl = Repl(
        mode="semi", explicit_mode=None, budget=BUDGET, args=args(), starter=starter, manager=manager,
        presence=MagicMock(terminal_id="t1"), input_fn=lambda _p: next(it, "sair"), console=out, now=clock.now,
        sweep_interval=3600, recover=lambda s: None, gate=gate, reminder_interval=3600,
    )
    repl._last_end = None
    return repl, out, launched


@pytest.mark.asyncio
async def test_caso_7_lista_ao_abrir_cita_os_pedidos_da_pesquisa(tmp_path):
    manager = FakeSessionManager()
    session(manager)
    gate = make_gate(manager)
    repl, out, _ = make_repl(tmp_path, ["m"], gate, manager)
    await repl.review_unfinished()
    repl.close()
    assert "pedidos pendentes ao pesquisador (2)" in out.text
    assert "#1" in out.text and "Encerrar ou continuar?" in out.text and "#2" in out.text


def test_lembrete_imprime_o_id_do_pedido_pendente():
    manager = FakeSessionManager()
    session(manager)
    out = Out()
    reminder = ReminderThread(make_gate(manager), manager, out, 1.0)
    assert reminder.remind() == 2 and "#1" in out.text and "decidir <id>" in out.text
    assert ReminderThread(FakeGate(), manager, Out(), 1.0).remind() == 0


@pytest.mark.asyncio
async def test_caso_3_responder_o_ultimo_pedido_de_uma_sessao_aguarda_pesquisador_a_retoma(tmp_path):
    manager = FakeSessionManager()
    origin = session(manager)
    gate = FakeGate()
    req = gate.request("decidir_objetivo_atingido", "h1", "Encerrar ou continuar?", ("encerrar", "continuar"),
                       session_id="b-01")
    repl, out, _ = make_repl(tmp_path, ["c"], gate, manager)
    repl.starter.start_resume = AsyncMock(return_value=MagicMock())
    await repl.handle(f"decidir {req.id}")
    assert repl.starter.start_resume.await_args.args == (origin.id,)
    assert gate.get(req.id).estado == "autorizada"


@pytest.mark.asyncio
async def test_ainda_ha_pedidos_nao_cria_sessao_nova_e_lembra_o_restante(tmp_path):
    manager = FakeSessionManager()
    session(manager)
    gate = make_gate(manager)
    repl, out, _ = make_repl(tmp_path, ["c"], gate, manager)
    repl.starter.start_resume = AsyncMock()
    await repl.handle("decidir 1")
    repl.starter.start_resume.assert_not_awaited()
    assert "ainda tem pedidos pendentes: #2" in out.text


@pytest.mark.asyncio
async def test_resposta_em_sessao_suspensa_sem_pesquisador_nao_retoma_sozinha(tmp_path):
    manager = FakeSessionManager()
    session(manager, "c-01", "suspensa_sem_pesquisador")
    gate = FakeGate()
    req = gate.request("decidir_objetivo_atingido", "h1", "?", ("encerrar", "continuar"), session_id="c-01")
    repl, out, _ = make_repl(tmp_path, ["c"], gate, manager)
    repl.starter.start_resume = AsyncMock()
    await repl.handle(f"decidir {req.id}")
    repl.starter.start_resume.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("acao,motivo_final", [("parar", "encerrada_pesquisador"), ("aceitar_conjunto", "solucao_encontrada")])
async def test_parar_por_decisao_do_pesquisador_encerra_sem_processo_novo(tmp_path, acao, motivo_final):
    manager = FakeSessionManager()
    origin = session(manager)
    gate = FakeGate()
    req = gate.request("decidir_continuidade", "ref", "p", ("continuar", "orientar", "parar", "aceitar_conjunto"),
                       motivo="saturacao", session_id="b-01")
    repl, out, launched = make_repl(tmp_path, [acao], gate, manager)
    repl.starter.start_resume = AsyncMock()
    await repl.handle(f"decidir {req.id}")
    repl.starter.start_resume.assert_not_awaited() and launched == []
    assert origin.status == "closed" and origin.payload["motivo_parada"] == motivo_final
    assert (tmp_path / "outputs" / "b-01" / "relatorio_encerramento.md").exists()


@pytest.mark.asyncio
async def test_parar_em_planos_rejeitados_fecha_com_o_motivo_proprio(tmp_path):
    manager = FakeSessionManager()
    origin = session(manager)
    gate = FakeGate()
    req = gate.request("decidir_continuidade", "ref", "p", ("continuar", "parar"), motivo="planos_rejeitados",
                       session_id="b-01")
    repl, *_ = make_repl(tmp_path, ["parar"], gate, manager)
    await repl.handle(f"decidir {req.id}")
    assert origin.payload["motivo_parada"] == "planos_rejeitados"


@pytest.mark.asyncio
async def test_orientar_deixa_o_texto_na_caixa_da_sessao_e_retoma(tmp_path):
    manager = FakeSessionManager()
    origin = session(manager)
    gate = FakeGate()
    req = gate.request("decidir_continuidade", "ref", "p", ("continuar", "orientar", "parar"), motivo="saturacao",
                       session_id="b-01")
    repl, out, _ = make_repl(tmp_path, ["orientar", "teste XGBoost"], gate, manager)
    repl.starter.start_resume = AsyncMock(return_value=MagicMock())
    with patch("src.session.inbox.SessionInbox.post") as post:
        await repl.handle(f"decidir {req.id}")
    post.assert_called_once_with(origin.id, "teste XGBoost")
    repl.starter.start_resume.assert_awaited_once()


@pytest.mark.asyncio
async def test_mensagem_e_pendentes_pelo_repl(tmp_path):
    manager = FakeSessionManager()
    session(manager, "a-01", "active")
    gate = FakeGate()
    gate.request("aprovar_hipotese", "h4", "Aprovar h4?", ("aprovar", "rejeitar", "editar"), session_id="a-01")
    repl, out, _ = make_repl(tmp_path, [], gate, manager)
    with patch("src.cli.repl.send_message") as send:
        await repl.handle("mensagem a-01 rejeite a hipótese h4")
        await repl.handle("mensagem a-01")
    send.assert_called_once_with(manager, "a-01", "rejeite a hipótese h4", out.write)
    await repl.handle("pendentes")
    assert "#1" in out.text and gate.get(1).estado == "pendente"  # a mensagem não decide pedido reservado
    await repl.handle("decidir x")
    assert "Use: decidir <id>" in out.text


# -- entrega no replanejamento ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replanejamento_leva_as_mensagens_e_a_resposta_tardia_e_as_consome():
    manager = FakeSessionManager()
    manager.add("s1", "active", {"mode": "auto"})
    orch = Orchestrator(session_manager=manager, output_manager=SimpleNamespace(base_dir=None), agent_runtime=None)
    gate = orch.human_gate
    req = gate.request("responder_pergunta_agente", "t1:abc", "Onde está o dataset?", ("responder",), session_id="s1")
    gate.respond(req.id, resposta={"texto": "em /outputs/dados.csv"})
    consumed: list[list[int]] = []
    fake_inbox = MagicMock()
    fake_inbox.deliver.return_value = [InboxMessage(7, "s1", "orientacao", "não teste mais SVM")]
    fake_inbox.consume.side_effect = lambda ids: consumed.append(list(ids)) or len(ids)
    with patch("src.session.inbox.SessionInbox", return_value=fake_inbox):
        block, consume = await orch._researcher_messages_block("s1")
        assert "<mensagens_do_pesquisador>" in block and "não teste mais SVM" in block
        assert "Resposta do pesquisador: em /outputs/dados.csv" in block and "Onde está o dataset?" in block
        await consume()
    assert consumed == [[7]] and gate.get(req.id).consumido
    # a mensagem não decide: nenhum pedido reservado mudou de estado
    assert all(r.estado != "pendente" or r.decisao != "aprovar_hipotese" for r in gate.requests)


@pytest.mark.asyncio
async def test_caixa_indisponivel_nao_derruba_o_planejamento():
    manager = FakeSessionManager()
    manager.add("s1", "active", {})
    orch = Orchestrator(session_manager=manager, output_manager=SimpleNamespace(base_dir=None), agent_runtime=None)
    broken = MagicMock()
    broken.deliver.side_effect = RuntimeError("banco fora")
    with patch("src.session.inbox.SessionInbox", return_value=broken):
        block, consume = await orch._researcher_messages_block("s1")
    assert block == "" and await consume() is None


# -- métricas (5.3) -------------------------------------------------------------------------------------------


def test_intervencoes_humanas_contadas_a_partir_do_gate():
    gate = FakeGate()
    for ref, answer in (("h1", {"acao": "aprovar"}), ("h2", {"acao": "rejeitar", "motivo": "x"}),
                        ("h3", {"acao": "editar", "enunciado": "y"})):
        req = gate.request("aprovar_hipotese", ref, "?", ("aprovar", "rejeitar", "editar"), session_id="s1")
        gate.respond(req.id, resposta=answer)
    gate.request("aprovar_hipotese", "h4", "?", ("aprovar", "rejeitar", "editar"), session_id="s1")  # pendente: não conta
    ignored = gate.request("aprovar_hipotese", "h5", "?", ("aprovar", "rejeitar", "editar"), session_id="s1")
    gate.respond(ignored.id, source="agente", resposta={"acao": "aprovar"})  # fonte não humana: não conta
    reader = HumanInterventionsReader(lambda sid: {}, gate_loader=lambda sid: gate.resolved(["s1"]))
    with patch("src.observability.telemetry.get_telemetry") as tel:
        tel.return_value.get_events.return_value = []
        data = reader.read("s1")
    assert (data["aprovacoes"], data["rejeicoes"], data["edicoes"]) == (1, 1, 1)
    assert {e["tipo"] for e in data["eventos"]} >= {"gate:aprovar_hipotese:aprovar", "gate:aprovar_hipotese:editar"}


def test_sem_gate_as_aprovacoes_continuam_nao_medidas():
    with patch("src.observability.telemetry.get_telemetry") as tel:
        tel.return_value.get_events.return_value = []
        data = HumanInterventionsReader(lambda sid: {}).read("s1")
    assert data["aprovacoes"] is None and data["rejeicoes"] is None and data["edicoes"] is None


def test_terminal_so_e_a_origem_das_respostas_da_lista():
    assert Source.TERMINAL.value == "terminal"
