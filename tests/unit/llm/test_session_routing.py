"""Cenários de resolução única por sessão, payload, banner, 429 e dica despachada (v16-model-catalog-router)."""

import hashlib
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.session import (
    SessionRouting,
    bind_session_routing,
    build_offline_routing,
    build_session_routing,
    get_catalog,
)
from src.model_router import ModelRouter

pytestmark = pytest.mark.unit

CHAVE_GEMINI = "AIza-chave-do-gemini-nao-pode-vazar"
CHAVE_CLAUDE = "sk-ant-chave-do-claude-nao-pode-vazar"


@pytest.fixture(autouse=True)
def clean_router_cache():
    ModelRouter.clear_cache()
    yield
    ModelRouter.clear_cache()


@pytest.fixture
def nuvem(monkeypatch):
    monkeypatch.setattr("src.config.LLM_DATA_POLICY", "third_party_allowed")
    monkeypatch.setattr("src.config.GEMINI_API_KEY", CHAVE_GEMINI)
    monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", CHAVE_CLAUDE)


@pytest.mark.asyncio
async def test_mapa_no_payload(nuvem):
    """Cenário: Mapa no payload (uma entrada por papel e o hash do catálogo efetivo)."""
    routing = await build_session_routing()
    payload = routing.payload()

    assert set(payload["papeis"]) == {"researcher", "developer", "reviewer", "summarizer", "validator", "base"}
    for entry in payload["papeis"].values():
        assert set(entry) == {"id", "trust", "origem"}
    catalog_file = Path("src/llm/catalog.yaml")
    assert payload["catalogo"]["hash"] == hashlib.sha256(catalog_file.read_bytes()).hexdigest()
    assert payload["catalogo"]["versao"] == get_catalog().versao
    assert payload["politica"] == "third_party_allowed"
    assert payload["routing"] == "flexible"
    json.dumps(payload)  # serializável no JSONB


@pytest.mark.asyncio
async def test_handle_request_grava_llm_routing_no_payload_da_sessao(nuvem):
    """Cenário: Mapa no payload, gravado pelo orquestrador ao iniciar a sessão."""
    from src.orchestrator import AgentTask, Orchestrator
    from src.session import Session

    session_manager = MagicMock()
    session_manager.create.return_value = Session(
        id="sess_master", agent_id="orchestrator", status="active", created_at="", updated_at="", payload={}
    )
    runtime = MagicMock()
    runtime.run = AsyncMock(side_effect=RuntimeError("não deve chegar aqui"))
    orchestrator = Orchestrator(session_manager=session_manager, agent_runtime=runtime)

    with patch.object(orchestrator, "_execute_agent", AsyncMock(side_effect=RuntimeError("parou"))):
        with pytest.raises(RuntimeError, match="parou"):
            await orchestrator.handle_request("teste", [AgentTask(agent_id="developer", prompt="p")])

    first_update = session_manager.update.call_args_list[0]
    payload = first_update.kwargs["payload"]
    assert payload["llm_routing"]["papeis"]["developer"]["id"] == "google/gemini-3.8-flash"
    assert payload["llm_routing"]["catalogo"]["hash"]


@pytest.mark.asyncio
async def test_sessao_nao_comeca_sem_modelo_elegivel(monkeypatch):
    """Cenário: Nenhum modelo sob a política (a sessão não começa; nenhuma sessão é criada)."""
    from src.llm.routing import NoEligibleModelError
    from src.orchestrator import AgentTask, Orchestrator

    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "")
    session_manager = MagicMock()
    orchestrator = Orchestrator(session_manager=session_manager, agent_runtime=MagicMock())

    with pytest.raises(NoEligibleModelError) as exc:
        await orchestrator.handle_request("teste", [AgentTask(agent_id="developer", prompt="p")])

    assert "LLM_DATA_POLICY=third_party_allowed" in str(exc.value)
    session_manager.create.assert_not_called()


@pytest.mark.asyncio
async def test_banner_sem_segredos(nuvem, capsys):
    """Cenário: Banner (uma linha por papel, sem nenhum valor de *_API_KEY)."""
    from src.cli import print_session_banner

    routing = await build_session_routing()
    print_session_banner("assisted", context_dir="/inexistente", llm_routing=routing)

    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    for role, resolution in routing.papeis.items():
        assert re.search(rf"^\s*{role}\s+{re.escape(resolution.id)}\s+\({resolution.trust}\)$", out, re.M), role
    assert "third_party_allowed" in out and "flexible" in out
    assert routing.catalogo.short_hash in out
    assert CHAVE_GEMINI not in out and CHAVE_CLAUDE not in out
    assert CHAVE_GEMINI not in json.dumps(routing.payload())


@pytest.mark.asyncio
async def test_politica_e_modo_no_banner_e_hash_curto(nuvem):
    routing = await build_session_routing()

    header = routing.banner_lines()[0]
    assert "política: third_party_allowed" in header
    assert f"catálogo v{routing.catalogo.versao} · {routing.catalogo.hash[:8]}" in header


@pytest.mark.asyncio
async def test_mapa_e_resolvido_uma_vez_e_nao_muda_na_sessao(nuvem, monkeypatch):
    routing = await build_session_routing()
    bind_session_routing(routing)
    before = routing.payload()

    # Mudanças posteriores de ambiente/chaves não alteram o mapa da sessão em curso.
    monkeypatch.setattr("src.config.LLM_DATA_POLICY", "self_hosted_only")
    monkeypatch.setattr("src.config.GEMINI_API_KEY", None)
    from src.model_config import get_role_model_config

    assert get_role_model_config("researcher").provider == "anthropic"
    assert routing.payload() == before


@pytest.mark.asyncio
async def test_429_nao_troca_o_modelo_resolvido(nuvem):
    """Cenário: 429 não troca o modelo resolvido (a retentativa usa o mesmo id e conta como retry)."""
    from src.llm.providers.google import GoogleProvider

    routing = await build_session_routing()
    bind_session_routing(routing)
    resolved_before = routing.resolution("developer").id

    rate_limit = Exception("429 RESOURCE_EXHAUSTED. Quota exceeded")
    ok = object()  # resposta qualquer: _call_with_retry a devolve sem interpretar
    with patch("src.llm.providers.google.genai.Client") as client_cls, \
         patch("src.llm.providers.google.asyncio.sleep", AsyncMock()), \
         patch("src.llm.providers.google.emit_connection_retry") as emit:
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(side_effect=[rate_limit, rate_limit, ok])
        client_cls.return_value = client
        provider = GoogleProvider(api_key="k", model="gemini-3.8-flash", fallback_model=None)
        await provider._call_with_retry("gemini-3.8-flash", [], None)

    models_used = [call.kwargs["model"] for call in client.aio.models.generate_content.call_args_list]
    assert models_used == ["gemini-3.8-flash"] * 3
    assert emit.call_count == 2  # cada retentativa é registrada e conta no orçamento de conexão da sessão
    assert routing.resolution("developer").id == resolved_before == "google/gemini-3.8-flash"


@pytest.mark.asyncio
async def test_fallback_do_google_so_com_catalogo_trust_e_flexivel(nuvem, monkeypatch):
    routing = await build_session_routing()
    primary = "google/gemini-3.8-flash"

    monkeypatch.setattr("src.config.GOOGLE_FALLBACK_MODEL", "gemini-3.7-flash")
    assert routing.fallback_for(primary) == "gemini-3.7-flash"

    monkeypatch.setattr("src.config.GOOGLE_FALLBACK_MODEL", "gemini-9-inexistente")
    assert routing.fallback_for(primary) is None

    monkeypatch.setattr("src.config.GOOGLE_FALLBACK_MODEL", "")
    assert routing.fallback_for(primary) is None

    monkeypatch.setattr("src.config.GOOGLE_FALLBACK_MODEL", "gemini-3.7-flash")
    assert routing.fallback_for("anthropic/claude-sonnet-5-5") is None
    strict = await _build_strict(monkeypatch)
    assert strict.fallback_for(primary) is None


async def _build_strict(monkeypatch) -> SessionRouting:
    monkeypatch.setattr("src.config.LLM_ROUTING", "strict")
    return await build_session_routing()


@pytest.mark.asyncio
async def test_dica_sem_provedor_na_subtarefa_despachada(nuvem, monkeypatch, caplog):
    """Cenário: Dica sem provedor (o Developer usa o modelo resolvido e um WARNING cita a dica)."""
    import logging

    from src.orchestrator import AgentTask, Orchestrator

    routing = await build_session_routing()
    bind_session_routing(routing)
    ctx_capturado = {}

    async def _run(task, ctx):
        ctx_capturado["model"] = ctx.model
        return MagicMock(status="success", response={}, error=None)

    session_manager = MagicMock()
    session_manager.create.return_value = MagicMock(id="sess_agent")
    runtime = MagicMock()
    runtime.run = _run
    orchestrator = Orchestrator(session_manager=session_manager, agent_runtime=runtime)
    orchestrator.rate_limiter = MagicMock(acquire=AsyncMock(), report_success=AsyncMock(), report_429=AsyncMock())

    with caplog.at_level(logging.WARNING, logger="src.llm.routing"):
        await orchestrator._execute_agent(AgentTask(agent_id="developer", prompt="p", preferred_model="qwen3:8b"), "m")

    assert ctx_capturado["model"] == routing.resolution("developer").id
    assert any(getattr(r, "hint", None) == "qwen3:8b" for r in caplog.records)


@pytest.mark.asyncio
async def test_dica_valida_na_subtarefa_despachada(nuvem):
    """Cenário: Dica válida (a subtarefa do Developer usa ollama/qwen3:8b)."""
    from src.orchestrator import AgentTask, Orchestrator

    routing = await build_session_routing()
    bind_session_routing(routing)
    ctx_capturado = {}

    async def _run(task, ctx):
        ctx_capturado["model"] = ctx.model
        return MagicMock(status="success", response={}, error=None)

    session_manager = MagicMock()
    session_manager.create.return_value = MagicMock(id="sess_agent")
    runtime = MagicMock()
    runtime.run = _run
    orchestrator = Orchestrator(session_manager=session_manager, agent_runtime=runtime)
    orchestrator.rate_limiter = MagicMock(acquire=AsyncMock(), report_success=AsyncMock(), report_429=AsyncMock())

    await orchestrator._execute_agent(
        AgentTask(agent_id="developer", prompt="p", preferred_model="ollama/qwen3:8b"), "m"
    )

    assert ctx_capturado["model"] == "ollama/qwen3:8b"


def test_resolucao_fora_de_sessao_nao_faz_health_check(monkeypatch):
    """Fora de sessão a resolução é síncrona e não consulta a rede (só credencial e lista de permissão)."""
    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://test:11434")

    routing = build_offline_routing()

    assert routing.resolution("researcher").id == "ollama/qwen3:8b"
