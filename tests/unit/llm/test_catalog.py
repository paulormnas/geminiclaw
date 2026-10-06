"""Cenários do requisito "Catálogo versionado e validado" e correlatos (v16-model-catalog-router)."""

import hashlib
import logging

import pytest

from src.llm.catalog import REQUIRED_ROLES, CatalogError, load_catalog
from tests.support.catalog_fixtures import REGISTERED, base_document, load, model

pytestmark = pytest.mark.unit


def test_catalogo_versionado_valido(tmp_path):
    """Cenário: Catálogo versionado válido."""
    catalog = load_catalog(local_path=tmp_path / "inexistente.yaml", openai_compatible_base_url=None)

    for role in REQUIRED_ROLES:
        assert catalog.papeis[role].preferencia, role
    assert catalog.versao >= 1
    assert len(catalog.hash) == 64
    # Cada papel termina em um modelo auto-hospedado: a sessão funciona sob self_hosted_only.
    for role in REQUIRED_ROLES:
        assert catalog.modelos[catalog.papeis[role].preferencia[-1]].trust == "self_hosted"


def test_campo_extra(tmp_path):
    """Cenário: Campo extra."""
    doc = base_document()
    doc["modelos"][0]["custo"] = 1

    with pytest.raises(CatalogError) as exc:
        load(tmp_path, doc)

    message = str(exc.value)
    assert "custo" in message
    assert "anthropic/claude-sonnet-5-5" in message
    assert "catalog.yaml" in message


def test_provedor_nao_registrado(tmp_path):
    """Cenário: Provedor não registrado."""
    doc = base_document()
    doc["modelos"].append(model("mistral/large", "third_party"))

    with pytest.raises(CatalogError) as exc:
        load(tmp_path, doc)

    message = str(exc.value)
    assert "mistral" in message
    for provider in REGISTERED:
        assert provider in message  # lista os provedores registrados


def test_id_duplicado(tmp_path):
    doc = base_document()
    doc["modelos"].append(model("ollama/qwen3:8b", "self_hosted"))

    with pytest.raises(CatalogError, match="duplicado"):
        load(tmp_path, doc)


def test_trust_fora_do_enum_e_janela_invalida(tmp_path):
    doc = base_document()
    doc["modelos"][0]["trust"] = "confiavel"
    with pytest.raises(CatalogError, match="trust"):
        load(tmp_path, doc)

    doc = base_document()
    doc["modelos"][0]["janela_contexto"] = 0
    with pytest.raises(CatalogError, match="janela_contexto"):
        load(tmp_path, doc)


def test_papel_sem_modelo_na_preferencia_e_id_inexistente(tmp_path):
    doc = base_document()
    doc["papeis"]["developer"]["preferencia"] = []
    with pytest.raises(CatalogError, match="developer"):
        load(tmp_path, doc)

    doc = base_document()
    doc["papeis"]["developer"]["preferencia"] = ["google/nao-existe"]
    with pytest.raises(CatalogError, match="nao-existe"):
        load(tmp_path, doc)


def test_papel_obrigatorio_ausente(tmp_path):
    doc = base_document()
    del doc["papeis"]["base"]
    with pytest.raises(CatalogError, match="base"):
        load(tmp_path, doc)


def test_provedor_difere_do_prefixo_do_id(tmp_path):
    doc = base_document()
    doc["modelos"][0]["provedor"] = "google"
    with pytest.raises(CatalogError, match="difere do prefixo"):
        load(tmp_path, doc)


def test_acrescimo_aceito(tmp_path, caplog):
    """Cenário: Acréscimo aceito."""
    local = {"modelos": [model("openai_compatible/llama-3.3-70b", "self_hosted")]}

    with caplog.at_level(logging.WARNING, logger="src.llm.catalog"):
        catalog = load(tmp_path, local=local)

    assert "openai_compatible/llama-3.3-70b" in catalog.modelos
    assert catalog.local is True
    local_file = tmp_path / "catalog.local.yaml"
    sha = hashlib.sha256(local_file.read_bytes()).hexdigest()
    warning = next(r for r in caplog.records if r.levelno == logging.WARNING and getattr(r, "sha256", None))
    assert warning.sha256 == sha
    assert warning.path == str(local_file)


def test_hash_do_catalogo_inclui_o_local(tmp_path):
    sem_local = load(tmp_path)
    com_local = load(tmp_path, local={"modelos": [model("ollama/outro:1b", "self_hosted")]})

    assert sem_local.hash != com_local.hash


def test_tentativa_de_rebaixar_trust(tmp_path):
    """Cenário: Tentativa de rebaixar trust."""
    local = {"modelos": [model("google/gemini-3.8-flash", "self_hosted")]}

    with pytest.raises(CatalogError, match="duplicado") as exc:
        load(tmp_path, local=local)

    assert "google/gemini-3.8-flash" in str(exc.value)


def test_catalogo_local_com_papeis_e_recusado(tmp_path):
    local = {"modelos": [], "papeis": {"researcher": {"preferencia": ["ollama/qwen3:8b"]}}}

    with pytest.raises(CatalogError, match="papeis"):
        load(tmp_path, local=local)


def test_http_para_host_publico(tmp_path, monkeypatch):
    """Cenário: http para host público (a sessão não inicia)."""
    local = {"modelos": [model("openai_compatible/llama-3.3-70b", "self_hosted")]}

    with pytest.raises(CatalogError) as exc:
        load(tmp_path, local=local, openai_compatible_base_url="http://gpu.exemplo.org/v1")

    assert "https" in str(exc.value)


def test_http_em_rede_privada(tmp_path):
    """Cenário: http em rede privada."""
    local = {"modelos": [model("openai_compatible/llama-3.3-70b", "self_hosted")]}

    catalog = load(tmp_path, local=local, openai_compatible_base_url="http://192.168.0.20:8080/v1")

    assert "openai_compatible/llama-3.3-70b" in catalog.modelos


@pytest.mark.parametrize("url", ["http://localhost:8000/v1", "http://127.0.0.1:8000/v1", "https://gpu.exemplo.org/v1"])
def test_loopback_e_https_sao_aceitos(tmp_path, url):
    local = {"modelos": [model("openai_compatible/llama-3.3-70b", "self_hosted")]}

    load(tmp_path, local=local, openai_compatible_base_url=url)


def test_https_so_vale_para_openai_compatible(tmp_path):
    """Sem entrada openai_compatible no catálogo, um OPENAI_BASE_URL http público não bloqueia (o
    provedor 'openai' usa o mesmo nome de variável)."""
    load(tmp_path, openai_compatible_base_url="http://gpu.exemplo.org/v1")


def test_erro_de_endpoint_nao_vaza_credenciais(tmp_path):
    local = {"modelos": [model("openai_compatible/llama-3.3-70b", "self_hosted")]}

    with pytest.raises(CatalogError) as exc:
        load(tmp_path, local=local, openai_compatible_base_url="http://usuario:segredo@gpu.exemplo.org/v1")

    assert "segredo" not in str(exc.value)
    assert "usuario" not in str(exc.value)
