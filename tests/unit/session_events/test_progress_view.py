"""Impressão dos eventos, saneamento na exibição e comandos do REPL (session-continuity 2.2, 2.3 e 3.3)."""


from types import SimpleNamespace

import pytest

from src.cli.progress_view import (
    EventsThread,
    clean_line,
    format_event,
    send_command,
    show_history,
    show_overview,
    visible,
)
from src.session.events import Event
from src.session.inbox import TIPO_COMANDO
from tests.support.fake_gate import FakeGate
from tests.support.session_fakes import FakeSessionManager

pytestmark = pytest.mark.unit


def evento(i: int, tipo: str, resumo: str, session_id: str = "s1") -> Event:
    return Event(i, session_id, i, tipo, "2026-10-18T10:00:00Z", resumo, {})


class FakeReader:
    def __init__(self, events=()):
        self.events = list(events)

    def since(self, last_id, *, session_ids=None, limit=200):
        return [e for e in self.events if e.id > last_id][:limit]

    def tail(self, session_id, n):
        return [e for e in self.events if e.session_id == session_id][-n:] if n > 0 else []

    def last_id(self):
        return max((e.id for e in self.events), default=0)


class Console:
    def __init__(self):
        self.lines = []

    def notify(self, text):
        self.lines.append(text)

    def write(self, text):
        self.lines.append(text)


@pytest.fixture
def manager():
    m = FakeSessionManager()
    s = m.add("s1", "active", {"mode": "auto"})
    s.alias, s.pid = "iris-01", None
    return m


def test_niveis_de_detalhe():
    assert visible("silencioso", "decisao_pendente") and not visible("silencioso", "subtarefa_concluida")
    assert visible("resumo", "plano_aprovado") and not visible("resumo", "subtarefa_iniciada")
    assert visible("detalhado", "subtarefa_iniciada")


def test_linha_com_apelido_e_texto_saneado():
    linha = format_event("iris-01", evento(1, "parada", "ok \x1b]0;titulo\x07 \x1b[2J fim ‮"))
    assert linha.startswith("[iris-01] ok ") and linha.endswith(" fim")
    for proibido in ("\x1b", "\x07", "‮"):
        assert proibido not in linha


def test_resumo_acima_do_teto_e_cortado():
    assert len(clean_line("x" * 1000)) <= 300


def test_imprime_so_o_que_o_nivel_mostra_e_nao_repete(manager):
    reader = FakeReader([
        evento(1, "subtarefa_concluida", "t1 concluída"), evento(2, "decisao_pendente", "aguarda você: x"),
        evento(3, "plano_aprovado", "plano 1 aprovado: 2 subtarefas"),
    ])
    console = Console()
    thread = EventsThread(reader, manager, console, 1, level=lambda: "silencioso")
    assert thread.poll() == 1 and console.lines == ["[iris-01] aguarda você: x"]
    assert thread.poll() == 0  # já visto
    resumo = Console()
    assert EventsThread(reader, manager, resumo, 1, level=lambda: "resumo").poll() == 2
    detalhado = Console()
    assert EventsThread(reader, manager, detalhado, 1, level=lambda: "detalhado").poll() == 3


def test_so_mostra_eventos_posteriores_ao_ponto_de_abertura(manager):
    reader = FakeReader([evento(1, "parada", "antigo"), evento(2, "parada", "novo")])
    console = Console()
    EventsThread(reader, manager, console, 1, start_id=reader.last_id() - 1).poll()
    assert console.lines == ["[iris-01] novo"]


def test_acompanhar_mostra_a_sessao_seguida_em_nivel_detalhado(manager):
    reader = FakeReader([evento(1, "subtarefa_iniciada", "t1 iniciada"),
                         evento(2, "subtarefa_iniciada", "u1 iniciada", session_id="outra")])
    console = Console()
    thread = EventsThread(reader, manager, console, 1, level=lambda: "resumo")
    thread.follow("s1")
    thread.poll()
    assert console.lines == ["[iris-01] t1 iniciada"]  # a seguida é detalhada; a outra segue o nível


def test_leitura_que_falha_nao_derruba(manager):
    class Quebrado(FakeReader):
        def since(self, *a, **k):
            raise RuntimeError("banco fora")

    assert EventsThread(Quebrado(), manager, Console(), 1).poll() == 0


def test_historico_mostra_os_ultimos_n_eventos(monkeypatch, manager):
    monkeypatch.setattr("src.config.TERMINAL_FOLLOW_HISTORY", 20)
    reader = FakeReader([evento(i, "subtarefa_iniciada", f"t{i} iniciada") for i in range(1, 26)])
    saida = Console()
    assert show_history(reader, manager.get("s1"), saida.write) == 20
    texto = "\n".join(saida.lines)
    assert "t6 iniciada" in texto and "t25 iniciada" in texto and "t5 iniciada" not in texto


def test_pesquisas_lista_estado_tempo_custo_ultimo_evento_e_pendentes(monkeypatch, manager):
    manager.add("b-01", "closed", {"mode": "semi", "motivo_parada": "solucao_encontrada"}).alias = "b-01"
    monkeypatch.setattr("src.cli.progress_view.session_costs", lambda ids: {"s1": 1.5})
    gate = FakeGate()
    gate.request("aprovar_hipotese", "h4", "Aprovar h4?", ("aprovar", "rejeitar", "editar"), session_id="s1")
    reader = FakeReader([evento(1, "plano_aprovado", "plano 1 aprovado: 2 subtarefas")])
    saida = Console()
    import time

    show_overview(manager, reader, gate, saida.write, time.time())
    texto = "\n".join(saida.lines)
    assert "iris-01" in texto and "b-01" in texto
    assert "1 pedido(s) pendente(s)" in texto and "US$ 1,50" in texto and "plano 1 aprovado" in texto
    assert "closed" in texto and "active" in texto


class FakeInbox:
    def __init__(self):
        self.posts = []

    def post(self, session_id, conteudo, tipo="orientacao"):
        self.posts.append((session_id, conteudo, tipo))


def test_comando_vai_pela_caixa_para_pesquisa_com_processo(manager):
    import os

    manager.rows["s1"].pid = os.getpid()
    inbox, saida = FakeInbox(), Console()
    assert send_command(manager, "iris-01", "pausar", None, saida.write, inbox=inbox) is True
    assert send_command(manager, "iris-01", "cancelar", "testar_svm", saida.write, inbox=inbox) is True
    assert inbox.posts == [
        ("s1", '{"comando": "pausar"}', TIPO_COMANDO),
        ("s1", '{"comando": "cancelar", "subtarefa": "testar_svm"}', TIPO_COMANDO),
    ]


def test_sessao_sem_processo_e_recusada_com_estado_e_dica(manager):
    manager.add("b-01", "aguarda_pesquisador", {}).alias = "b-01"
    inbox, saida = FakeInbox(), Console()
    assert send_command(manager, "b-01", "pausar", None, saida.write, inbox=inbox) is False
    texto = "\n".join(saida.lines)
    assert "aguarda_pesquisador" in texto and "retomar b-01" in texto and inbox.posts == []


def test_pesquisa_inexistente_e_comando_desconhecido(manager):
    saida = Console()
    assert send_command(manager, "nao-existe", "pausar", None, saida.write, inbox=FakeInbox()) is False
    assert send_command(manager, "iris-01", "formatar", None, saida.write, inbox=FakeInbox()) is False


def test_pid_que_nao_existe_mais_conta_como_sem_processo(manager):
    manager.rows["s1"].pid = 2**22 + 12345  # improvável existir
    saida = Console()
    assert send_command(manager, "iris-01", "parar", None, saida.write, inbox=FakeInbox()) is False
    assert "não tem processo" in "\n".join(saida.lines)


# --- nova-pesquisa com outra em execução ---------------------------------------------------------------------------


class _Starter:
    def __init__(self):
        self.started = []
        self.base_dir = "."

    async def start_new(self, task, **kw):
        self.started.append(task)
        return SimpleNamespace()

    async def wait_registered(self, started):
        return SimpleNamespace(alias="nova-01", pid=1)


def _repl(manager, answers):
    from src.cli.repl import Repl
    from src.session.presence import TerminalPresence
    from tests.support.session_fakes import InMemoryPresenceStore

    entradas = iter(answers)
    perguntas = []

    def entrada(prompt):
        perguntas.append(prompt)
        return next(entradas)

    saidas = Console()
    starter = _Starter()
    repl = Repl(
        mode="auto", explicit_mode=None, budget=None, args=SimpleNamespace(), starter=starter, manager=manager,
        presence=TerminalPresence("repl", store=InMemoryPresenceStore(), pid_alive=lambda pid: True),
        input_fn=entrada, console=saidas, recover=lambda s: None, gate=FakeGate(), reader=FakeReader(),
    )
    return repl, starter, perguntas, saidas


@pytest.mark.asyncio
async def test_nova_pesquisa_com_outra_em_execucao_pergunta_e_com_n_nao_cria(manager):
    manager.rows["s1"].pid = 4321
    repl, starter, perguntas, saidas = _repl(manager, ["n"])
    await repl.handle("nova-pesquisa treinar um classificador no iris")
    assert "Já há pesquisa em execução (iris-01). Iniciar outra? [s/N]" in perguntas[0]
    assert starter.started == []
    assert "Nenhuma pesquisa foi iniciada" in "\n".join(saidas.lines)


@pytest.mark.asyncio
async def test_nova_pesquisa_com_s_inicia(manager):
    manager.rows["s1"].pid = 4321
    repl, starter, perguntas, _ = _repl(manager, ["s"])
    await repl.handle("nova-pesquisa treinar um classificador no iris")
    assert starter.started == ["treinar um classificador no iris"]


@pytest.mark.asyncio
async def test_nova_pesquisa_sem_outra_em_execucao_nao_pergunta():
    manager = FakeSessionManager()
    repl, starter, perguntas, _ = _repl(manager, [])
    await repl.handle("nova-pesquisa treinar um classificador no iris")
    assert perguntas == [] and starter.started == ["treinar um classificador no iris"]
