"""REPL: texto livre é conversa, ``perguntar`` e orientação sugerida com confirmação (researcher-consult)."""

import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.cli.repl import NO_RESEARCH_TO_CONSULT, Repl
from src.cli.terminal_consult import ConsultOutcome
from src.session.presence import TerminalPresence
from tests.support.fake_gate import FakeGate
from tests.support.session_fakes import FakeSessionManager, InMemoryPresenceStore

pytestmark = pytest.mark.unit


class Console:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)

    notify = write

    @property
    def text(self):
        return "\n".join(self.lines)


class Starter:
    def __init__(self):
        self.started = []
        self.base_dir = "."

    async def start_new(self, task, **kw):
        self.started.append(task)
        return SimpleNamespace()

    async def wait_registered(self, started):
        return SimpleNamespace(alias="x", pid=1)


def make(running=True, answers=(), outcome=None):
    manager = FakeSessionManager()
    if running:
        s = manager.add("s1", "active", {"mode": "auto"})
        s.alias, s.pid = "iris-01", 4242
    chamadas = []
    entradas = iter(answers)
    perguntas = []

    def entrada(prompt):
        perguntas.append(prompt)
        return next(entradas)

    def consulta(pergunta, session_id):
        chamadas.append((pergunta, session_id))
        return outcome or ConsultOutcome(resposta="h1 foi refutada")

    console, starter = Console(), Starter()
    repl = Repl(
        mode="auto", explicit_mode=None, budget=None, args=SimpleNamespace(), starter=starter, manager=manager,
        presence=TerminalPresence("repl", store=InMemoryPresenceStore(), pid_alive=lambda pid: True),
        input_fn=entrada, console=console, recover=lambda s: None, gate=FakeGate(),
        consult_fn=consulta,
    )
    repl.perguntas = perguntas
    return repl, chamadas, console, starter


@pytest.mark.asyncio
async def test_texto_livre_e_conversa_e_nao_inicia_pesquisa():
    """Scenario: Texto livre é conversa."""
    repl, chamadas, console, starter = make()
    await repl.handle("quais hipóteses foram refutadas?")
    assert chamadas == [("quais hipóteses foram refutadas?", "s1")]
    assert starter.started == [] and "h1 foi refutada" in console.text


@pytest.mark.asyncio
@pytest.mark.parametrize("linha, esperado", [
    ("perguntar quais hipóteses?", "quais hipóteses?"),
    ("? quais hipóteses?", "quais hipóteses?"),
    ("perguntar @iris-01 quais hipóteses?", "quais hipóteses?"),
])
async def test_perguntar_e_ponto_de_interrogacao(linha, esperado):
    repl, chamadas, *_ = make()
    await repl.handle(linha)
    assert chamadas == [(esperado, "s1")]


@pytest.mark.asyncio
async def test_texto_livre_sem_pesquisa_e_recusado_sem_chamar_o_modelo():
    """Scenario: Texto livre sem pesquisa."""
    repl, chamadas, console, starter = make(running=False)
    await repl.handle("quais hipóteses foram refutadas?")
    assert chamadas == [] and starter.started == [] and NO_RESEARCH_TO_CONSULT in console.text
    assert "nova-pesquisa <tarefa>" in console.text


@pytest.mark.asyncio
async def test_com_varias_pesquisas_pergunta_qual():
    repl, chamadas, console, _ = make(answers=["b-01"])
    b = repl.manager.add("s2", "active", {"mode": "semi"})
    b.alias, b.pid = "b-01", 4343
    await repl.handle("qual o estado?")
    assert chamadas == [("qual o estado?", "s2")]


@pytest.mark.asyncio
async def test_apelido_inexistente_nao_consulta():
    repl, chamadas, console, _ = make()
    await repl.handle("perguntar @nao-existe tudo bem?")
    assert chamadas == [] and "não encontrada" in console.text


@pytest.mark.asyncio
async def test_consulta_recusada_mostra_o_motivo():
    repl, chamadas, console, _ = make(outcome=ConsultOutcome(erro="política self_hosted_only: provedor de nuvem"))
    await repl.handle("perguntar algo")
    assert "Consulta recusada" in console.text and "self_hosted_only" in console.text


@pytest.mark.asyncio
async def test_consulta_desligada_nao_chama(monkeypatch):
    monkeypatch.setattr("src.config.TERMINAL_CONSULT_ENABLED", False)
    repl, chamadas, console, _ = make()
    await repl.handle("perguntar algo")
    assert chamadas == [] and "desligada" in console.text


@pytest.mark.asyncio
async def test_resposta_com_sequencia_de_controle_e_exibida_saneada():
    repl, _, console, _ = make(outcome=ConsultOutcome(resposta="ok \x1b[2J fim \x07"))
    await repl.handle("perguntar algo")
    texto = re.sub(r"\x1b\[[0-9;]*m", "", console.text)  # as cores do próprio terminal são esperadas
    assert "\x1b" not in texto and "\x07" not in texto and "ok" in texto and "fim" in texto


@pytest.mark.asyncio
async def test_orientacao_confirmada_vai_a_caixa_da_pesquisa():
    """Scenario: Pesquisador confirma."""
    saida = ConsultOutcome(resposta="ok", orientacao_sugerida="priorize modelos lineares")
    repl, _, console, _ = make(answers=["s"], outcome=saida)
    with patch("src.cli.repl.send_message") as enviar:
        await repl.handle("perguntar mude o rumo")
    enviar.assert_called_once()
    assert enviar.call_args.args[1:3] == ("iris-01", "priorize modelos lineares")
    assert any("Enviar como mensagem a iris-01? [s/N]" in p for p in repl.perguntas)


@pytest.mark.asyncio
async def test_orientacao_recusada_nao_grava_nada():
    """Scenario: Pesquisador recusa."""
    saida = ConsultOutcome(resposta="ok", orientacao_sugerida="priorize modelos lineares")
    repl, _, _, _ = make(answers=["n"], outcome=saida)
    with patch("src.cli.repl.send_message") as enviar:
        await repl.handle("perguntar mude o rumo")
    enviar.assert_not_called()


@pytest.mark.asyncio
async def test_comandos_conhecidos_continuam_funcionando():
    repl, chamadas, console, _ = make()
    await repl.handle("pesquisas")
    assert chamadas == [] and "iris-01" in console.text
