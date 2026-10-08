"""Marca persistida, perfil misto, limite de volume e demais cenários da spec data-egress (v18.5-egress-gate)."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.continuity import CheckpointError, CheckpointRecorder, SubtaskState, plan_entry, read_checkpoint
from src.egress import filters
from src.egress.fragments import ContentOrigin, PromptFragment, labeled, mark_tainted
from src.egress.persisted import (
    TAINT_TAG,
    legacy_tainted,
    read_mark,
    resumed_text_tainted,
    resumo_marca,
    tag_text,
    tags_tainted,
    with_taint_tag,
)
from src.llm.allocation import allocation_banner_lines, mixed_profile_warning
from src.llm.session import build_session_routing
from src.orchestrator import AgentTask
from src.subtask_output import SubtaskOutput
from src.usage import StopReason, UsageBudget, UsageTracker

pytestmark = pytest.mark.unit


# --- Requisito: contaminação reaplicada por destino (marca persistida) ---------------------------------------------

def test_retomada_com_outro_catalogo(gate, third_party, tmp_path):
    """Cenário "Retomada com outro catálogo": a marca gravada na produção vale; os números chegam como marcadores."""
    sdir = tmp_path / "out" / "sessao-1"
    sdir.mkdir(parents=True)
    rec = CheckpointRecorder.start(sdir, session_id="sessao-1", project_id=None, continues_session_id=None,
                                   prompt="p", modo="auto")
    rec.set_plan([plan_entry(AgentTask(agent_id="developer", prompt="x", task_name="treino", subtask_id="i1"))])
    rec.subtask_finished("treino", status="concluida", tentativas=1, resumo="acurácia 0.93 no teste",
                         marca=resumo_marca(True, "developer"))

    # A sessão nova lê o checkpoint com OUTRO catálogo (nenhum papel com dados brutos).
    checkpoint, _ = read_checkpoint(sdir)
    state = checkpoint.find("treino")
    assert state.resultado_marca == {"origem": "instrucao", "tainted": True, "produzido_por": "developer"}
    session_manager = MagicMock()  # o perfil da sessão de origem não é nem consultado: há marca gravada
    assert resumed_text_tainted(state, "sessao-1", session_manager) is True
    session_manager.get.assert_not_called()

    output = SubtaskOutput(
        task_name="treino", agent_id="developer", status="success", text_summary=state.resultado_resumo, tainted=True
    )
    contexto = output.to_context_string()
    enviado = gate.prepare_llm([labeled("user", PromptFragment(contexto, ContentOrigin.INSTRUCAO))], None, third_party)
    assert "acurácia <num padrão=d.dd> no teste" in enviado.messages[0]["content"]
    assert "0.93" not in enviado.messages[0]["content"]


def test_marca_falsa_no_checkpoint_e_recusada():
    base = {"task_name": "t", "status": "concluida"}
    for bad in ({"tainted": "sim"}, "texto", {"tainted": True, "origem": "x" * 40}):
        with pytest.raises(CheckpointError):
            SubtaskState.from_dict({**base, "resultado_marca": bad})
    ok = SubtaskState.from_dict({**base, "resultado_marca": resumo_marca(False, "reviewer")})
    assert ok.to_dict()["resultado_marca"]["tainted"] is False
    assert "resultado_marca" not in SubtaskState.from_dict(base).to_dict()  # checkpoint antigo segue igual


def test_texto_sem_marca_segue_a_regra_do_perfil_da_sessao_produtora():
    estado = SimpleNamespace(resultado_marca=None)
    com_dados = {"papeis": {"curator": {"aceita_dados_brutos": True}, "researcher": {"aceita_dados_brutos": False}}}
    sem_dados = {"papeis": {"researcher": {"aceita_dados_brutos": False}}}
    for profile, esperado in ((com_dados, True), (sem_dados, False), (None, False)):
        sm = MagicMock()
        sm.get.return_value = SimpleNamespace(payload={"allocation_profile": profile} if profile else {})
        assert resumed_text_tainted(estado, "origem", sm) is esperado
        assert legacy_tainted(profile) is esperado


def test_marca_malformada_e_lida_como_contaminada():
    estado = SimpleNamespace(resultado_marca={"tainted": "talvez"})
    assert resumed_text_tainted(estado, "x", MagicMock()) is True
    with pytest.raises(ValueError):
        read_mark({"tainted": "talvez"})


def test_tag_de_memoria_de_longo_prazo():
    assert with_taint_tag(["a"], True) == ["a", TAINT_TAG]
    assert with_taint_tag(["a", TAINT_TAG], False) == ["a"]
    assert tags_tainted(["x", TAINT_TAG]) and not tags_tainted(["x"]) and not tags_tainted(None)


def test_resumo_de_memoria_marca_entradas_contaminadas(gate, third_party):
    from src.skills.memory.long_term import LongTermMemory, LongTermMemoryEntry

    memoria = LongTermMemory.__new__(LongTermMemory)
    entradas = [
        LongTermMemoryEntry(id="1", key="a", value="valor 12.4", source="x", importance=0.9, tags=[TAINT_TAG]),
        LongTermMemoryEntry(id="2", key="b", value="valor 7.5", source="x", importance=0.9, tags=[]),
    ]
    with patch.object(LongTermMemory, "search", return_value=entradas):
        resumo = memoria.summarize_for_context()
    enviado = gate.prepare_llm([], f"Papel.\n{resumo}", third_party).system
    assert "a: valor <num padrão=dd.d>" in enviado and "b: valor 7.5" in enviado and "⟦" not in enviado


def test_tag_text_sem_marca_usa_o_perfil_corrente(monkeypatch):
    monkeypatch.setattr("src.egress.gate.any_role_raw", lambda: True)
    assert tag_text("x", None) == mark_tainted("x") and tag_text("x", False) == "x" and tag_text("x", True) != "x"


def test_resultado_de_agente_com_dados_brutos_e_contaminado(monkeypatch):
    monkeypatch.setattr("src.egress.gate.role_tainted", lambda role: role == "developer")
    resultado = SimpleNamespace(response={"text": "média 12.4"}, status="success")
    assert SubtaskOutput.from_agent_result("t", "developer", resultado).tainted is True
    assert SubtaskOutput.from_agent_result("t", "reviewer", resultado).tainted is False


def test_escrita_de_memoria_por_agente_com_dados_brutos_leva_a_tag(monkeypatch):
    from src.agent_runtime.context import AgentContext, bind_agent_context, current_context
    from src.skills.memory.skill import _writer_tags

    assert _writer_tags(["a"]) == ["a"]  # sem agente (escrita programática): sem marca
    token = current_context.set(None)
    try:
        bind_agent_context(AgentContext(session_id="s", agent_session_id="s-a", agent_id="developer", mode="auto",
                                        output_dir=Path("/tmp/x"), model="ollama/qwen3:8b"))
        monkeypatch.setattr("src.egress.gate.caller_tainted", lambda: True)
        assert TAINT_TAG in _writer_tags(["a"])
    finally:
        current_context.reset(token)


# --- Perfil misto -------------------------------------------------------------------------------------------------

@pytest.fixture
def nuvem(monkeypatch):
    monkeypatch.setattr("src.config.LLM_DATA_POLICY", "third_party_allowed")
    monkeypatch.setattr("src.config.GEMINI_API_KEY", "AIza-chave-ficticia-de-teste")
    monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", "sk-ant-chave-ficticia-de-teste")


@pytest.mark.asyncio
async def test_perfil_misto(nuvem, capsys):
    """Cenário "Perfil misto": o banner mostra o aviso com os papéis de cada grupo."""
    from src.cli import print_session_banner

    routing = await build_session_routing()
    aviso = mixed_profile_warning(routing)
    assert aviso.startswith("⚠ Perfil misto: saídas de curator serão filtradas antes de ir a ")
    assert "researcher" in aviso and "developer" in aviso
    print_session_banner("assisted", context_dir="/inexistente", llm_routing=routing)
    saida = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert aviso in saida
    assert len(allocation_banner_lines(routing)) == len(routing.papeis)  # as linhas por papel não mudam


@pytest.mark.asyncio
async def test_perfil_homogeneo_nao_gera_aviso(monkeypatch):
    routing = await build_session_routing()  # política self_hosted_only: todos os papéis no nó
    assert mixed_profile_warning(routing) is None


# --- Orquestrador ----------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orquestrador_cria_o_portao_e_grava_k_no_payload(nuvem):
    from src.orchestrator import AgentTask, Orchestrator
    from src.session import Session

    session_manager = MagicMock()
    session_manager.create.return_value = Session(
        id="sess_master", agent_id="orchestrator", status="active", created_at="", updated_at="", payload={}
    )
    runtime = MagicMock()
    orchestrator = Orchestrator(session_manager=session_manager, agent_runtime=runtime)

    with patch.object(orchestrator, "_execute_agent", AsyncMock(side_effect=RuntimeError("parou"))):
        with pytest.raises(RuntimeError, match="parou"):
            await orchestrator.handle_request("teste", [AgentTask(agent_id="developer", prompt="p")])

    payload = session_manager.update.call_args_list[0].kwargs["payload"]
    assert payload["locality_min_group_size"] == 10
    assert payload["budget"]["max_egress_bytes"] == 2_000_000
    gate = orchestrator._egress_gates["sess_master"]
    assert gate.session_id == "sess_master" and gate.max_egress_bytes == 2_000_000


@pytest.mark.asyncio
async def test_orquestrador_nao_inicia_sem_locality_min_group_size(monkeypatch):
    from src import config
    from src.orchestrator import AgentTask, Orchestrator

    monkeypatch.setattr(config, "LOCALITY_MIN_GROUP_SIZE", None)
    session_manager = MagicMock()
    orchestrator = Orchestrator(session_manager=session_manager, agent_runtime=MagicMock())
    with pytest.raises(RuntimeError, match="LOCALITY_MIN_GROUP_SIZE"):
        await orchestrator.handle_request("teste", [AgentTask(agent_id="developer", prompt="p")])
    session_manager.create.assert_not_called()  # nenhum registro foi criado


# --- Requisito: limite de volume (UsageTracker) --------------------------------------------------------------------

def _tracker(bytes_now, limit=10000):
    budget = UsageBudget(max_tokens=100_000, max_minutes=60, max_task_retries=3, max_connection_retries=5,
                         closing_reserve_pct=0.05, max_egress_bytes=limit)
    return UsageTracker(budget, "exec", token_reader=lambda: 0, connection_retry_reader=lambda: 0,
                        egress_reader=lambda: bytes_now[0], clock=lambda: 0.0)


def test_limite_atingido():
    """Cenário "Limite atingido": nenhuma nova subtarefa e fechamento com `motivo_parada="limite_egresso"`."""
    bytes_now = [9999]
    tracker = _tracker(bytes_now)
    assert tracker.check().should_close is False
    bytes_now[0] = 10_000
    status = tracker.check()
    assert status.egress_exhausted and status.should_close and status.egress_bytes == 10_000
    assert status.stop_reason is StopReason.EGRESS and status.stop_reason.value == "limite_egresso"


def test_prioridade_do_motivo_de_parada_com_egresso():
    budget = UsageBudget(max_tokens=1000, max_minutes=60, max_task_retries=3, max_connection_retries=5,
                         closing_reserve_pct=0.0, max_egress_bytes=10)
    tracker = UsageTracker(budget, "e", token_reader=lambda: 5000, connection_retry_reader=lambda: 0,
                           egress_reader=lambda: 50, clock=lambda: 0.0)
    assert tracker.check().stop_reason is StopReason.TOKENS  # tokens > tempo > conexão > egresso


def test_orcamento_valida_o_limite_e_o_le_da_configuracao(monkeypatch):
    with pytest.raises(ValueError):
        UsageBudget(max_tokens=1, max_minutes=1, max_task_retries=1, max_connection_retries=1,
                    closing_reserve_pct=0.0, max_egress_bytes=0)
    monkeypatch.setattr("src.config.EGRESS_SESSION_MAX_BYTES", 12345)
    assert UsageBudget.from_config().max_egress_bytes == 12345
    assert UsageBudget.from_config(max_egress_bytes=7).max_egress_bytes == 7


def test_tracker_le_o_volume_do_registro_de_egresso_por_padrao(gate, third_party):
    """`egress_bytes_for_session` soma `bytes_saida_execucao_novos` do `egress_log` (leitor padrão do tracker)."""
    from src.egress.log import EgressLog

    class _Shared(EgressLog):
        pass

    # Grava de verdade no banco simulado (autouse) pelo `EgressLog` real e lê pelo leitor padrão.
    real = EgressLog("exec-egresso", None)
    from src.egress.gate import EgressGate

    portao = EgressGate("exec-egresso", log=real, min_group_size=10)
    mensagem = labeled("tool", PromptFragment("saida " * 20, ContentOrigin.SAIDA_EXECUCAO))
    portao.prepare_llm([mensagem], None, third_party)
    budget = UsageBudget(max_tokens=1000, max_minutes=60, max_task_retries=3, max_connection_retries=5,
                         closing_reserve_pct=0.0, max_egress_bytes=100)
    tracker = UsageTracker(budget, "exec-egresso", token_reader=lambda: 0, connection_retry_reader=lambda: 0,
                           clock=lambda: 0.0)
    status = tracker.check()
    assert status.egress_bytes == len("saida " * 20) and status.egress_exhausted
    assert portao.egress_bytes_for_session() == len("saida " * 20)


def test_limite_de_egresso_e_um_motivo_retomavel():
    from src.continuity import MOTIVOS_RETOMAVEIS

    assert "limite_egresso" in MOTIVOS_RETOMAVEIS


# --- Requisito: Developer instruído a imprimir agregados ------------------------------------------------------------

def test_prompt_do_developer_manda_imprimir_agregados():
    """Cenário "Prompt renderizado"."""
    from agents.developer.agent import AGENT_INSTRUCTION  # noqa: F401  (instrução renderizada do módulo)

    texto = AGENT_INSTRUCTION() if callable(AGENT_INSTRUCTION) else AGENT_INSTRUCTION
    assert "IMPRIMA AGREGADOS, NÃO DADOS" in texto
    assert "head()" in texto and "print(df)" in texto and "registros" in texto
    assert "df.dtypes" in texto and "df.shape" in texto


# --- Planejamento: marcas em linha nos prompts --------------------------------------------------------------------

def test_bloco_de_input_context_e_retido_para_destino_sem_dados_brutos(gate, third_party, remote_raw):
    from src.egress.fragments import mark_research_data

    bloco = mark_research_data("[CONTEXTO CIENTÍFICO — input_context/]\nAmostra: [[1.5, 2.5]]", "input_context/")
    prompt = f"MODO: PLAN\nCrie um plano.\n{bloco}\nRetorne JSON."
    msg = labeled("user", PromptFragment(prompt, ContentOrigin.INSTRUCAO))
    fora = gate.prepare_llm([msg], None, third_party).messages[0]["content"]
    assert "[dado de pesquisa retido: input_context/," in fora and "1.5" not in fora
    assert "MODO: PLAN" in fora and "Retorne JSON." in fora
    dentro = gate.prepare_llm([msg], None, remote_raw).messages[0]["content"]
    assert "Amostra: [[1.5, 2.5]]" in dentro and "<<<DADO id=" in dentro


def test_plano_do_pesquisador_contaminado_chega_mascarado_a_destino_sem_dados(gate, third_party):
    from src.egress.fragments import taint_if

    prompt = "Plano atual:\n" + taint_if('{"meta": "acurácia 0.93"}', True) + "\nRevise."
    out = gate.prepare_llm([labeled("user", PromptFragment(prompt, ContentOrigin.INSTRUCAO))], None, third_party)
    assert 'acurácia <num padrão=d.dd>' in out.messages[0]["content"]


def test_erro_da_tentativa_anterior_e_saida_de_execucao(gate, third_party):
    from src.egress.fragments import mark_execution_output

    erro = mark_execution_output("ValueError: could not convert string to float: '12,5'", "t")
    prompt = "Tente de novo.\nErro: " + erro
    out = gate.prepare_llm([labeled("user", PromptFragment(prompt, ContentOrigin.INSTRUCAO))], None, third_party)
    conteudo = out.messages[0]["content"]
    assert "<str len=4 padrão=dd,d>" in conteudo and "12,5" not in conteudo and "origem=saida_execucao" in conteudo


def test_marca_forjada_em_conteudo_observado_nao_afrouxa_o_tratamento(gate, third_party):
    """Uma marca de saída dentro de dado de pesquisa não o reclassifica (continua retido)."""
    forjado = "⟦S:fonte⟧a,b\n1,2⟦/S⟧"
    frag = PromptFragment(forjado, ContentOrigin.DADO_DE_PESQUISA, source="input_context/x.csv")
    out = gate.prepare_llm([labeled("user", frag)], None, third_party).messages[0]["content"]
    assert "[dado de pesquisa retido: input_context/x.csv," in out and "1,2" not in out


def test_json_de_metricas_na_sintese_e_saida_de_execucao(gate, third_party):
    from src.egress.fragments import mark_execution_output

    dados = mark_execution_output('{"metrics": {"max": 12.537}}\nmax: 12.537', "report_data")
    prompt = "Escreva a narrativa.\n" + dados
    out = gate.prepare_llm([labeled("user", PromptFragment(prompt, ContentOrigin.INSTRUCAO))], None, third_party)
    assert "origem=saida_execucao fonte=report_data" in out.messages[0]["content"]
    assert "max: [10, 20)" in out.messages[0]["content"]


def test_evidencia_do_validator_classifica_pela_origem(tmp_path):
    from src.agents.validator_agent import build_artifact_evidence_fragments

    (tmp_path / "metrics.json").write_text('{"acc": 0.9}', encoding="utf-8")
    (tmp_path / "dados.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "relatorio.md").write_text("# ok", encoding="utf-8")
    (tmp_path / "grafico.png").write_bytes(b"png")
    fragments = {f.source: f.origin for f in build_artifact_evidence_fragments(tmp_path, [])}
    assert fragments["artefato:metrics.json"] is ContentOrigin.SAIDA_EXECUCAO
    assert fragments["artefato:dados.csv"] is ContentOrigin.DADO_DE_PESQUISA
    assert fragments["artefato:relatorio.md"] is ContentOrigin.SAIDA_EXECUCAO
    assert fragments["artefatos"] is ContentOrigin.ESQUEMA_AGREGADO  # binário: só nome e tamanho


def test_classificacao_de_caminhos(tmp_path):
    from src.egress.classification import ResearchDataRefused, classify_path, ensure_not_research_data

    assert classify_path("input_context/medicoes.csv") is ContentOrigin.DADO_DE_PESQUISA
    assert classify_path("outputs/s/t/saida.parquet") is ContentOrigin.DADO_DE_PESQUISA
    assert classify_path("input_snapshot/imagem.PNG") is ContentOrigin.DADO_DE_PESQUISA
    assert classify_path("input_context/artigo.pdf") is ContentOrigin.DOCUMENTO
    assert classify_path("/fora/tabela.csv", output_roots=[]) is ContentOrigin.DOCUMENTO
    with pytest.raises(ResearchDataRefused):
        ensure_not_research_data("input_snapshot/x.json")
    ensure_not_research_data("input_snapshot/x.json", compartilhavel=True)


def test_bytes_do_registro_local_sao_gravados_compactados(tmp_path, third_party):
    """`envios.jsonl.gz` recebe o payload exato enviado, com o id da linha do banco."""
    import gzip

    from src.egress.gate import EgressGate
    from src.egress.log import EgressLog

    gate = EgressGate("sessao-gz", log=EgressLog("sessao-gz", tmp_path), min_group_size=10)
    prepared = gate.prepare_llm([labeled("tool", PromptFragment("max: 12.537", ContentOrigin.SAIDA_EXECUCAO))], None,
                                third_party)
    arquivo = tmp_path / "sessao-gz" / "egress" / "envios.jsonl.gz"
    linhas = [json.loads(x) for x in gzip.open(arquivo, "rt", encoding="utf-8").read().splitlines()]
    assert linhas[0]["id"] == prepared.record_id and linhas[0]["canal"] == "llm"
    assert "[10, 20)" in json.dumps(linhas[0]["payload"], ensure_ascii=False)
    assert filters.IV_EXTREMO  # tipos de intervenção exportados
