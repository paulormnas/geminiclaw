"""Cenário "Perfil de alocação da sessão" (v18.5-model-catalog-locality)."""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.allocation import allocation_banner_lines, build_allocation_profile, current_allocation
from src.llm.session import bind_session_routing, build_session_routing
from src.model_router import ModelRouter

pytestmark = pytest.mark.unit

CHAVE_GEMINI = "AIza-chave-do-gemini-nao-pode-vazar"
CHAVE_CLAUDE = "sk-ant-chave-do-claude-nao-pode-vazar"


@pytest.fixture(autouse=True)
def unbind_session_routing():
    """O mapa vinculado ao contexto não pode vazar para outros testes."""
    from src.llm import session

    yield
    session._current.set(None)


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
async def test_perfil_no_payload(nuvem):
    """Cenário: Perfil no payload (um registro por papel com os campos de localidade, família e versão)."""
    routing = await build_session_routing()

    profile = build_allocation_profile(routing)

    assert set(profile["papeis"]) == set(routing.papeis)
    researcher = profile["papeis"]["researcher"]
    assert researcher == {
        "provedor_modelo": "anthropic/claude-sonnet-5-5",
        "trust": "third_party",
        "localidade": "fora_do_no",
        "aceita_dados_brutos": False,
        "familia_modelo": "claude",
        "versao_efetiva": "desconhecida",
    }
    curator = profile["papeis"]["curator"]
    assert curator["localidade"] == "no_no" and curator["aceita_dados_brutos"] is True
    assert profile["papeis"]["validator"]["desempate"]["escolhido"] == "anthropic/claude-sonnet-5-5"
    assert profile["catalogo"]["hash"] == routing.catalogo.hash
    assert profile["catalogo"]["versao"] == routing.catalogo.versao
    assert profile["catalogo"]["local_hash"] is None
    assert CHAVE_GEMINI not in json.dumps(profile) and CHAVE_CLAUDE not in json.dumps(profile)


@pytest.mark.asyncio
async def test_orquestrador_grava_o_perfil_antes_do_primeiro_envio(nuvem):
    """Cenário: Perfil no payload (gravado pelo orquestrador ao iniciar a sessão, antes de qualquer envio)."""
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

    payload = session_manager.update.call_args_list[0].kwargs["payload"]
    assert payload["allocation_profile"]["papeis"]["developer"]["provedor_modelo"] == "google/gemini-3.8-flash"
    assert payload["allocation_profile"]["papeis"]["researcher"]["localidade"] == "fora_do_no"
    assert payload["eventos_versao_modelo"] == []
    json.dumps(payload["allocation_profile"])


@pytest.mark.asyncio
async def test_banner_com_bloco_alocacao(nuvem, capsys):
    """Cenário: Perfil no banner (uma linha por papel com trust, localidade e aceitação de dados brutos)."""
    from src.cli import print_session_banner

    routing = await build_session_routing()
    print_session_banner("assisted", context_dir="/inexistente", llm_routing=routing)

    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert "Alocação" in out
    assert re.search(
        r"^\s*researcher\s+→ anthropic/claude-sonnet-5-5 · third_party · fora_do_no · dados brutos: não$", out, re.M
    )
    assert re.search(r"^\s*curator\s+→ ollama/qwen3:8b · self_hosted · no_no · dados brutos: sim$", out, re.M)
    assert len(allocation_banner_lines(routing)) == len(routing.papeis)
    assert CHAVE_GEMINI not in out and CHAVE_CLAUDE not in out


@pytest.mark.asyncio
async def test_current_allocation_le_o_mapa_da_sessao(nuvem):
    bind_session_routing(await build_session_routing())

    allocation = current_allocation("planner")  # alias de researcher

    assert allocation.papel == "researcher"
    assert allocation.modelo == "claude-sonnet-5-5"
    with pytest.raises(ValueError):
        current_allocation("inexistente")
