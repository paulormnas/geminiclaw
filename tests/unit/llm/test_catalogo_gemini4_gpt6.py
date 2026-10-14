"""Catálogo v5 com Gemini 4 e GPT-6 (v18.6-models-gemini4-gpt6), um teste por Scenario do delta ``llm-providers``."""

from __future__ import annotations

import importlib

import pytest

from src.llm.catalog import CatalogError, load_catalog
from src.llm.routing import Pin, resolve_session
from tests.support.catalog_fixtures import all_available, load, model

pytestmark = pytest.mark.unit


def test_modelos_novos_no_catalogo(tmp_path) -> None:
    catalog = load_catalog(local_path=tmp_path / "inexistente.yaml", base_urls={})
    assert catalog.versao == 5
    assert catalog.modelos["google/gemini-4-argon"].familia_modelo == "gemini"
    assert catalog.modelos["openai/gpt-6.1-sol"].familia_modelo == "gpt"
    assert "google/gemini-3.8-flash" not in catalog.modelos
    assert "openai/gpt-5.6-terra" not in catalog.modelos


def test_catalogo_local_com_modelo_removido(tmp_path) -> None:
    """A mensagem cita o modelo: o catálogo local não pode redeclarar nem referenciar o que saiu."""
    local = {"papeis": {}, "modelos": [model("google/gemini-3.8-flash", "third_party")]}
    with pytest.raises(CatalogError):
        load(tmp_path, local=local)


def test_validator_de_outra_familia_com_developer_gemini(tmp_path) -> None:
    catalog = load_catalog(local_path=tmp_path / "inexistente.yaml", base_urls={})
    papeis = resolve_session(
        catalog, all_available(catalog), "third_party_allowed",
        {"developer": Pin("google/gemini-4-argon")}, "flexible", "required",
    )
    assert catalog.modelos[papeis["developer"].id].familia_modelo == "gemini"
    assert catalog.modelos[papeis["validator"].id].familia_modelo != "gemini"


def test_padrao_do_fallback_do_google(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_FALLBACK_MODEL", raising=False)
    from src import config

    try:
        importlib.reload(config)
        assert config.GOOGLE_FALLBACK_MODEL == "gemini-4-argon"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
