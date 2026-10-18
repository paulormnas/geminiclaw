"""Consulta só leitura ao Researcher pelo terminal (researcher-consult do session-events-terminal)."""

import json
import os
import sys
from types import SimpleNamespace

import pytest

import src.cli.terminal_consult as cli
from src import config
from src.agents.researcher import terminal_consult as tc
from src.agents.researcher.consult import ConsultError
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.provenance import Actor
from src.knowledge.read_only import ReadOnlyGraphStore, ReadOnlyQdrant, ReadOnlyViolation
from src.llm.base import LLMResponse, ToolCall
from tests.support.fake_recording_provider import FakeRecordingProvider

pytestmark = pytest.mark.unit

ORQ = Actor(kind="orquestrador")


def sessao(**over):
    base = {"id": "s1", "alias": "iris-01", "status": "active", "resumo": "Estudar o iris", "payload": {"mode": "auto"}}
    base.update(over)
    return SimpleNamespace(**base)


class Reader:
    def tail(self, session_id, n):
        return [SimpleNamespace(resumo=f"evento {i}") for i in range(1, 4)][-n:]


# --- invólucros somente leitura ---------------------------------------------------------------------------------


def test_grafo_somente_leitura_deixa_ler_e_recusa_escrever():
    store = ReadOnlyGraphStore(InMemoryGraphStore())
    assert store.find_nodes("Hipotese", {}, limit=5) == []
    for escrita in ("create_node", "update_node", "create_edge", "set_edge_status", "update_edge", "record_audit_note"):
        with pytest.raises(ReadOnlyViolation):
            getattr(store, escrita)
    with pytest.raises(ReadOnlyViolation):
        store.qualquer_coisa_nova
    with pytest.raises(ReadOnlyViolation):
        store.novo_atributo = 1


def test_qdrant_somente_leitura():
    chamadas = []
    inner = SimpleNamespace(search=lambda *a, **k: chamadas.append("search"), upsert=lambda *a, **k: chamadas.append("upsert"),
                            delete=lambda *a, **k: chamadas.append("delete"))
    qdrant = ReadOnlyQdrant(inner)
    qdrant.search("c", [0.1])
    for escrita in ("upsert", "delete", "create_collection", "upload_points", "set_payload"):
        with pytest.raises(ReadOnlyViolation):
            getattr(qdrant, escrita)
    assert chamadas == ["search"]


# --- contexto ----------------------------------------------------------------------------------------------------


def _store_com_hipoteses():
    from tests.support.hypothesis_world import HypothesisWorld

    world = HypothesisWorld()
    h1 = world.hypothesis("RF supera o baseline", status="proposta")
    world.store.update_node(h1, {"status": "refutada"}, actor=ORQ)
    h2 = world.hypothesis("kNN melhora com padronização", status="em_teste")
    return world, h1, h2


def test_contexto_tem_hipoteses_dentro_do_bloco_delimitado():
    world, h1, h2 = _store_com_hipoteses()
    contexto = cli.build_context(
        sessao(payload={"mode": "auto", "project_id": world.pid}), ReadOnlyGraphStore(world.store), Reader(),
    )
    bloco = contexto[contexto.index('<dado_nao_confiavel origem="hipoteses_do_projeto">'):]
    bloco = bloco[:bloco.index("</dado_nao_confiavel>")]
    assert h1 in bloco and h2 in bloco and "refutada" in bloco and "em_teste" in bloco
    assert '<dado_nao_confiavel origem="pesquisa">' in contexto and "evento 1" in contexto
    assert len(contexto) <= config.TERMINAL_CONSULT_CONTEXT_MAX_CHARS


def test_contexto_respeita_o_teto_e_um_bloco_indisponivel_nao_derruba():
    class Quebrado(Reader):
        def tail(self, *a):
            raise RuntimeError("banco fora")

    contexto = cli.build_context(sessao(), InMemoryGraphStore(), Quebrado(), max_chars=900)
    assert len(contexto) <= 900 and "indisponível" in contexto


# --- ask: ferramentas, resposta e consumo ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_devolve_resposta_e_orientacao_e_o_prompt_leva_o_contexto():
    provider = FakeRecordingProvider(script=[
        json.dumps({"resposta": "h1 foi refutada", "orientacao_sugerida": "priorize modelos lineares"})
    ])
    resposta = await tc.ask(provider, "quais hipóteses foram refutadas?", "<dado_nao_confiavel>h1 h2</dado_nao_confiavel>",
                            web_enabled=False)
    assert resposta == tc.ConsultaTerminal("h1 foi refutada", "priorize modelos lineares")
    chamada = provider.calls[0]
    assert "consulta pelo terminal" in chamada.system and "h1 h2" in str(chamada.messages)


@pytest.mark.asyncio
async def test_orientacao_vazia_vira_none():
    provider = FakeRecordingProvider(script=['{"resposta": "ok", "orientacao_sugerida": "  "}'])
    assert (await tc.ask(provider, "q", "c", web_enabled=False)).orientacao_sugerida is None


@pytest.mark.asyncio
async def test_ferramentas_expostas_sao_exatamente_quick_search_e_web_reader():
    provider = FakeRecordingProvider(script=['{"resposta": "ok"}'])
    await tc.ask(provider, "q", "c", web_enabled=True)
    nomes = sorted(t["function"]["name"] for t in provider.calls[0].tools)
    assert nomes == sorted(tc.TOOL_NAMES) == ["quick_search", "web_reader"]


@pytest.mark.asyncio
async def test_resposta_ilegivel_levanta_erro_de_consulta():
    provider = FakeRecordingProvider(script=["isto não é json"])
    with pytest.raises(ConsultError):
        await tc.ask(provider, "q", "c", web_enabled=False)


@pytest.mark.asyncio
async def test_teto_de_tokens_por_pergunta(monkeypatch):
    monkeypatch.setattr(config, "TERMINAL_CONSULT_MAX_TOKENS", 100)
    provider = FakeRecordingProvider(script=[
        LLMResponse(text="", tool_calls=[ToolCall(id="c1", name="quick_search", arguments={"query": "docs"})],
                    usage={"prompt_tokens": 90, "completion_tokens": 30}),
    ])
    with pytest.raises(ConsultError, match="teto"):
        await tc.ask(provider, "q", "c", web_enabled=True)


@pytest.mark.asyncio
async def test_consumo_e_registrado_com_origem_consulta_terminal(monkeypatch):
    registros = []
    monkeypatch.setattr("src.agents.researcher.consult.record_llm_call",
                        lambda provider, response, latency, agent_id, task_name=None, **kw:
                        registros.append((agent_id, task_name, response.usage)))
    provider = FakeRecordingProvider(script=[
        LLMResponse(text='{"resposta": "ok"}', usage={"prompt_tokens": 1000, "completion_tokens": 500})
    ])
    await tc.ask(provider, "q", "c", web_enabled=False)
    assert registros == [("researcher", "consulta_terminal", {"prompt_tokens": 1000, "completion_tokens": 500})]


# --- processo filho: saída, ambiente e recusa ------------------------------------------------------------------


def test_ambiente_do_filho_sem_credencial_do_terminal_e_com_banco_somente_leitura():
    env = cli.consult_env({
        "PATH": "/usr/bin", "TERMINAL_DATABASE_URL_FILE": "/x", "TERMINAL_DATABASE_URL": "postgres://u:p@h/db",
        "PGPASSWORD": "segredo", "PGPASSFILE": "/y", "PGSERVICEFILE": "/z", "SESSION_ENV_DENYLIST": "OUTRA_CHAVE",
        "OUTRA_CHAVE": "v",
    })
    for negado in ("TERMINAL_DATABASE_URL_FILE", "TERMINAL_DATABASE_URL", "PGPASSWORD", "PGPASSFILE", "PGSERVICEFILE",
                   "OUTRA_CHAVE"):
        assert negado not in env
    assert "default_transaction_read_only=on" in env["PGOPTIONS"] and env["PATH"] == "/usr/bin"


@pytest.mark.parametrize("bruto, esperado", [
    ('{"resposta": "ok \\u001b[2J fim", "orientacao_sugerida": "siga \\u001b]0;x\\u0007 assim"}', ("ok", "fim")),
])
def test_resposta_do_filho_e_saneada(bruto, esperado):
    saida = cli.parse_outcome(bruto)
    assert saida.ok
    texto = saida.resposta + (saida.orientacao_sugerida or "")
    assert "\x1b" not in texto and "\x07" not in texto
    assert all(parte in saida.resposta for parte in esperado)
    assert "siga" in saida.orientacao_sugerida and "assim" in saida.orientacao_sugerida


@pytest.mark.parametrize("bruto", ["", "lixo", "[]", '{"resposta": ""}', '{"resposta": 3}'])
def test_saida_ilegivel_do_filho_vira_erro(bruto):
    assert not cli.parse_outcome(bruto).ok


def test_motivo_de_recusa_do_filho_e_exibido_saneado():
    saida = cli.parse_outcome('{"erro": "política self_hosted_only \\u001b[2J recusou"}')
    assert not saida.ok and "\x1b" not in saida.erro and "self_hosted_only" in saida.erro


def test_processo_filho_real_em_pid_diferente_sem_a_credencial(tmp_path, monkeypatch):
    """Scenario: Consulta em processo filho sem a credencial — usa um módulo de teste no lugar de ``terminal_consult``."""
    modulo = tmp_path / "filho_de_teste.py"
    modulo.write_text(
        "import json, os, sys\n"
        "pedido = json.load(open(sys.argv[sys.argv.index('--request') + 1]))\n"
        "chaves = ('TERMINAL_DATABASE_URL_FILE', 'PGPASSWORD', 'PGOPTIONS', 'GEMINICLAW_SESSION_PROCESS')\n"
        "print(json.dumps({'resposta': json.dumps({'pid': os.getpid(), 'tem': [k for k in chaves if k in os.environ], "
        "'pergunta': pedido['pergunta']})}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    ambiente = {**os.environ, "PYTHONPATH": str(tmp_path), "TERMINAL_DATABASE_URL_FILE": "/x", "PGPASSWORD": "s"}
    saida = cli.run_consult_process("quais hipóteses?", "s1", environ=ambiente, module="filho_de_teste")
    assert saida.ok
    visto = json.loads(saida.resposta)  # a resposta do filho de teste é um JSON dentro do texto
    assert visto["pid"] != os.getpid() and visto["pergunta"] == "quais hipóteses?"
    assert "TERMINAL_DATABASE_URL_FILE" not in visto["tem"] and "PGPASSWORD" not in visto["tem"]
    assert "PGOPTIONS" in visto["tem"]  # o filho nasce com o banco relacional somente leitura


def test_pedido_vai_por_arquivo_e_nao_pela_linha_de_comando(tmp_path):
    modulo = tmp_path / "filho_argv.py"
    modulo.write_text(
        "import json, sys\nprint(json.dumps({'resposta': ' '.join(sys.argv)}))\n", encoding="utf-8"
    )
    ambiente = {**os.environ, "PYTHONPATH": str(tmp_path)}
    saida = cli.run_consult_process("pergunta secreta", "s1", environ=ambiente, module="filho_argv")
    assert "secreta" not in saida.resposta and "--request" in saida.resposta


def test_tempo_limite_e_tratado(tmp_path):
    modulo = tmp_path / "filho_lento.py"
    modulo.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    saida = cli.run_consult_process("q", "s1", environ={**os.environ, "PYTHONPATH": str(tmp_path)},
                                    module="filho_lento", timeout=0.5)
    assert not saida.ok and "tempo limite" in saida.erro


def test_processo_do_terminal_nao_executa_o_modelo():
    """O módulo do terminal (``repl``) só importa o lado do terminal da consulta."""
    import ast
    import pathlib

    fonte = pathlib.Path(sys.modules["src.cli.repl"].__file__).read_text(encoding="utf-8")
    importados = {n.module for n in ast.walk(ast.parse(fonte)) if isinstance(n, ast.ImportFrom) and n.module}
    assert "src.agents.researcher.terminal_consult" not in importados
    assert "src.agents.researcher.consult" not in importados


# --- filho: caminho completo com dependências simuladas --------------------------------------------------------------


def _prepara_filho(monkeypatch, provider):
    from unittest.mock import AsyncMock

    store = InMemoryGraphStore()
    monkeypatch.setattr("src.session.manager.SessionManager.get", lambda self, sid: sessao(id=sid))
    monkeypatch.setattr("src.knowledge.factory.open_graph_store", lambda *a, **k: store)
    monkeypatch.setattr("src.gate.persistent_gate.PersistentGate.pending", lambda self, ids=None: [])
    monkeypatch.setattr("src.session.events.EventReader.tail", lambda self, sid, n: [])
    monkeypatch.setattr("src.llm.session.build_session_routing", AsyncMock(return_value=SimpleNamespace(papeis={})))
    monkeypatch.setattr("src.llm.session.bind_session_routing", lambda routing: None)
    monkeypatch.setattr("src.egress.routing.ModelRouter.get_provider", staticmethod(lambda role, **k: provider))
    vistos = {}
    monkeypatch.setattr("src.llm.metering.bind_execution", lambda execution, session: vistos.update(
        execucao=execution, sessao=session))
    return vistos


@pytest.mark.asyncio
async def test_filho_monta_o_contexto_e_amarra_o_consumo_a_pesquisa_consultada(monkeypatch):
    provider = FakeRecordingProvider(script=['{"resposta": "h1 foi refutada", "orientacao_sugerida": null}'])
    vistos = _prepara_filho(monkeypatch, provider)
    monkeypatch.setattr("src.agents.researcher.consult.consult_tools", lambda web: [])
    resultado, codigo = await cli._child("quais hipóteses foram refutadas?", "s1")
    assert codigo == 0 and resultado == {"resposta": "h1 foi refutada", "orientacao_sugerida": None}
    assert vistos == {"execucao": "s1", "sessao": "s1"}  # o consumo vai para o execution_id da pesquisa
    assert "REGIMENTO DA PESQUISA" in provider.calls[0].system and "<dado_nao_confiavel" in str(provider.calls[0].messages)


@pytest.mark.asyncio
async def test_filho_recusa_pela_politica_de_dados_sem_chamar_o_provedor_interno(monkeypatch):
    """Scenario: Localidade do projeto — o EgressGate recusa antes do provedor interno."""
    interno = FakeRecordingProvider(script=['{"resposta": "não deveria sair"}'])

    class Gated:
        model_name = "nuvem/modelo"

        async def generate(self, *a, **k):
            raise PermissionError("destino não permitido pela política self_hosted_only")

    _prepara_filho(monkeypatch, Gated())
    resultado, codigo = await cli._child("pergunta", "s1")
    assert codigo == cli.EXIT_REFUSED and "self_hosted_only" in resultado["erro"] and interno.calls == []


@pytest.mark.asyncio
async def test_filho_com_pesquisa_inexistente(monkeypatch):
    monkeypatch.setattr("src.session.manager.SessionManager.get", lambda self, sid: None)
    resultado, codigo = await cli._child("pergunta", "nao-existe")
    assert codigo == cli.EXIT_REFUSED and "não encontrada" in resultado["erro"]
