"""Integração de v18.5-model-catalog-locality (escrita; executada só na bateria de integração final).

- Catálogo versionado real com os provedores realmente registrados, resolvido de ponta a ponta e serializado no
  formato do payload JSONB da sessão.
- Leitura real do digest do Ollama (``/api/tags``): só roda com ``GEMINICLAW_LIVE_OLLAMA_TEST=1`` e um Ollama
  acessível em ``OLLAMA_BASE_URL``; fora disso é pulada.
"""

import json
import os

import pytest

from src.llm import registry
from src.llm.allocation import build_allocation_profile
from src.llm.availability import Availability
from src.llm.catalog import load_catalog
from src.llm.providers.ollama import OllamaProvider, clear_known_digests
from src.llm.routing import resolve_session
from src.llm.session import SessionRouting
from src.llm.versions import UNKNOWN_VERSION, VersionTracker


@pytest.mark.integration
def test_catalogo_versionado_real_resolve_e_serializa_o_perfil(tmp_path):
    catalog = load_catalog(local_path=tmp_path / "inexistente.yaml")
    available = {model_id: Availability(True) for model_id in catalog.modelos}

    resolved = resolve_session(catalog, available, "third_party_allowed")
    routing = SessionRouting("third_party_allowed", "flexible", catalog, resolved, available, VersionTracker())
    profile = build_allocation_profile(routing)

    json.loads(json.dumps(profile))  # cabe no JSONB da sessão
    assert set(profile["papeis"]) >= {"researcher", "developer", "validator", "summarizer", "reviewer", "base"}
    for entry in profile["papeis"].values():
        assert entry["familia_modelo"]
        if entry["trust"] == "third_party":
            assert entry["aceita_dados_brutos"] is False and entry["localidade"] == "fora_do_no"
    assert {"google", "ollama"} <= set(registry.available_providers())


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("GEMINICLAW_LIVE_OLLAMA_TEST") != "1" or not os.getenv("OLLAMA_BASE_URL"),
    reason="exige GEMINICLAW_LIVE_OLLAMA_TEST=1 e OLLAMA_BASE_URL apontando para um Ollama acessível",
)
async def test_digest_real_do_ollama():
    clear_known_digests()
    provider = OllamaProvider(os.environ["OLLAMA_BASE_URL"], os.getenv("OLLAMA_LIVE_MODEL", "qwen3:8b"))

    digest = await provider.fetch_digest()

    assert digest != UNKNOWN_VERSION and digest.startswith("sha256:")
