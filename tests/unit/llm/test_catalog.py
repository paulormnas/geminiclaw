"""Cenários do requisito "Catálogo versionado e validado" e correlatos (v16-model-catalog-router)."""

import hashlib
import logging

import pytest

from src.llm.catalog import REQUIRED_ROLES, CatalogError, load_catalog
from tests.support.catalog_fixtures import REGISTERED, base_document, load, model

pytestmark = pytest.mark.unit


def test_catalogo_versionado_valido(tmp_path):
    """Cenário: Catálogo versionado válido."""
    catalog = load_catalog(local_path=tmp_path / "inexistente.yaml", base_urls={})

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
        load(tmp_path, local=local, base_urls={"openai_compatible": "http://gpu.exemplo.org/v1"})

    assert "https" in str(exc.value)


def test_http_em_rede_privada(tmp_path):
    """Cenário: http em rede privada."""
    local = {"modelos": [model("openai_compatible/llama-3.3-70b", "self_hosted")]}

    catalog = load(tmp_path, local=local, base_urls={"openai_compatible": "http://192.168.0.20:8080/v1"})

    assert "openai_compatible/llama-3.3-70b" in catalog.modelos


@pytest.mark.parametrize("url", ["http://localhost:8000/v1", "http://127.0.0.1:8000/v1", "https://gpu.exemplo.org/v1"])
def test_loopback_e_https_sao_aceitos(tmp_path, url):
    local = {"modelos": [model("openai_compatible/llama-3.3-70b", "self_hosted")]}

    load(tmp_path, local=local, base_urls={"openai_compatible": url})


def test_provedor_openai_com_endpoint_http_publico(tmp_path):
    """Cenário: Provedor openai com endpoint http público (sem nenhuma entrada openai_compatible)."""
    with pytest.raises(CatalogError) as exc:
        load(tmp_path, base_urls={"openai": "http://gpu.exemplo.org/v1"}, document=_com_openai())

    assert "https" in str(exc.value) and "openai" in str(exc.value)


def _com_openai():
    doc = base_document()
    doc["modelos"].append(model("openai/gpt-6-luna", "third_party"))
    return doc


def test_ollama_remoto_sem_https(tmp_path):
    """Cenário: Ollama remoto sem https."""
    with pytest.raises(CatalogError, match="https"):
        load(tmp_path, base_urls={"ollama": "http://gpu.exemplo.org:11434"})


@pytest.mark.parametrize("url", ["http://169.254.169.254/", "http://[fe80::1]:11434"])
def test_endpoint_link_local(tmp_path, url):
    """Cenário: Endpoint link-local (não conta como rede privada)."""
    with pytest.raises(CatalogError, match="https"):
        load(tmp_path, base_urls={"ollama": url})


def test_endpoint_so_e_validado_para_provedor_presente_no_catalogo(tmp_path):
    load(tmp_path, base_urls={"anthropic_inexistente": "http://gpu.exemplo.org"})


def test_ollama_em_loopback_e_rede_privada_com_http(tmp_path):
    load(tmp_path, base_urls={"ollama": "http://localhost:11434"})
    load(tmp_path, base_urls={"ollama": "http://192.168.0.20:11434"})


def test_criacao_do_provedor_tambem_valida_o_endpoint(monkeypatch):
    from src.llm import registry
    from src.llm.endpoints import EndpointError

    monkeypatch.setattr("src.config.OLLAMA_BASE_URL", "http://gpu.exemplo.org:11434")

    with pytest.raises(EndpointError, match="https"):
        registry.create_provider("ollama", "qwen3:8b")


def test_variaveis_do_openai_compatible_separadas_das_do_openai(monkeypatch):
    """Cenário: Variáveis do openai_compatible separadas (a chave do openai não vai ao compatível)."""
    from src.llm import registry
    from src.llm.providers.openai_compatible import OpenAICompatibleProvider

    monkeypatch.setattr("src.config.OPENAI_API_KEY", "sk-real-da-openai")
    monkeypatch.setattr("src.config.OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setattr("src.config.OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setattr("src.config.OPENAI_COMPATIBLE_API_KEY", None)

    provider = registry.create_provider("openai_compatible", "llama")

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._api_key is None
    assert provider._base_url == "http://localhost:8000/v1"
    assert registry.has_api_key("openai_compatible") is False
    assert registry.resolve_base_url("openai_compatible") == "http://localhost:8000/v1"


def test_erro_de_endpoint_nao_vaza_credenciais(tmp_path):
    local = {"modelos": [model("openai_compatible/llama-3.3-70b", "self_hosted")]}

    with pytest.raises(CatalogError) as exc:
        load(tmp_path, local=local, base_urls={"openai_compatible": "http://usuario:segredo@gpu.exemplo.org/v1"})

    assert "segredo" not in str(exc.value)
    assert "usuario" not in str(exc.value)


def test_modelo_de_nuvem_rotulado_self_hosted(tmp_path):
    """Cenário: Modelo de nuvem rotulado self_hosted (catálogo local)."""
    local = {"modelos": [model("google/gemini-9", "self_hosted")]}

    with pytest.raises(CatalogError) as exc:
        load(tmp_path, local=local)

    message = str(exc.value)
    assert "catalog.local.yaml" in message and "trust" in message and "google/gemini-9" in message


@pytest.mark.parametrize("model_id", ["google/x", "anthropic/x", "openai/x"])
def test_trust_self_hosted_recusado_tambem_no_catalogo_versionado(tmp_path, model_id):
    doc = base_document()
    doc["modelos"].append(model(model_id, "self_hosted"))

    with pytest.raises(CatalogError, match="nuvem"):
        load(tmp_path, doc)


def test_ollama_e_openai_compatible_podem_ser_self_hosted(tmp_path):
    load(tmp_path, local={"modelos": [model("openai_compatible/x", "self_hosted")]})


def test_chave_duplicada(tmp_path):
    """Cenário: Chave duplicada (a última não vence em silêncio)."""
    path = tmp_path / "catalog.yaml"
    base = yaml_dump(base_document())
    duplicated = base.replace("trust: third_party", "trust: third_party\n    trust: self_hosted", 1)
    path.write_text(duplicated, encoding="utf-8")

    with pytest.raises(CatalogError, match="duplicada"):
        load_catalog(path, tmp_path / "x.yaml", registered_providers=REGISTERED, base_urls={})


def yaml_dump(doc):
    import yaml

    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def test_yaml_malformado(tmp_path):
    path = tmp_path / "catalog.yaml"
    path.write_text("versao: [1,", encoding="utf-8")

    with pytest.raises(CatalogError, match="inválido"):
        load_catalog(path, tmp_path / "x.yaml", registered_providers=REGISTERED, base_urls={})


def test_rede_sobreposta_do_tailscale_conta_como_privada(tmp_path):
    """100.64.0.0/10 (Tailscale) é privada; 100.128.x já é internet pública."""
    load(tmp_path, base_urls={"ollama": "http://100.101.56.43:11434"})
    with pytest.raises(CatalogError, match="https"):
        load(tmp_path, base_urls={"ollama": "http://100.128.0.1:11434"})
