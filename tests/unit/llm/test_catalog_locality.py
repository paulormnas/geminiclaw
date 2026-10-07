"""Cenários de localidade, dados brutos e família no catálogo (v18.5-model-catalog-locality)."""

import logging

import pytest

from src.llm.catalog import CatalogError, load_catalog
from tests.support.catalog_fixtures import base_document, load, model

pytestmark = pytest.mark.unit

GEMINI = "google/gemini-3.8-flash"
QWEN = "ollama/qwen3:8b"


def _compat(**extra):
    return model("openai_compatible/llama-3.3-70b", "self_hosted", **extra)


def test_padroes_seguros(tmp_path):
    """Cenário: Padrões seguros."""
    catalog = load(tmp_path)

    entry = catalog.modelos[GEMINI]
    assert entry.localidade == "fora_do_no"
    assert entry.aceita_dados_brutos is False


def test_modelo_no_no(tmp_path):
    """Cenário: Modelo no nó (aceita_dados_brutos efetivo true)."""
    doc = base_document()
    doc["modelos"][2]["localidade"] = "no_no"

    catalog = load(tmp_path, doc)

    assert catalog.modelos[QWEN].localidade == "no_no"
    assert catalog.modelos[QWEN].aceita_dados_brutos is True


def test_self_hosted_fora_do_no_com_declaracao_explicita(tmp_path):
    doc = base_document()
    doc["modelos"][2].update(localidade="fora_do_no", aceita_dados_brutos=True)

    assert load(tmp_path, doc).modelos[QWEN].aceita_dados_brutos is True


def test_endpoint_em_loopback_nao_muda_a_declaracao(tmp_path, caplog):
    """Cenário: Endpoint em loopback não muda a declaração."""
    with caplog.at_level(logging.WARNING, logger="src.llm.catalog"):
        catalog = load(
            tmp_path,
            local={"modelos": [_compat(localidade="fora_do_no")]},
            base_urls={"openai_compatible": "http://127.0.0.1:8080"},
        )

    assert catalog.modelos["openai_compatible/llama-3.3-70b"].localidade == "fora_do_no"
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("loopback" in m and "túnel ou proxy" in m for m in messages)


def test_declaracao_no_no_com_endpoint_remoto(tmp_path, caplog):
    """Cenário: Declaração no nó com endpoint remoto."""
    with caplog.at_level(logging.WARNING, logger="src.llm.catalog"):
        catalog = load(
            tmp_path,
            local={"modelos": [_compat(localidade="no_no")]},
            base_urls={"openai_compatible": "https://gpu.exemplo.org"},
        )

    assert catalog.modelos["openai_compatible/llama-3.3-70b"].localidade == "no_no"
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("openai_compatible/llama-3.3-70b" in m and "gpu.exemplo.org" in m for m in messages)


def test_declaracao_coerente_com_endpoint_nao_avisa(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="src.llm.catalog"):
        load(
            tmp_path,
            local={"modelos": [_compat(localidade="no_no")]},
            base_urls={"openai_compatible": "http://localhost:8080"},
        )

    assert not [r for r in caplog.records if "endpoint" in r.getMessage()]


def test_terceiro_declarando_dados_brutos(tmp_path):
    """Cenário: Terceiro declarando dados brutos."""
    doc = base_document()
    doc["modelos"][1]["aceita_dados_brutos"] = True

    with pytest.raises(CatalogError) as exc:
        load(tmp_path, doc)

    assert GEMINI in str(exc.value)
    assert "catalog.yaml" in str(exc.value)


def test_terceiro_no_no(tmp_path):
    doc = base_document()
    doc["modelos"][1]["localidade"] = "no_no"

    with pytest.raises(CatalogError, match="third_party") as exc:
        load(tmp_path, doc)

    assert GEMINI in str(exc.value)


def test_no_no_com_dados_brutos_false_explicito(tmp_path):
    doc = base_document()
    doc["modelos"][2].update(localidade="no_no", aceita_dados_brutos=False)

    with pytest.raises(CatalogError, match="contraditória") as exc:
        load(tmp_path, doc)

    assert QWEN in str(exc.value)


def test_localidade_fora_do_enum(tmp_path):
    doc = base_document()
    doc["modelos"][2]["localidade"] = "nuvem"

    with pytest.raises(CatalogError, match="localidade"):
        load(tmp_path, doc)


def test_catalogo_local_que_aceita_dados_brutos(tmp_path, caplog):
    """Cenário: Catálogo local que aceita dados brutos."""
    local = {"modelos": [_compat(aceita_dados_brutos=True)]}

    with caplog.at_level(logging.WARNING, logger="src.llm.catalog"):
        catalog = load(tmp_path, local=local)

    assert catalog.modelos["openai_compatible/llama-3.3-70b"].aceita_dados_brutos is True
    assert catalog.local_hash is not None
    specific = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and getattr(r, "id", None) == "openai_compatible/llama-3.3-70b"
    ]
    assert specific


@pytest.mark.parametrize("familia", [None, "", "Qwen", "-qwen", "qw en"])
def test_familia_ausente_ou_invalida(tmp_path, familia):
    """Cenário: Família ausente."""
    doc = base_document()
    if familia is None:
        del doc["modelos"][0]["familia_modelo"]
    else:
        doc["modelos"][0]["familia_modelo"] = familia

    with pytest.raises(CatalogError, match="familia_modelo") as exc:
        load(tmp_path, doc)

    assert "anthropic/claude-sonnet-5-5" in str(exc.value)


def test_catalogo_versionado_declara_localidade_e_familia(tmp_path):
    """Todas as entradas do catálogo versionado são válidas e Ollama é no nó."""
    catalog = load_catalog(local_path=tmp_path / "inexistente.yaml", base_urls={})

    for entry in catalog.modelos.values():
        assert entry.familia_modelo
        if entry.trust == "third_party":
            assert entry.localidade == "fora_do_no" and entry.aceita_dados_brutos is False
    assert catalog.modelos[QWEN].localidade == "no_no"
    assert catalog.modelos[QWEN].aceita_dados_brutos is True


def test_posicao_de_preferencia_com_grupo(tmp_path):
    doc = base_document()
    doc["papeis"]["validator"]["preferencia"] = [[GEMINI, QWEN], "anthropic/claude-sonnet-5-5"]

    catalog = load(tmp_path, doc)

    spec = catalog.papeis["validator"]
    assert spec.preferencia_grupos == ((GEMINI, QWEN), ("anthropic/claude-sonnet-5-5",))
    assert spec.preferencia == (GEMINI, QWEN, "anthropic/claude-sonnet-5-5")


def test_grupo_com_id_inexistente_ou_vazio(tmp_path):
    doc = base_document()
    doc["papeis"]["validator"]["preferencia"] = [[GEMINI, "ollama/nao-existe"]]
    with pytest.raises(CatalogError, match="inexistente"):
        load(tmp_path, doc)

    doc["papeis"]["validator"]["preferencia"] = [[]]
    with pytest.raises(CatalogError, match="vazia"):
        load(tmp_path, doc)
