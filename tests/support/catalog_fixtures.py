"""Catálogo e disponibilidade de teste para o roteador de modelos (ADR 017).

Os testes do roteador usam um catálogo pequeno e controlado, nunca o catálogo versionado (que
muda com o conteúdo), exceto no teste que valida o próprio ``src/llm/catalog.yaml``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.llm.availability import Availability
from src.llm.catalog import Catalog, load_catalog

REGISTERED = {"google", "anthropic", "openai", "ollama", "openai_compatible"}


def model(model_id: str, trust: str, *, ferramentas: bool = True, saida: bool = True, janela: int = 100000) -> dict:
    return {
        "id": model_id,
        "provedor": model_id.split("/", 1)[0],
        "trust": trust,
        "ferramentas": ferramentas,
        "saida_estruturada": saida,
        "janela_contexto": janela,
    }


def base_document() -> dict:
    """Catálogo mínimo válido: um modelo de nuvem, um do Claude e um local; todos os papéis."""
    prefs = ["anthropic/claude-sonnet-5-5", "google/gemini-3.8-flash", "ollama/qwen3:8b"]
    roles = {
        name: {"requisitos": {}, "preferencia": list(prefs)}
        for name in ("researcher", "developer", "reviewer", "summarizer", "validator", "base")
    }
    roles["researcher"]["requisitos"] = {"ferramentas": True}
    return {
        "versao": 1,
        "modelos": [
            model("anthropic/claude-sonnet-5-5", "third_party"),
            model("google/gemini-3.8-flash", "third_party"),
            model("ollama/qwen3:8b", "self_hosted"),
        ],
        "papeis": roles,
        "aliases_papel": {"planner": "researcher"},
    }


def write_yaml(path: Path, document: dict) -> Path:
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    return path


def load(tmp_path: Path, document: dict | None = None, local: dict | None = None, **kwargs) -> Catalog:
    """Escreve os YAML em ``tmp_path`` e carrega o catálogo efetivo."""
    main = write_yaml(tmp_path / "catalog.yaml", document or base_document())
    local_path = tmp_path / "catalog.local.yaml"
    if local is not None:
        write_yaml(local_path, local)
    kwargs.setdefault("registered_providers", REGISTERED)
    kwargs.setdefault("base_urls", {})
    return load_catalog(main, local_path, **kwargs)


def all_available(catalog: Catalog) -> dict[str, Availability]:
    return {model_id: Availability(True) for model_id in catalog.modelos}
