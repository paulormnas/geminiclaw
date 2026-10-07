"""Testes de apoio do Curator (v17-curator-agent): schema, ``update_edge``, sinalizações, ingestão e papel opcional."""

from __future__ import annotations

import json
import os

import pytest

from agents.base.tools import flag_for_curator
from src import config
from src.agent_runtime.context import AgentContext, bind_agent_context, current_context
from src.knowledge import schema
from src.knowledge.curator_flags import FLAGS_FILENAME, FlagError, FlagStore, record_flag
from src.knowledge.errors import GraphStoreError, UnknownPropertyError
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.ingestion import SessionContext, ingest_session_start
from src.knowledge.semantic_index import IGNORED_STATUSES
from src.llm.catalog import OPTIONAL_ROLES, REQUIRED_ROLES
from src.llm.routing import NoEligibleModelError, resolve_session
from tests.support import catalog_fixtures as cf
from tests.support.curator_graph import ORQ, CuratorGraph

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- schema (aprovado em 2026-10-06)


def test_schema_ganha_abordagem_status_filtro_condicoes_e_fundida_em():
    """Task 1.1 — Abordagem.status (ativa|fundida), Descoberta.filtro_condicoes e a relação FUNDIDA_EM."""
    assert schema.NODE_SCHEMAS["Abordagem"].properties["status"].enum == ("ativa", "fundida")
    assert not schema.NODE_SCHEMAS["Abordagem"].properties["status"].required  # nós existentes continuam válidos
    assert "filtro_condicoes" in schema.NODE_SCHEMAS["Descoberta"].properties
    assert schema.find_relation_schema("Abordagem", "FUNDIDA_EM", "Abordagem") is not None
    assert "FUNDIDA_EM" in schema.RELATION_TYPES
    assert "fundida" in IGNORED_STATUSES  # abordagem fundida sai das buscas e dos candidatos de similaridade


def test_update_edge_so_altera_propriedades_da_relacao():
    """``update_edge`` atualiza ``peso`` e recusa propriedades de proveniência ou desconhecidas."""
    store = InMemoryGraphStore()
    g = CuratorGraph(store).setup_project()
    hip = g.hipotese()
    _, res = g.tentativa(hip, g.abordagem())
    store.create_edge(res, "SUSTENTA", hip, {"peso": 0.5}, actor=ORQ)

    store.update_edge(res, "SUSTENTA", hip, {"peso": 0.9}, actor=ORQ)

    edge = next(e for e in store._edges if e.rel_type == "SUSTENTA")  # noqa: SLF001
    assert edge.properties["peso"] == 0.9 and edge.properties["criado_por"] == "orquestrador"
    for proibido in ({"criado_por": "x"}, {"status": "contestada"}, {"inexistente": 1}):
        with pytest.raises(UnknownPropertyError):
            store.update_edge(res, "SUSTENTA", hip, proibido, actor=ORQ)
    with pytest.raises(GraphStoreError):
        store.update_edge(res, "REFUTA", hip, {"peso": 1}, actor=ORQ)


def test_ingestao_segue_fundida_em_para_a_canonica():
    """Scenario: Fusão — o nome da duplicada passa a resolver para a canônica na ingestão (sem apagar a duplicada)."""
    store = InMemoryGraphStore()
    g = CuratorGraph(store, "11111111-1111-4111-8111-111111111111").setup_project()
    canonica, duplicada = g.abordagem("ResNet-18"), g.abordagem("resnet18")
    store.update_node(duplicada, {"status": "fundida"}, actor=ORQ)
    store.create_edge(duplicada, "FUNDIDA_EM", canonica, {}, actor=ORQ)
    ctx = SessionContext(project_id=g.projeto_id, session_id="s9", modo="auto", inicio="2026-10-06T10:00:00+00:00",
                         no_execucao="n")
    ingest_session_start(store, ctx)

    from src.knowledge.ingestion import _Writer

    writer = _Writer(store, ctx)

    assert writer.abordagem({"nome": "resnet18", "tipo": "arquitetura"}, "t") == canonica
    assert writer.abordagem({"nome": "ResNet-18"}, "t") == canonica
    assert store.get_node(duplicada) is not None


# --------------------------------------------------------------------------- sinalizações (flag_for_curator)


@pytest.fixture
def bound(tmp_path):
    token = current_context.set(None)
    ctx = AgentContext(
        session_id="s1", agent_session_id="a1", agent_id="developer", mode="auto", output_dir=tmp_path / "s1",
        model="m", task_name="treino", execution_id="s1",
    )
    bind_agent_context(ctx)
    yield tmp_path / "s1"
    current_context.reset(token)


@pytest.mark.asyncio
async def test_flag_for_curator_grava_jsonl_com_agente_subtarefa_e_horario(bound):
    """Task 4.1 — flag_for_curator grava em curator_flags.jsonl (agente, subtarefa, horário); sem mudança de schema."""
    saida = await flag_for_curator(tipo="falha_relevante", texto="OOM com lote 64", refs=["node-1", "metrics.json"])

    assert "registrada" in saida
    linha = json.loads((bound / FLAGS_FILENAME).read_text().splitlines()[0])
    assert linha["agente"] == "developer" and linha["subtarefa"] == "treino" and linha["criado_em"]
    assert linha["tipo"] == "falha_relevante" and linha["refs"] == ["node-1", "metrics.json"]
    (pendente,) = FlagStore(bound).pending()
    assert pendente.id == linha["id"]


@pytest.mark.asyncio
async def test_flag_for_curator_valida_tipo_tamanho_e_limite(bound, monkeypatch):
    """Segurança — tipo inválido, texto longo, refs demais e o limite por sessão são recusados com mensagem
    acionável."""
    assert "Erro" in await flag_for_curator(tipo="qualquer", texto="x")
    assert "Erro" in await flag_for_curator(tipo="oportunidade", texto="x" * 5000)
    assert "Erro" in await flag_for_curator(tipo="oportunidade", texto="ok", refs=["r"] * 50)
    monkeypatch.setattr(config, "CURATOR_MAX_FLAGS_PER_SESSION", 2)
    assert "registrada" in await flag_for_curator(tipo="oportunidade", texto="a")
    assert "registrada" in await flag_for_curator(tipo="oportunidade", texto="b")
    assert "limite" in await flag_for_curator(tipo="oportunidade", texto="c")


@pytest.mark.asyncio
async def test_flag_for_curator_fora_de_um_agente_recusa():
    """Sem AgentContext a ferramenta recusa em vez de gravar em um diretório arbitrário."""
    token = current_context.set(None)
    try:
        assert "Erro" in await flag_for_curator(tipo="oportunidade", texto="a")
    finally:
        current_context.reset(token)


def test_flag_nao_segue_link_simbolico_e_limpa_controles(tmp_path):
    """Segurança — O_NOFOLLOW: o arquivo de sinalizações não é escrito através de um link simbólico; texto sem
    controles."""
    alvo = tmp_path / "alvo.txt"
    alvo.write_text("intacto")
    pasta = tmp_path / "sess"
    pasta.mkdir()
    os.symlink(alvo, pasta / FLAGS_FILENAME)

    with pytest.raises(OSError):
        record_flag(pasta, agente="a", subtarefa="s", tipo="oportunidade", texto="x")
    assert alvo.read_text() == "intacto"

    limpa = tmp_path / "limpa"
    record_flag(limpa, agente="a", subtarefa="s", tipo="oportunidade", texto="linha1\nlinha2\x00 fim")
    assert FlagStore(limpa).pending()[0].texto == "linha1 linha2 fim"


def test_decisao_de_sinalizacao_exige_motivo_e_no_id(tmp_path):
    """Spec: o Curator marca cada sinalização como registrada (com ID) ou descartada (com motivo)."""
    fid = record_flag(tmp_path, agente="a", subtarefa="s", tipo="oportunidade", texto="x")
    store = FlagStore(tmp_path)

    with pytest.raises(FlagError):
        store.resolve(fid, "descartada", "")
    with pytest.raises(FlagError):
        store.resolve(fid, "registrada", "m")
    with pytest.raises(FlagError):
        store.resolve("inexistente", "descartada", "m")
    store.resolve(fid, "descartada", "sem evidência")

    assert store.pending() == [] and store.counts()["descartada"] == 1


# --------------------------------------------------------------------------- papel opcional no roteador


def test_curator_sem_modelo_elegivel_nao_impede_a_sessao(tmp_path):
    """Falha do Curator nunca derruba a sessão — sem modelo elegível o papel é omitido e os demais resolvem."""
    doc = cf.base_document()
    doc["papeis"]["curator"]["preferencia"] = ["anthropic/claude-sonnet-5-5"]  # nuvem: descartado em self_hosted_only
    catalog = cf.load(tmp_path, doc)
    disponiveis = {m: cf.Availability(True) for m in catalog.modelos}

    mapa = resolve_session(catalog, disponiveis, "self_hosted_only")

    assert "curator" not in mapa and {"researcher", "developer", "base"} <= set(mapa)
    assert OPTIONAL_ROLES == ("curator",) and "curator" not in REQUIRED_ROLES


def test_papel_obrigatorio_sem_modelo_continua_derrubando_a_sessao(tmp_path):
    """Só o Curator é opcional: um papel obrigatório sem modelo elegível segue sendo erro acionável."""
    doc = cf.base_document()
    doc["papeis"]["developer"]["preferencia"] = ["anthropic/claude-sonnet-5-5"]
    catalog = cf.load(tmp_path, doc)
    disponiveis = {m: cf.Availability(True) for m in catalog.modelos}

    with pytest.raises(NoEligibleModelError):
        resolve_session(catalog, disponiveis, "self_hosted_only")


def test_session_routing_expoe_o_curator_com_o_catalogo_versionado():
    """Task 5.2 — o catálogo versionado define o papel ``curator`` (Ollama local) e o payload da sessão o lista."""
    from src.llm.session import build_offline_routing

    routing = build_offline_routing()

    assert routing.resolution("curator").id.startswith("ollama/")
    assert "curator" in routing.payload()["papeis"]


def test_pin_invalido_do_curator_em_strict_nao_derruba_a_sessao(tmp_path):
    """Sugestão do PR #106 — PinError do papel opcional ``curator`` o desliga em vez de derrubar a sessão."""
    from src.llm.routing import Pin, PinError

    doc = cf.base_document()
    catalog = cf.load(tmp_path, doc)
    disponiveis = {m: cf.Availability(True) for m in catalog.modelos}

    mapa = resolve_session(catalog, disponiveis, "third_party_allowed", {"curator": Pin("google/inexistente")}, "strict")

    assert "curator" not in mapa and "researcher" in mapa
    with pytest.raises(PinError):
        resolve_session(catalog, disponiveis, "third_party_allowed", {"developer": Pin("google/inexistente")}, "strict")
