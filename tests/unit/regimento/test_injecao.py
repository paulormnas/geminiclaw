"""Injeção do recorte no system, registro por sessão e retomada (agent-runtime: recorte em toda chamada de papel)."""

import shutil
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.agents.regimento import (
    REGIMENTO_DIR,
    carregar_regimento,
    com_regimento,
    encerrar_sessao,
    iniciar_sessao,
    sessao_atual,
)
from src.agents.validator.agent import ValidatorAgent
from tests.support.fake_recording_provider import FakeRecordingProvider

pytestmark = pytest.mark.unit

CABECALHO_DISCRIMINACAO_AUTO = "REGIMENTO DA PESQUISA (versão 1; objetivo discriminacao; modo auto)"


@pytest.fixture
def sessao_auto():
    sessao, token = iniciar_sessao("auto", "discriminacao")
    yield sessao
    encerrar_sessao(token)


def test_sem_sessao_o_prompt_segue_como_esta():
    assert sessao_atual() is None
    assert com_regimento("Você é o Developer.") == "Você é o Developer."


def test_prompt_do_papel_vem_primeiro_depois_cabecalho_e_recorte(sessao_auto):
    system = com_regimento("Você é o Developer.")
    assert system.startswith("Você é o Developer.\n\n" + CABECALHO_DISCRIMINACAO_AUTO + "\n")
    assert "## Objetivo do tipo discriminação" in system
    for fora in ("## Objetivo do tipo limiar", "## Objetivo do tipo fronteira", "## Modo assisted", "## Modo semi"):
        assert fora not in system


def test_arquivo_alterado_no_meio_da_sessao_nao_muda_o_recorte(tmp_path):
    base = tmp_path / "regimento"
    base.mkdir()
    for nome in ("regimento.md", "regimento.yaml"):
        shutil.copy(REGIMENTO_DIR / nome, base / nome)
    sessao, token = iniciar_sessao("semi", "limiar", base=base)
    try:
        antes = com_regimento("P")
        (base / "regimento.md").write_text("## Outra coisa\n<!-- secao: fluxo; aplica: comum -->\nTexto trocado.\n")
        assert com_regimento("P") == antes
        assert "Texto trocado" not in com_regimento("P")
    finally:
        encerrar_sessao(token)


def test_mudar_o_tipo_de_objetivo_troca_o_recorte_e_registra_cada_um_uma_vez():
    vistos = []
    sessao, token = iniciar_sessao("auto", None, on_recorte=vistos.append)
    try:
        com_regimento("P")
        com_regimento("P")
        sessao.definir_objetivo("limiar")
        com_regimento("P")
        sessao.definir_objetivo(None)
        com_regimento("P")
    finally:
        encerrar_sessao(token)
    assert [r.tipo_objetivo for r in vistos] == ["", "limiar"]


def test_falha_no_registro_do_recorte_nao_quebra_a_chamada():
    def falha(_):
        raise RuntimeError("telemetria fora do ar")

    sessao, token = iniciar_sessao("auto", "limiar", on_recorte=falha)
    try:
        assert "REGIMENTO DA PESQUISA" in com_regimento("P")
    finally:
        encerrar_sessao(token)


@pytest.mark.asyncio
async def test_validator_do_plano_recebe_o_recorte(sessao_auto):
    provider = FakeRecordingProvider(script=['{"status": "approved", "reason": "ok", "issues": []}'])
    plano = [{
        "agent_id": "developer", "task_name": "implementar_modelo", "prompt": "Criar script de treinamento em Python",
        "validation_criteria": ["Script executa sem erro e salva modelo"], "expected_artifacts": ["modelo.pkl"],
        "depends_on": [],
    }]
    resultado = await ValidatorAgent(provider=provider).validate_plan(plano, prompt="Treinar modelo")
    assert resultado.is_valid is True
    system = provider.calls[0].system
    assert system.startswith("Você é o ValidatorAgent")
    assert CABECALHO_DISCRIMINACAO_AUTO in system


@pytest.mark.asyncio
async def test_consultor_recebe_o_recorte(sessao_auto):
    from src.agents.researcher.consult import run_consult

    provider = FakeRecordingProvider(script=['{"resposta": "use 42", "confianca": "alta"}'])
    await run_consult(provider, question="Qual seed?", web_enabled=False)
    assert provider.calls and CABECALHO_DISCRIMINACAO_AUTO in provider.calls[0].system


def test_instrucao_dos_agentes_com_agente_em_sessao_leva_recorte_apos_o_prompt(sessao_auto):
    from src.agents.developer.agent import AGENT_INSTRUCTION, root_agent

    instrucao = root_agent.instruction
    assert instrucao.startswith(AGENT_INSTRUCTION)
    assert CABECALHO_DISCRIMINACAO_AUTO in instrucao
    assert instrucao.index(CABECALHO_DISCRIMINACAO_AUTO) > len(AGENT_INSTRUCTION)
    assert "MODO DE OPERAÇÃO DA SESSÃO" not in instrucao


# --- laço autônomo: registro por sessão ---------------------------------------------------------------------------


def _loop():
    from src.orchestration.autonomous_loop import AutonomousLoop

    loop = AutonomousLoop.__new__(AutonomousLoop)
    sessoes = {}
    manager = MagicMock()
    manager.get.side_effect = lambda sid: sessoes.get(sid)
    manager.update.side_effect = lambda sid, **kw: sessoes.setdefault(sid, SimpleNamespace(payload={})).__setattr__(
        "payload", kw.get("payload", sessoes[sid].payload)
    )
    loop.orchestrator = SimpleNamespace(session_manager=manager, get_resume=lambda sid: None)
    return loop, sessoes


@pytest.fixture
def eventos(monkeypatch):
    registrados = []
    telemetria = MagicMock()
    telemetria.record_agent_event.side_effect = lambda **kw: registrados.append(kw)
    monkeypatch.setattr("src.orchestration.autonomous_loop.get_telemetry", lambda: telemetria)
    return registrados


def test_inicio_da_sessao_registra_versao_e_hash(eventos):
    loop, sessoes = _loop()
    sessoes["s1"] = SimpleNamespace(payload={})
    token, _ = loop._iniciar_regimento("s1", "auto")
    try:
        reg = carregar_regimento()
        inicio = [e for e in eventos if e["event_type"] == "regimento_sessao"][0]["payload"]
        assert inicio["versao"] == 1 and inicio["regimento_sha256"] == reg.sha256 and inicio["adendo_sha256"] == ""
        com_regimento("P")
        com_recorte = [e["payload"] for e in eventos if e["payload"].get("recorte_sha256")]
        assert com_recorte and com_recorte[0]["modo"] == "auto"
        gravado = sessoes["s1"].payload["regimento"]
        assert gravado["regimento_sha256"] == reg.sha256 and gravado["recortes"][0]["modo"] == "auto"
    finally:
        encerrar_sessao(token)


def test_retomada_com_regimento_novo_registra_regimento_alterado(eventos):
    loop, sessoes = _loop()
    sessoes["s0"] = SimpleNamespace(payload={"regimento": {"regimento_sha256": "a" * 64}})
    sessoes["s1"] = SimpleNamespace(payload={})
    loop.orchestrator.get_resume = lambda sid: None
    loop._resume = lambda sid: SimpleNamespace(source_session_id="s0")
    token, _ = loop._iniciar_regimento("s1", "semi")
    try:
        alterado = [e["payload"] for e in eventos if e["event_type"] == "regimento_alterado"]
        assert len(alterado) == 1
        assert alterado[0]["regimento_sha256_registrado"] == "a" * 64
        assert alterado[0]["regimento_sha256_atual"] == carregar_regimento().sha256
    finally:
        encerrar_sessao(token)


def test_retomada_com_o_mesmo_regimento_nao_registra_alteracao(eventos):
    loop, sessoes = _loop()
    sessoes["s0"] = SimpleNamespace(payload={"regimento": {"regimento_sha256": carregar_regimento().sha256}})
    sessoes["s1"] = SimpleNamespace(payload={})
    loop._resume = lambda sid: SimpleNamespace(source_session_id="s0")
    token, _ = loop._iniciar_regimento("s1", "semi")
    try:
        assert not [e for e in eventos if e["event_type"] == "regimento_alterado"]
    finally:
        encerrar_sessao(token)


@pytest.mark.asyncio
async def test_agent_context_da_tentativa_leva_os_hashes_do_regimento(sessao_auto):
    from unittest.mock import AsyncMock

    from src.agent_runtime.types import AgentResult, AgentTask
    from src.orchestration.orchestrator import Orchestrator
    from tests.support.task_loop import run_tasks

    runtime = MagicMock()
    runtime.run = AsyncMock(return_value=AgentResult(agent_id="developer", session_id="s1", status="success", response={}))
    manager = MagicMock()
    manager.create.side_effect = lambda *a, **k: SimpleNamespace(id="sess", payload={}, status="running")
    orchestrator = Orchestrator(session_manager=manager, agent_runtime=runtime)

    await run_tasks(orchestrator, "Olá", [AgentTask(agent_id="developer", prompt="Olá")])

    ctx = runtime.run.call_args.args[1]
    assert ctx.regimento_sha256 == sessao_auto.regimento.sha256
    assert ctx.recorte_sha256 == sessao_auto.recorte_atual().sha256
