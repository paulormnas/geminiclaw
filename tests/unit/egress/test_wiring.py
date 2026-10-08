"""Ligação da camada de saída aos pontos de chamada (v18.5-egress-gate, spec data-egress)."""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.egress import filters
from src.egress.fragments import ContentOrigin, PromptFragment, ToolOutput, labeled
from src.egress.gate import GatedProvider, bind_gate_for_tests
from src.llm.agent_loop import run_agent_loop
from src.llm.base import LLMResponse, ToolCall

from .conftest import make_dest

pytestmark = pytest.mark.unit


class FakeInner:
    """Provedor interno que guarda o que recebeu e responde em sequência."""

    model_name = "fake"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def generate(self, messages, tools=None, system=None, temperature=0.7, max_tokens=4096, **kwargs):
        self.calls.append({"messages": messages, "system": system})
        return self.responses.pop(0) if self.responses else LLMResponse(text="ok")

    async def generate_stream(self, messages, system=None):  # pragma: no cover
        yield "x"

    async def health_check(self):  # pragma: no cover
        return True


def _gated(inner, dest, gate):
    bind_gate_for_tests(gate)
    return GatedProvider(inner, dest)


# --- Requisito: ponto único de saída ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chamada_de_compressao_de_contexto(gate, memory_log, third_party, monkeypatch):
    """Cenário "Chamada de compressão de contexto": o resumo passa pelo `EgressGate` e gera linha `canal=llm`."""
    from src import config
    from src.llm.context_compression import compress_messages

    monkeypatch.setattr(config, "CONTEXT_COMPRESSION_MODE", "summarize")
    inner = FakeInner([LLMResponse(text="Resumo: houve 2 execuções.")])
    provider = _gated(inner, third_party, gate)
    historico = [
        labeled("user", PromptFragment("Analise os dados " * 40, ContentOrigin.INSTRUCAO)),
        labeled("tool", PromptFragment("max: 12.537\n" + "linha de log\n" * 80, ContentOrigin.SAIDA_EXECUCAO)),
        labeled("assistant", PromptFragment("a média foi 12.4 " * 20, ContentOrigin.INSTRUCAO, tainted=True)),
        labeled("user", PromptFragment("continue " * 100, ContentOrigin.INSTRUCAO)),
    ]
    out = await compress_messages(historico, max_tokens=300, system="s", provider=provider)

    assert len(memory_log.records) == 1 and memory_log.records[0].canal == "llm"
    enviado = inner.calls[0]["messages"][1]["content"]
    assert "max: [10, 20)" in enviado and "12.537" not in enviado  # saída filtrada para o destino do resumo
    assert "<num padrão=dd.d>" in enviado and "12.4" not in enviado  # texto contaminado mascarado
    assert "<<<DADO id=" in enviado
    resumo = next(m for m in out if "RESUMO DO HISTÓRICO" in m["content"])
    assert resumo["_fragments"][0].tainted is False  # modelo sem dados brutos: resumo não contaminado


@pytest.mark.asyncio
async def test_resumo_de_modelo_com_dados_brutos_e_contaminado(gate, local_node):
    from src import config  # noqa: F401
    from src.llm.context_compression import _summarize_old_context

    inner = FakeInner([LLMResponse(text="A média foi 12.4.")])
    provider = _gated(inner, local_node, gate)
    msgs = [labeled("user", PromptFragment("x " * 400, ContentOrigin.INSTRUCAO)) for _ in range(6)]
    out = await _summarize_old_context(msgs, budget=300, provider=provider)
    assert out[0]["_fragments"][0].tainted is True


@pytest.mark.asyncio
async def test_resultado_do_interpretador_entra_no_historico_como_saida_execucao(gate, memory_log, third_party):
    """Cenário "Resultado do interpretador" pelo laço do agente, com o destino filtrando o histórico."""
    tabela = "     a    b\n0  1.0  2.0\n1  3.0  4.0\n\n[2 rows x 2 columns]"

    def python_interpreter(**kwargs):
        return ToolOutput(f"Resultado de python_interpreter: {tabela}", origin=ContentOrigin.SAIDA_EXECUCAO,
                          source="step_01:stdout", integral_path="outputs/s/t/step_01.stdout.txt")

    inner = FakeInner([
        LLMResponse(text="vou rodar", tool_calls=[ToolCall(id="c1", name="python_interpreter", arguments={})]),
        LLMResponse(text="pronto"),
    ])
    provider = _gated(inner, third_party, gate)
    resposta = await run_agent_loop(prompt="Analise", instruction="Você é o Developer.", tools=[python_interpreter],
                                    provider=provider)

    assert resposta == "pronto"
    assert len(memory_log.records) == 2
    segundo = memory_log.records[1]
    saidas = [f for f in segundo.fragmentos if f["origem"] == "saida_execucao"]
    assert saidas and saidas[0]["bytes"] > 0 and saidas[0]["source"] == "step_01:stdout"
    tool_msg = next(m for m in inner.calls[1]["messages"] if m["role"] == "tool")
    assert "origem=saida_execucao fonte=step_01:stdout>>>" in tool_msg["content"]
    retido = "[saída tabular retida: 2 linhas × 2 colunas; colunas: a, b; integral em outputs/s/t/step_01.stdout.txt]"
    assert retido in tool_msg["content"]
    assert "1.0" not in tool_msg["content"]


@pytest.mark.asyncio
async def test_caminhos_principais_nao_geram_fragmento_sem_origem(gate, memory_log, third_party, tmp_path):
    """Tarefa 7.3: laço do agente (sistema, prompt, resposta, ferramenta, bloco do workspace) sem rótulos faltando."""
    from src.skills.code.manifest import WorkspaceManifest

    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    manifest = WorkspaceManifest(session_dir=session_dir, session_id="sess", task_name="t")
    manifest.record_step(
        step=1, status="failed", artifacts=["resultados.csv"], summary="Execução falhou.",
        error={"error_type": "ValueError", "error_message": "bad '12,5'", "error_location": "step_01.py, linha 3"},
        code_file="step_01.py", task_name="t",
    )
    (session_dir / "step_01.py").write_text("x = float('12,5')\n", encoding="utf-8")

    inner = FakeInner([
        LLMResponse(text="vou rodar", tool_calls=[ToolCall(id="c1", name="memory", arguments={})]),
        LLMResponse(text="pronto"),
    ])
    provider = _gated(inner, third_party, gate)

    def memory(**kwargs):
        return "memória qualquer"

    import os
    os.environ.update({"SESSION_ID": "sess", "TASK_NAME": "t", "OUTPUT_BASE_DIR": str(tmp_path)})
    try:
        await run_agent_loop(prompt="Faça", instruction="Papel", tools=[memory], provider=provider)
    finally:
        for key in ("SESSION_ID", "TASK_NAME", "OUTPUT_BASE_DIR"):
            os.environ.pop(key, None)

    assert memory_log.records
    for row in memory_log.records:
        assert filters.IV_SEM_ORIGEM not in row.intervencoes
        assert all(f["source"] != "sem_rotulo" for f in row.fragmentos)
    # O bloco do workspace trouxe só o NOME do artefato; a mensagem de erro foi filtrada como saída de execução.
    bloco = next(m for m in inner.calls[0]["messages"] if "CONTEXTO DO WORKSPACE" in m["content"])["content"]
    assert "resultados.csv" in bloco and "12,5" not in bloco.split("Código do step anterior")[0]


# --- Requisito: leitura de dados de pesquisa só pela ingestão ---------------------------------------------------

@pytest.mark.asyncio
async def test_ingestao_de_csv_pelo_document_processor(tmp_path):
    """Cenário "Ingestão de CSV pelo document_processor": recusada com a mensagem da regra."""
    from src.skills.document_processor.skill import DocumentProcessorSkill

    class _Skill(DocumentProcessorSkill):  # a skill ainda é abstrata no repositório (sem `run`)
        async def run(self, **kwargs):  # pragma: no cover
            raise NotImplementedError

    skill = _Skill.__new__(_Skill)
    skill.extractor_registry = MagicMock()
    skill.indexer = MagicMock(ingest=AsyncMock())

    result = await skill.execute_async(action="ingest", file_path="input_snapshot/medicoes.csv")

    assert "dados de pesquisa entram só pela ingestão de input_context/" in result["error"]
    skill.extractor_registry.extract.assert_not_called()


def test_resultados_do_document_processor_saem_rotulados_pela_fonte():
    from src.skills.document_processor.skill import _result_content

    dado = _result_content({"content": "a,b\n1,2", "source_path": "input_snapshot/medicoes.csv"})
    documento = _result_content({"content": "texto do artigo", "source_path": "input_snapshot/artigo.pdf"})
    assert dado == "[conteúdo de arquivo de dados omitido: input_snapshot/medicoes.csv]" and "omitido" not in documento


def test_artefato_de_dados_no_bloco_do_workspace(tmp_path):
    """Cenário "Artefato de dados no bloco do workspace": só o nome é injetado, nunca o conteúdo."""
    from src.llm.context_injection import build_workspace_context_fragments
    from src.skills.code.manifest import WorkspaceManifest

    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    WorkspaceManifest(session_dir=session_dir, session_id="sess", task_name="t").record_step(
        step=1, status="success", artifacts=["resultados.csv", "curva_12.537.png"], summary="ok", task_name="t"
    )
    (session_dir / "resultados.csv").write_text("a,b\n9.99,8.88\n", encoding="utf-8")

    fragments = build_workspace_context_fragments(session_dir, "sess", "t")
    texto = "\n".join(f.text for f in fragments)
    assert "resultados.csv" in texto and "9.99" not in texto
    nomes = [f for f in fragments if f.origin is ContentOrigin.ESQUEMA_AGREGADO]
    assert nomes and nomes[0].source == "artefatos"


@pytest.mark.asyncio
async def test_nomes_de_artefatos_com_decimal_sao_mascarados_para_destino_sem_dados(gate, third_party, local_node):
    from src.egress.fragments import ARTIFACT_NAMES_SOURCE
    from src.llm.context_injection import build_workspace_context_fragments  # noqa: F401

    frag = PromptFragment("  - curva_12.537.png\n  - resultados.csv", ContentOrigin.ESQUEMA_AGREGADO,
                          source=ARTIFACT_NAMES_SOURCE)
    fora = gate.prepare_llm([labeled("user", frag)], None, third_party).messages[0]["content"]
    dentro = gate.prepare_llm([labeled("user", frag)], None, local_node).messages[0]["content"]
    assert "curva_<num padrão=dd.ddd>.png" in fora and "resultados.csv" in fora
    assert "curva_12.537.png" in dentro


# --- Skill de código ----------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skill_de_codigo_grava_a_saida_integral_antes_de_devolver(tmp_path, monkeypatch):
    """Tarefa 3.4: `step_NN.stdout.txt`/`.stderr.txt` gravados, e o caminho vai no metadata."""
    from unittest.mock import patch

    from src.skills.code.sandbox import SandboxResult
    from src.skills.code.skill import CodeSkill

    class _Sandbox:
        def __init__(self, *a, **k): ...

        def run(self, **kwargs):
            return SandboxResult(stdout="1.0 2.0\n3.0 4.0\n5.0 6.0", stderr="aviso", exit_code=0, artifacts=[])

    monkeypatch.setenv("OUTPUT_BASE_DIR", str(tmp_path))
    with patch("src.skills.code.skill.PythonSandbox", _Sandbox):
        skill = CodeSkill()
    skill.sandbox = _Sandbox()
    result = await skill.run(code="print(1)", session_id="s", task_name="t")

    stdout_file = tmp_path / "s" / "t" / "step_01.stdout.txt"
    assert stdout_file.read_text(encoding="utf-8") == "1.0 2.0\n3.0 4.0\n5.0 6.0"
    assert (tmp_path / "s" / "t" / "step_01.stderr.txt").read_text(encoding="utf-8") == "aviso"
    assert result.metadata["integral_path"].endswith("s/t/step_01.stdout.txt")
    assert result.metadata["egress_source"] == "step_01:stdout"


def test_ferramenta_devolve_texto_com_a_origem_da_skill():
    from src.skills import registry

    tools = {t.__name__: t for t in registry.as_tools()}
    assert "python_interpreter" in tools and "quick_search" in tools
    skills = {s: registry.get(s) for s in ("python_interpreter", "quick_search", "web_reader", "memory")}
    assert skills["python_interpreter"].egress_origin is ContentOrigin.SAIDA_EXECUCAO
    assert skills["quick_search"].egress_origin is ContentOrigin.DOCUMENTO
    assert skills["web_reader"].egress_origin is ContentOrigin.DOCUMENTO
    assert skills["memory"].egress_origin is ContentOrigin.GRAFO


# --- Requisito: busca e leitura web registradas e restringidas ---------------------------------------------------

@pytest.fixture
def web_dest():
    return make_dest(raw=False, provider="brave")


def _web(dest_provider="brave", canal="busca"):
    from src.egress.gate import Destination

    return Destination(canal=canal, provedor=dest_provider, modelo=None, trust=None, localidade="fora_do_no",
                       aceita_dados_brutos=False, papel="researcher")


def test_consulta_de_papel_contaminado(gate, memory_log):
    """Cenário "Consulta de papel contaminado"."""
    enviada = gate.check_query("calibração sensor 12.537 mV", True, _web())
    assert enviada == "calibração sensor <num padrão=dd.ddd> mV"
    row = memory_log.records[0]
    assert row.canal == "busca" and row.recusado is False and row.intervencoes[filters.IV_NUMERO] == 1


def test_consulta_de_papel_nao_contaminado_vai_como_esta(gate):
    assert gate.check_query("calibração sensor 12 mV", False, _web()) == "calibração sensor 12 mV"


def test_consulta_vazia_de_termos_e_recusada(gate, memory_log):
    from src.egress.gate import EgressRefused

    with pytest.raises(EgressRefused):
        gate.check_query("12.537 34", True, _web())
    assert memory_log.records[0].recusado is True


def test_url_com_dado_embutido(gate, memory_log):
    """Cenário "URL com dado embutido": papel contaminado, URL fora de resultado de busca."""
    from src.egress.gate import EgressRefused

    with pytest.raises(EgressRefused):
        gate.check_url("https://exemplo.org/api?v=12.537", True, _web(canal="leitura_web"))
    row = memory_log.records[0]
    assert row.recusado is True and row.canal == "leitura_web" and "dados brutos" in row.motivo_recusa


def test_url_de_resultado_de_busca_e_url_limpa_sao_lidas(gate, memory_log):
    dest = _web(canal="leitura_web")
    gate.note_search_urls(["https://exemplo.org/api?v=1"])
    assert gate.check_url("https://exemplo.org/api?v=1", True, dest)
    assert gate.check_url("https://exemplo.org/artigo", True, dest)
    assert gate.check_url("https://exemplo.org/api?v=9", False, dest)  # papel não contaminado
    assert [r.recusado for r in memory_log.records] == [False, False, False]


def test_url_com_segmento_numerico_de_papel_contaminado_e_recusada(gate):
    from src.egress.gate import EgressRefused

    with pytest.raises(EgressRefused):
        gate.check_url("https://exemplo.org/medida/12.537", True, _web(canal="leitura_web"))


@pytest.mark.asyncio
async def test_quick_search_mascara_e_registra_a_consulta_do_papel_contaminado(gate, memory_log, monkeypatch):
    from src.skills.search_quick.skill import QuickSearchSkill

    bind_gate_for_tests(gate)
    skill = QuickSearchSkill()
    chamadas = []

    class _Backend:
        async def search(self, query, max_results=5):
            chamadas.append(query)
            return [SimpleNamespace(url="https://exemplo.org/a", title="t", snippet="s")]

    skill.backends = {"ddg": _Backend()}
    skill.strategy = ["ddg"]
    skill.cache = MagicMock(get=MagicMock(return_value=None))
    result = await skill.run(query="calibração 12.537 mV")

    assert result.success and chamadas == ["calibração <num padrão=dd.ddd> mV"]  # sem contexto de agente: contaminado
    assert memory_log.records[0].canal == "busca"


@pytest.mark.asyncio
async def test_quick_search_em_cache_nao_e_egresso(gate, memory_log):
    from src.skills.search_quick.skill import QuickSearchSkill

    bind_gate_for_tests(gate)
    skill = QuickSearchSkill()
    skill.cache = MagicMock(get=MagicMock(return_value=[SimpleNamespace(url="u")]))
    result = await skill.run(query="algo")
    assert result.success and memory_log.records == []


# --- Requisito: visão ---------------------------------------------------------------------------------------------

def test_imagem_de_pesquisa_a_terceiro(gate, memory_log, tmp_path):
    """Cenário "Imagem de pesquisa a terceiro"."""
    from src.egress.gate import Destination, EgressRefused

    imagem = tmp_path / "micro.png"
    imagem.write_bytes(b"png")
    visao = Destination(canal="visao", provedor="google", modelo="g", trust="third_party", localidade="fora_do_no",
                        aceita_dados_brutos=False, papel="ingestao")
    with pytest.raises(EgressRefused):
        gate.authorize_vision(imagem, False, visao)
    assert memory_log.records[0].recusado is True and memory_log.records[0].canal == "visao"

    gate.authorize_vision(imagem, True, visao)  # compartilhável: liberada
    assert memory_log.records[1].recusado is False
    assert memory_log.records[1].intervencoes[filters.IV_COMPARTILHAVEL] == 1
    com_dados = Destination(canal="visao", provedor="ollama", modelo="v", trust="self_hosted", localidade="no_no",
                            aceita_dados_brutos=True, papel="ingestao")
    gate.authorize_vision(imagem, False, com_dados)  # destino com dados brutos: liberada


# --- Tarefa 7.2: nenhum ponto de chamada a modelo fora da camada ---------------------------------------------------

_ROOT = Path(__file__).resolve().parents[3]
_PROVIDER_CALL = re.compile(r"\.generate\(|\.generate_content\(|generate_stream\(")
# Onde a chamada é o próprio provedor ou a camada: provedores, GatedProvider, contrato abstrato e health check.
_ALLOWED_CALL_FILES = {
    "src/llm/providers", "src/egress/gate.py", "src/llm/base.py",
}


def _py_files(*roots):
    for root in roots:
        for path in (_ROOT / root).rglob("*.py"):
            yield path


def test_nenhum_ponto_de_chamada_envia_sem_gated_provider():
    """Toda chamada `generate(` fora dos provedores usa um provedor obtido do roteador (sempre `GatedProvider`),
    e só o roteador e o health check criam provedores diretamente."""
    ofensores = []
    criadores = []
    for path in _py_files("src", "agents"):
        rel = path.relative_to(_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if any(rel.startswith(allowed) for allowed in _ALLOWED_CALL_FILES):
            continue
        # `genai.Client` / `generate_content` só nos provedores, exceto a visão (autorizada por `authorize_vision`).
        if "generate_content(" in text and rel != "src/context_loader.py":
            ofensores.append(rel)
        if rel == "src/context_loader.py":
            assert "authorize_vision" in text
        if re.search(r"\bcreate_provider\(", text) and rel not in {
            "src/model_router.py", "src/llm/availability.py", "src/llm/registry.py",
        }:
            criadores.append(rel)
    assert not ofensores, f"chamada direta a generate_content fora da camada: {ofensores}"
    assert not criadores, f"provedores criados fora do roteador: {criadores}"


def test_roteador_devolve_sempre_provedor_envolvido():
    from src.model_router import ModelRouter

    ModelRouter.clear_cache()
    for role in ("researcher", "developer", "validator", "reviewer", "summarizer", "base", "planner"):
        assert isinstance(ModelRouter.get_provider(role), GatedProvider), role
    from src.llm.factory import get_provider

    assert isinstance(get_provider(), GatedProvider)
    ModelRouter.clear_cache()


def test_destino_do_provedor_vem_do_catalogo():
    from src.model_router import ModelRouter

    ModelRouter.clear_cache()
    dest = ModelRouter.get_provider("developer").dest
    assert dest.canal == "llm" and dest.papel == "developer"
    assert dest.localidade in ("no_no", "fora_do_no") and isinstance(dest.aceita_dados_brutos, bool)
    ModelRouter.clear_cache()


def test_provedor_envolvido_repassa_atributos_do_interno():
    inner = FakeInner([])
    inner.fetch_digest = lambda: "sha"
    provider = GatedProvider(inner, make_dest(raw=False))
    assert provider.fetch_digest() == "sha" and provider.model_name == "fake"
    assert provider.tainted_output is False


@pytest.mark.asyncio
async def test_resposta_do_provedor_envolvido_e_rotulada(gate, third_party, local_node):
    provider = _gated(FakeInner([LLMResponse(text="12.4", tool_calls=[ToolCall(id="1", name="t", arguments={})])]),
                      local_node, gate)
    response = await provider.generate(messages=[labeled("user", PromptFragment("oi", ContentOrigin.INSTRUCAO))])
    assert response.tainted is True and response.produced_by == "developer"
    message = response.to_message()
    assert message["_fragments"][0].tainted is True and message["_tool_calls_tainted"] is True
    sem_gate = LLMResponse(text="x").to_message()
    assert "_fragments" not in sem_gate


def test_a_sessao_nao_inicia_sem_locality_min_group_size(monkeypatch):
    from src import config

    monkeypatch.setattr(config, "LOCALITY_MIN_GROUP_SIZE", None)
    with pytest.raises(RuntimeError, match="LOCALITY_MIN_GROUP_SIZE"):
        config.require_locality_min_group_size()


@pytest.mark.asyncio
async def test_falha_no_registro_impede_o_envio_ao_provedor(gate, memory_log, third_party):
    """Cenário "Falha no registro" pelo provedor envolvido: o provedor interno nunca é chamado."""
    from src.egress.log import EgressLogError

    inner = FakeInner([LLMResponse(text="não deveria chegar")])
    provider = _gated(inner, third_party, gate)
    memory_log.fail = True
    with pytest.raises(EgressLogError):
        await provider.generate(messages=[labeled("user", PromptFragment("oi", ContentOrigin.INSTRUCAO))])
    assert inner.calls == []
