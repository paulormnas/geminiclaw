"""Cenários de versão efetiva por chamada e de troca de versão na sessão (v18.5-model-catalog-locality)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from src.autonomous_loop import AutonomousLoop
from src.llm.allocation import (
    build_allocation_profile,
    current_allocation,
    record_call_version,
    refresh_ollama_versions,
    seed_ollama_versions,
)
from src.llm.availability import Availability
from src.llm.base import LLMResponse
from src.llm.providers import ollama as ollama_module
from src.llm.providers.ollama import OllamaProvider
from src.llm.providers.openai_compatible import OpenAICompatibleProvider
from src.llm.routing import resolve_session
from src.llm.session import SessionRouting, bind_session_routing
from src.llm.versions import UNKNOWN_VERSION, VersionTracker, normalize_version
from src.usage import StopReason, UsageBudget, UsageTracker
from tests.support.catalog_fixtures import all_available, base_document, load

pytestmark = pytest.mark.unit

QWEN = "ollama/qwen3:8b"
CLAUDE = "anthropic/claude-sonnet-5-5"
OLLAMA_URL = "http://localhost:11434"


@pytest.fixture(autouse=True)
def unbind_session_routing():
    """O mapa vinculado ao contexto não pode vazar para outros testes."""
    from src.llm import session

    yield
    session._current.set(None)


@pytest.fixture(autouse=True)
def clean_digests():
    ollama_module.clear_known_digests()
    yield
    ollama_module.clear_known_digests()


def _routing(tmp_path, *, strict: bool = False, doc: dict | None = None) -> SessionRouting:
    catalog = load(tmp_path, doc)
    resolved = resolve_session(catalog, all_available(catalog), "third_party_allowed")
    return SessionRouting(
        "third_party_allowed", "strict" if strict else "flexible", catalog, resolved,
        {i: Availability(True) for i in catalog.modelos}, VersionTracker(strict=strict),
    )


# --- provedores -------------------------------------------------------------------------------------------------


def _google_response(model_version):
    part = SimpleNamespace(thought=False, function_call=None, text="oi", thought_signature=None)
    response = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]), finish_reason="STOP")],
        usage_metadata=SimpleNamespace(
            prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0, total_token_count=2
        ),
    )
    if model_version is not False:
        response.model_version = model_version
    return response


@pytest.mark.asyncio
async def test_google_informa_a_versao():
    """Cenário: Google informa a versão."""
    from src.llm.providers.google import GoogleProvider

    with patch("src.llm.providers.google.genai.Client") as client_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=_google_response("gemini-2.5-pro-002"))
        client_cls.return_value = client
        provider = GoogleProvider(api_key="chave-de-teste", model="gemini-3.8-flash")

    response = await provider.generate([{"role": "user", "content": "oi"}])

    assert response.versao_efetiva == "gemini-2.5-pro-002"


@pytest.mark.asyncio
async def test_google_sem_model_version_e_desconhecida():
    from src.llm.providers.google import GoogleProvider

    with patch("src.llm.providers.google.genai.Client") as client_cls:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(return_value=_google_response(False))
        client_cls.return_value = client
        provider = GoogleProvider(api_key="chave-de-teste", model="gemini-3.8-flash")

    assert (await provider.generate([{"role": "user", "content": "oi"}])).versao_efetiva == UNKNOWN_VERSION


async def _compatible_call(payload: dict) -> LLMResponse:
    provider = OpenAICompatibleProvider(base_url="http://test-server:8000/v1", model="llama", api_key="k")
    async with respx.mock:
        respx.post("http://test-server:8000/v1/chat/completions").mock(return_value=httpx.Response(200, json=payload))
        return await provider.generate(messages=[{"role": "user", "content": "Oi"}])


_CHOICES = [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]


@pytest.mark.asyncio
async def test_servidor_compativel_sem_campo_de_modelo():
    """Cenário: Servidor compatível sem campo de modelo."""
    response = await _compatible_call({"choices": _CHOICES})

    assert response.versao_efetiva == "desconhecida"


@pytest.mark.asyncio
async def test_servidor_compativel_com_modelo_e_fingerprint():
    with_both = await _compatible_call({"choices": _CHOICES, "model": "llama-3.3", "system_fingerprint": "fp_1"})
    only_model = await _compatible_call({"choices": _CHOICES, "model": "llama-3.3"})
    bad_type = await _compatible_call({"choices": _CHOICES, "model": 7, "system_fingerprint": "fp_1"})

    assert with_both.versao_efetiva == "llama-3.3@fp_1"
    assert only_model.versao_efetiva == "llama-3.3"
    assert bad_type.versao_efetiva == "desconhecida"


@pytest.mark.asyncio
async def test_ollama_pelo_digest():
    """Cenário: Ollama pelo digest (lido de /api/tags no início da sessão; a resposta usa o último conhecido)."""
    provider = OllamaProvider(OLLAMA_URL, "qwen3:8b")
    tags = {"models": [{"name": "outro:1b", "digest": "sha256:zzz"}, {"name": "qwen3:8b", "digest": "sha256:abc123"}]}
    chat = {"message": {"role": "assistant", "content": "oi"}, "done": True, "eval_count": 1}

    async with respx.mock:
        respx.get(f"{OLLAMA_URL}/api/tags").mock(return_value=httpx.Response(200, json=tags))
        respx.post(f"{OLLAMA_URL}/api/chat").mock(return_value=httpx.Response(200, json=chat))
        assert await provider.fetch_digest() == "sha256:abc123"
        response = await provider.generate(messages=[{"role": "user", "content": "Oi"}])

    assert response.versao_efetiva == "sha256:abc123"


@pytest.mark.asyncio
async def test_ollama_sem_digest_conhecido_ou_modelo_ausente():
    provider = OllamaProvider(OLLAMA_URL, "qwen3:8b")
    chat = {"message": {"role": "assistant", "content": "oi"}, "done": True, "eval_count": 1}

    async with respx.mock:
        respx.post(f"{OLLAMA_URL}/api/chat").mock(return_value=httpx.Response(200, json=chat))
        sem_leitura = await provider.generate(messages=[{"role": "user", "content": "Oi"}])
        respx.get(f"{OLLAMA_URL}/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
        ausente = await provider.fetch_digest()
        respx.get(f"{OLLAMA_URL}/api/tags").mock(
            return_value=httpx.Response(200, json={"models": [{"name": "qwen3:8b", "digest": ""}]})
        )
        vazio = await provider.fetch_digest()

    assert sem_leitura.versao_efetiva == ausente == vazio == "desconhecida"


def test_normalize_version():
    assert normalize_version("  v1\n") == "v1"
    assert normalize_version("") == normalize_version(None) == normalize_version(3) == UNKNOWN_VERSION


# --- registro por chamada ---------------------------------------------------------------------------------------


def test_chamada_registra_a_versao_em_token_usage():
    """Cenário: Google informa a versão (a versão chega à telemetria de ``token_usage``)."""
    from src.llm.metering import record_llm_call

    telemetry = MagicMock()
    class GoogleProvider:
        model_name = "gemini-2.5-pro"

    provider = GoogleProvider()
    response = LLMResponse(
        text="x", usage={"prompt_tokens": 1, "completion_tokens": 1}, versao_efetiva="gemini-2.5-pro-002"
    )

    with patch("src.llm.metering.get_telemetry", return_value=telemetry):
        record_llm_call(provider, response, 5, "validator")

    assert telemetry.record_token_usage.call_args.kwargs["versao_efetiva"] == "gemini-2.5-pro-002"


def test_telemetria_guarda_a_versao_na_linha():
    from src.telemetry import TelemetryCollector

    collector = TelemetryCollector()
    with patch.object(collector, "_maybe_flush_sync"):
        collector.record_token_usage("e", "s", "a", "google", "m", 1, 1, 5, versao_efetiva="v-1")
        collector.record_token_usage("e", "s", "a", "google", "m", 1, 1, 5)

    assert [r.versao_efetiva for r in collector._buffer.token_usage] == ["v-1", "desconhecida"]


# --- troca de versão --------------------------------------------------------------------------------------------


def test_troca_de_versao_em_modo_flexivel(tmp_path, caplog):
    """Cenário: Troca de versão em modo flexível (evento e aviso; a sessão continua)."""
    routing = _routing(tmp_path)
    events = []
    routing.versions.set_event_sink(events.append)
    bind_session_routing(routing)

    with caplog.at_level("WARNING", logger="src.llm.versions"):
        record_call_version("anthropic", "claude-sonnet-5-5", "v1")
        record_call_version("anthropic", "claude-sonnet-5-5", "v2")

    assert len(events) == 1
    assert events[0]["tipo"] == "versao_modelo_alterada"
    assert events[0]["anterior"] == "v1" and events[0]["nova"] == "v2"
    assert events[0]["provedor_modelo"] == CLAUDE
    assert "developer" in events[0]["papeis"]
    assert routing.versions.parada_pendente is None
    assert any("mudou" in r.getMessage() for r in caplog.records)
    assert routing.versions.eventos == events


def test_versao_estavel_nao_gera_evento_e_desconhecida_para_conhecida_tambem_nao(tmp_path):
    routing = _routing(tmp_path)
    bind_session_routing(routing)

    record_call_version("anthropic", "claude-sonnet-5-5", UNKNOWN_VERSION)
    record_call_version("anthropic", "claude-sonnet-5-5", "v1")
    record_call_version("anthropic", "claude-sonnet-5-5", "v1")

    assert routing.versions.eventos == []


def test_versao_conhecida_que_vira_desconhecida_e_troca(tmp_path):
    routing = _routing(tmp_path)
    bind_session_routing(routing)

    record_call_version("anthropic", "claude-sonnet-5-5", "v1")
    record_call_version("anthropic", "claude-sonnet-5-5", UNKNOWN_VERSION)

    assert [e["nova"] for e in routing.versions.eventos] == [UNKNOWN_VERSION]


def _closing_loop():
    orchestrator = MagicMock()
    orchestrator._run_planning_loop = AsyncMock(return_value=[])
    orchestrator._execute_agent = AsyncMock()
    orchestrator.output_manager = MagicMock()
    orchestrator.output_manager.list_artifacts.return_value = []
    orchestrator.session_manager = MagicMock()
    orchestrator.session_manager.get.return_value = None
    loop = AutonomousLoop(orchestrator)
    budget = UsageBudget(
        max_tokens=500_000, max_minutes=120, max_task_retries=3, max_connection_retries=20, closing_reserve_pct=0.05
    )
    loop._usage_tracker = UsageTracker(
        budget, execution_id="exec_versao",
        token_reader=lambda: 0, connection_retry_reader=lambda: 0, clock=lambda: 0.0,
        pending_stop=AutonomousLoop._pending_model_stop,
    )
    return orchestrator, loop


async def _run_closing(loop):
    with patch("src.autonomous_loop.get_telemetry", return_value=MagicMock()), \
         patch.object(AutonomousLoop, "_is_complex_triage", AsyncMock(return_value=True)):
        return await loop._run_complex_path("tarefa", "exec_versao")


@pytest.mark.asyncio
async def test_troca_de_versao_em_modo_strict(tmp_path):
    """Cenário: Troca de versão em modo strict (nada é despachado; fechamento com versao_modelo)."""
    routing = _routing(tmp_path, strict=True)
    bind_session_routing(routing)
    record_call_version("anthropic", "claude-sonnet-5-5", "v1")
    record_call_version("anthropic", "claude-sonnet-5-5", "v2")
    orchestrator, loop = _closing_loop()

    await _run_closing(loop)

    orchestrator._run_planning_loop.assert_not_called()
    orchestrator._execute_agent.assert_not_called()
    payload = orchestrator.session_manager.update.call_args.kwargs["payload"]
    assert payload["motivo_parada"] == StopReason.MODEL_VERSION.value == "versao_modelo"


@pytest.mark.asyncio
async def test_versao_desconhecida_em_modo_strict(tmp_path):
    """Cenário: Versão desconhecida em modo strict."""
    routing = _routing(tmp_path, strict=True)
    bind_session_routing(routing)
    record_call_version("anthropic", "claude-sonnet-5-5", UNKNOWN_VERSION)
    orchestrator, loop = _closing_loop()

    await _run_closing(loop)

    payload = orchestrator.session_manager.update.call_args.kwargs["payload"]
    assert payload["motivo_parada"] == "versao_modelo"


@pytest.mark.asyncio
async def test_modo_flexivel_nao_fecha_por_versao(tmp_path):
    routing = _routing(tmp_path)
    bind_session_routing(routing)
    record_call_version("anthropic", "claude-sonnet-5-5", UNKNOWN_VERSION)

    assert AutonomousLoop._pending_model_stop() is None


@pytest.mark.asyncio
async def test_versao_modelo_e_motivo_retomavel_e_valido_no_grafo():
    from src.continuity import MOTIVOS_RETOMAVEIS
    from src.knowledge.ingestion import MOTIVOS_PARADA

    assert "versao_modelo" in MOTIVOS_RETOMAVEIS
    assert "versao_modelo" in MOTIVOS_PARADA


# --- digest do Ollama no início e a cada checkpoint -------------------------------------------------------------


def _ollama_routing(tmp_path) -> SessionRouting:
    doc = base_document()
    for role in doc["papeis"].values():
        role["preferencia"] = [QWEN]
    return _routing(tmp_path, doc=doc)


class _TagsFactory:
    """Dublê do provedor para a leitura de digest, sem rede."""

    def __init__(self, digests: list[str]):
        self.digests = digests

    def __call__(self, provider, model):
        outer = self

        class _P:
            async def fetch_digest(self):
                return outer.digests.pop(0)

        return _P()


@pytest.mark.asyncio
async def test_digest_do_ollama_no_inicio_e_a_cada_checkpoint(tmp_path):
    routing = _ollama_routing(tmp_path)
    factory = _TagsFactory(["sha256:a", "sha256:a", "sha256:b"])

    await seed_ollama_versions(routing, factory)
    assert routing.versions.current(QWEN) == "sha256:a"
    assert current_allocation_from(routing).versao_efetiva == "sha256:a"

    assert await refresh_ollama_versions(routing, factory) == []
    events = await refresh_ollama_versions(routing, factory)

    assert [e["nova"] for e in events] == ["sha256:b"]
    assert routing.versions.current(QWEN) == "sha256:b"


def current_allocation_from(routing):
    from src.llm.allocation import allocation_for

    return allocation_for(routing, "validator")


# --- liga o rastreador à sessão (telemetria e payload) ----------------------------------------------------------


def test_orquestrador_grava_evento_e_atualiza_o_perfil(tmp_path):
    from src.orchestrator import Orchestrator

    routing = _routing(tmp_path)
    store = {"payload": {"allocation_profile": build_allocation_profile(routing), "eventos_versao_modelo": []}}
    session_manager = MagicMock()
    session_manager.get.side_effect = lambda _id: SimpleNamespace(payload=store["payload"])
    session_manager.update.side_effect = lambda _id, payload: store.update(payload=payload)
    orchestrator = Orchestrator(session_manager=session_manager, agent_runtime=MagicMock())
    telemetry = MagicMock()
    bind_session_routing(routing)

    with patch("src.orchestrator.get_telemetry", return_value=telemetry):
        orchestrator._wire_version_events(routing, "sess1")
        record_call_version("anthropic", "claude-sonnet-5-5", "v1")
        record_call_version("anthropic", "claude-sonnet-5-5", "v2")

    papeis = store["payload"]["allocation_profile"]["papeis"]
    assert papeis["developer"]["versao_efetiva"] == "v2"
    assert [e["nova"] for e in store["payload"]["eventos_versao_modelo"]] == ["v2"]
    kwargs = telemetry.record_agent_event.call_args.kwargs
    assert kwargs["event_type"] == "versao_modelo_alterada"
    json.dumps(store["payload"])


def test_perfil_e_alocacao_atual_sem_segredos(tmp_path):
    routing = _routing(tmp_path)
    bind_session_routing(routing)

    allocation = current_allocation("researcher")

    assert allocation.provedor == "anthropic"
    assert allocation.trust == "third_party"
    assert allocation.localidade == "fora_do_no"
    assert allocation.aceita_dados_brutos is False
    assert allocation.familia_modelo == "anthropic"
    assert allocation.versao_efetiva == UNKNOWN_VERSION


# --- M1: falha transitória em /api/tags não é troca de versão ---------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_digest_em_falha_devolve_none_e_preserva_o_digest_conhecido():
    ollama_module.clear_known_digests()
    provider = OllamaProvider(OLLAMA_URL, "qwen3:8b")
    tags = {"models": [{"name": "qwen3:8b", "digest": "sha256:abc123"}]}

    async with respx.mock:
        respx.get(f"{OLLAMA_URL}/api/tags").mock(return_value=httpx.Response(200, json=tags))
        assert await provider.fetch_digest() == "sha256:abc123"
        respx.get(f"{OLLAMA_URL}/api/tags").mock(return_value=httpx.Response(503))
        assert await provider.fetch_digest() is None

    assert ollama_module._known_digests[(provider._base_url, "qwen3:8b")] == "sha256:abc123"


@pytest.mark.asyncio
async def test_refresh_com_falha_nao_gera_evento_nem_parada_em_strict(tmp_path):
    routing = _ollama_routing(tmp_path)
    routing.versions.strict = True
    factory = _TagsFactory(["sha256:a", None, "sha256:a"])

    await seed_ollama_versions(routing, factory)
    assert await refresh_ollama_versions(routing, factory) == []  # falha transitória
    assert await refresh_ollama_versions(routing, factory) == []

    assert routing.versions.current(QWEN) == "sha256:a"
    assert routing.versions.parada_pendente is None
    assert routing.versions.eventos == []


@pytest.mark.asyncio
async def test_seed_com_falha_grava_desconhecida(tmp_path):
    routing = _ollama_routing(tmp_path)

    await seed_ollama_versions(routing, _TagsFactory([None]))

    assert routing.versions.current(QWEN) == UNKNOWN_VERSION
