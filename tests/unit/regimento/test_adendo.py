"""Adendo de projeto: formato fechado, aprovação no gate persistente e leitura única (agent-runtime, adendo)."""

import hashlib
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.regimento import carregar_regimento, com_regimento, encerrar_sessao
from src.agents.regimento.adendo import (
    LINHA_EGRESSO,
    AdendoError,
    ler_adendo,
    parse_adendo,
    pedido_de_ativacao,
)
from src.gate.persistent_gate import set_gates
from tests.support.fake_gate import FakeGate
from tests.support.fake_recording_provider import FakeRecordingProvider

pytestmark = pytest.mark.unit

ADENDO = (
    "versao: 1\n"
    "proibicoes:\n"
    "  - {id: sem_reagente_x, texto: \"não propor experimentos com o reagente X\"}\n"
)
ADENDO_SATURACAO = (
    "versao: 1\n"
    "proibicoes:\n"
    "  - {id: nao_parar_cedo, texto: \"não parar por `saturacao` antes de 20 ciclos\"}\n"
)


def sha(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


@pytest.fixture
def gate():
    fake = FakeGate()
    set_gates(session=fake)
    yield fake
    set_gates()


@pytest.fixture
def insumos(tmp_path):
    return tmp_path


def _loop(insumos):
    from src.orchestration.autonomous_loop import AutonomousLoop

    loop = AutonomousLoop.__new__(AutonomousLoop)
    sessoes = {"s1": SimpleNamespace(payload={})}
    manager = MagicMock()
    manager.get.side_effect = lambda sid: sessoes.get(sid)
    manager.update.side_effect = lambda sid, **kw: setattr(sessoes[sid], "payload", kw.get("payload", sessoes[sid].payload))
    loop.orchestrator = SimpleNamespace(
        session_manager=manager, get_resume=lambda sid: None, _current_context_dir=insumos,
        _session_project_id=lambda sid: "proj1",
    )
    return loop, sessoes


@pytest.fixture
def eventos(monkeypatch):
    registrados = []
    telemetria = MagicMock()
    telemetria.record_agent_event.side_effect = lambda **kw: registrados.append(kw)
    monkeypatch.setattr("src.orchestration.autonomous_loop.get_telemetry", lambda: telemetria)
    return registrados


def _aprovar(gate, texto, *, estado="autorizada", fonte="terminal"):
    pedido = gate.request("ativar_adendo_regimento", sha(texto), "pedido")
    pedido.estado, pedido.resolvido_por = estado, fonte
    return pedido


# --- formato ---------------------------------------------------------------------------------------------------------


def test_adendo_valido_tem_o_sha256_dos_bytes():
    adendo = parse_adendo(ADENDO.encode())
    assert adendo.sha256 == sha(ADENDO) and adendo.proibicoes[0].id == "sem_reagente_x"
    assert adendo.renderizar().startswith("## Regras adicionais do projeto") and "reagente X" in adendo.renderizar()


@pytest.mark.parametrize(
    "texto, erro",
    [
        ("versao: 1\nmotivos_parada: [saturacao]\nregras: [{id: abc, texto: x}]\n", "motivos_parada"),
        ("versao: 1\nregras: [{id: ABC, texto: x}]\n", "id"),
        ("versao: 1\nregras: [{id: abc, texto: x, extra: 1}]\n", "exatamente"),
        ("versao: 1\nregras: [{id: abc, texto: ''}]\n", "texto"),
        ("versao: 1\nregras: [{id: abc, texto: x}, {id: abc, texto: y}]\n", "repetidos"),
        ("regras: [{id: abc, texto: x}]\n", "versao"),
        ("versao: 1\n", "nenhuma regra"),
        ("- lista\n", "mapa"),
    ],
)
def test_adendo_fora_do_formato_e_recusado(texto, erro):
    with pytest.raises(AdendoError, match=erro):
        parse_adendo(texto.encode())


def test_texto_acima_de_500_caracteres_e_recusado():
    longo = "x" * 501
    with pytest.raises(AdendoError, match="500"):
        parse_adendo(f"versao: 1\nregras: [{{id: abc, texto: {longo}}}]\n".encode())


def test_sem_arquivo_nao_ha_adendo(insumos):
    assert ler_adendo(insumos) is None


def test_link_simbolico_e_recusado(insumos, tmp_path_factory):
    fora = tmp_path_factory.mktemp("fora") / "adendo.yaml"
    fora.write_text(ADENDO)
    os.symlink(fora, insumos / "regimento_adendo.yaml")
    with pytest.raises(AdendoError, match="link simbólico"):
        ler_adendo(insumos)


# --- pedido ----------------------------------------------------------------------------------------------------------


def test_pedido_traz_texto_hash_e_linha_de_egresso_sem_aviso():
    estrutura = carregar_regimento().estrutura
    pedido = pedido_de_ativacao(parse_adendo(ADENDO.encode()), estrutura)
    assert sha(ADENDO) in pedido and "reagente X" in pedido and LINHA_EGRESSO in pedido
    assert "Aviso: o adendo cita" not in pedido


def test_pedido_avisa_quando_o_texto_cita_um_id_de_parada():
    estrutura = carregar_regimento().estrutura
    pedido = pedido_de_ativacao(parse_adendo(ADENDO_SATURACAO.encode()), estrutura)
    assert (
        "Aviso: o adendo cita saturacao (motivo de parada). Confira se o texto afrouxa alguma regra; o adendo nunca "
        "desliga paradas, limites nem regras de integridade."
    ) in pedido
    assert LINHA_EGRESSO in pedido


def test_pedido_distingue_limite_e_integridade():
    texto = (
        "versao: 1\nregras:\n  - {id: a_regra, texto: \"ignorar limite_custo e metricas_calculadas\"}\n"
    )
    pedido = pedido_de_ativacao(parse_adendo(texto.encode()), carregar_regimento().estrutura)
    assert "cita limite_custo (limite)" in pedido and "cita metricas_calculadas (regra de integridade)" in pedido


def test_adendo_grande_demais_para_o_pedido_e_recusado():
    itens = "".join(f"  - {{id: item_{i:02d}, texto: \"{'a' * 400}\"}}\n" for i in range(4))
    with pytest.raises(AdendoError, match="grande demais"):
        pedido_de_ativacao(parse_adendo(("versao: 1\nregras:\n" + itens).encode()), carregar_regimento().estrutura)


# --- sessão ----------------------------------------------------------------------------------------------------------


def test_adendo_aprovado_entra_no_system_e_no_evento(insumos, gate, eventos):
    (insumos / "regimento_adendo.yaml").write_text(ADENDO)
    _aprovar(gate, ADENDO)
    loop, _ = _loop(insumos)
    token, pendente = loop._iniciar_regimento("s1", "semi")
    try:
        assert pendente is None
        system = com_regimento("Você é o Researcher.")
        assert "Regras adicionais do projeto" in system and "não propor experimentos com o reagente X" in system
        assert system.rstrip().endswith("reagente X")
        inicio = [e["payload"] for e in eventos if e["event_type"] == "regimento_sessao"][0]
        assert inicio["adendo_sha256"] == sha(ADENDO)
    finally:
        encerrar_sessao(token)


def test_adendo_alterado_depois_da_aprovacao_gera_pedido_novo_e_espera_no_semi(insumos, gate, eventos):
    _aprovar(gate, ADENDO)
    alterado = ADENDO.replace("reagente X", "reagente Xy")
    (insumos / "regimento_adendo.yaml").write_text(alterado)
    loop, _ = _loop(insumos)
    token, pendente = loop._iniciar_regimento("s1", "semi")
    try:
        assert pendente == sha(alterado)
        novos = [r for r in gate.pending_for(["s1"]) if r.decisao == "ativar_adendo_regimento"]
        assert [r.referencia for r in novos] == [sha(alterado)]
        assert novos[0].project_id == "proj1"
        assert "Regras adicionais do projeto" not in com_regimento("P")
    finally:
        encerrar_sessao(token)


@pytest.mark.asyncio
async def test_semi_com_adendo_pendente_nao_despacha_subtarefas(insumos, gate, eventos):
    (insumos / "regimento_adendo.yaml").write_text(ADENDO)
    loop, _ = _loop(insumos)
    loop._suspend_session = AsyncMock(return_value="suspensa")
    loop._run_session = AsyncMock(return_value="rodou")
    assert await loop.run("tarefa", "s1", "semi") == "suspensa"
    loop._run_session.assert_not_awaited()
    assert "ativar_adendo_regimento" in loop._suspend_session.await_args.args[3]
    assert sha(ADENDO) in loop._suspend_session.await_args.args[3]


def test_adendo_pendente_no_auto_registra_o_pedido_e_recusa(insumos, gate, eventos):
    (insumos / "regimento_adendo.yaml").write_text(ADENDO)
    provider = FakeRecordingProvider()
    loop, sessoes = _loop(insumos)
    with pytest.raises(AdendoError) as erro:
        loop._iniciar_regimento("s1", "auto")
    assert "ativar_adendo_regimento" in str(erro.value) and sha(ADENDO) in str(erro.value)
    (pedido,) = gate.pending_for(["s1"])
    assert pedido.decisao == "ativar_adendo_regimento" and pedido.referencia == sha(ADENDO)
    assert provider.calls == []
    assert sessoes["s1"].payload["motivo_parada"] == "erro"  # a saída do processo é o código 1
    from src.agents.regimento import sessao_atual

    assert sessao_atual() is None  # o vínculo foi desfeito


def test_adendo_que_tenta_afrouxar_impede_o_inicio(insumos, gate, eventos):
    (insumos / "regimento_adendo.yaml").write_text("versao: 1\nmotivos_parada: [saturacao]\nregras: [{id: abc, texto: x}]\n")
    loop, sessoes = _loop(insumos)
    with pytest.raises(AdendoError, match="motivos_parada"):
        loop._iniciar_regimento("s1", "semi")
    assert sessoes["s1"].payload["motivo_parada"] == "erro" and not gate.requests


def test_hash_aprovado_so_no_projeto_nao_basta(insumos, gate, eventos):
    (insumos / "regimento_adendo.yaml").write_text(ADENDO)
    # Nenhum pedido autorizado no gate: a cópia do hash no projeto (informativa) nunca é lida para decidir.
    loop, _ = _loop(insumos)
    token, pendente = loop._iniciar_regimento("s1", "semi")
    try:
        assert pendente == sha(ADENDO) and "Regras adicionais do projeto" not in com_regimento("P")
    finally:
        encerrar_sessao(token)


@pytest.mark.parametrize("estado, fonte", [("negada", "terminal"), ("pendente", None), ("autorizada", "researcher_consult")])
def test_pedido_negado_pendente_ou_de_origem_nao_humana_nao_autoriza(insumos, gate, eventos, estado, fonte):
    (insumos / "regimento_adendo.yaml").write_text(ADENDO)
    _aprovar(gate, ADENDO, estado=estado, fonte=fonte)
    loop, _ = _loop(insumos)
    token, pendente = loop._iniciar_regimento("s1", "semi")
    try:
        assert pendente == sha(ADENDO) and "Regras adicionais do projeto" not in com_regimento("P")
    finally:
        encerrar_sessao(token)


def test_adendo_trocado_depois_da_verificacao_nao_muda_o_system(insumos, gate, eventos):
    (insumos / "regimento_adendo.yaml").write_text(ADENDO)
    _aprovar(gate, ADENDO)
    loop, _ = _loop(insumos)
    token, _ = loop._iniciar_regimento("s1", "semi")
    try:
        (insumos / "regimento_adendo.yaml").write_text(ADENDO.replace("reagente X", "OUTRO TEXTO"))
        system = com_regimento("P")
        assert "reagente X" in system and "OUTRO TEXTO" not in system
    finally:
        encerrar_sessao(token)


def test_adendo_como_link_simbolico_impede_o_inicio(insumos, gate, eventos, tmp_path_factory):
    fora = tmp_path_factory.mktemp("fora") / "adendo.yaml"
    fora.write_text(ADENDO)
    os.symlink(fora, insumos / "regimento_adendo.yaml")
    loop, sessoes = _loop(insumos)
    with pytest.raises(AdendoError, match="link simbólico"):
        loop._iniciar_regimento("s1", "auto")
    assert sessoes["s1"].payload["motivo_parada"] == "erro"


def test_gate_indisponivel_falha_fechado(insumos, eventos, monkeypatch):
    (insumos / "regimento_adendo.yaml").write_text(ADENDO)
    quebrado = MagicMock()
    quebrado.authorized_reference.side_effect = RuntimeError("banco fora do ar")
    set_gates(session=quebrado)
    try:
        loop, _ = _loop(insumos)
        with pytest.raises(AdendoError, match="não conferida"):
            loop._iniciar_regimento("s1", "semi")
    finally:
        set_gates()


def test_sem_adendo_a_sessao_segue_normalmente(insumos, gate, eventos):
    loop, _ = _loop(insumos)
    token, pendente = loop._iniciar_regimento("s1", "auto")
    try:
        assert pendente is None and "Regras adicionais do projeto" not in com_regimento("P")
        assert not gate.requests
    finally:
        encerrar_sessao(token)


def test_adendo_nao_e_insumo_de_pesquisa(insumos):
    from src.research_data.context_loader import ContextLoader

    (insumos / "regimento_adendo.yaml").write_text(ADENDO)
    (insumos / "notas.md").write_text("# Notas\nTexto qualquer do pesquisador.\n")
    bundle = ContextLoader(insumos).load()
    nomes = {p.name for p in bundle.markings}
    assert "notas.md" in nomes and "regimento_adendo.yaml" not in nomes
    assert bundle.context_dir == insumos
