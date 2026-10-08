import importlib
import os
from unittest.mock import patch

import pytest

# Define uma chave fictícia temporária para permitir a importação inicial sem erro e sem poluir globalmente
with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy_initial_key"}):
    import src.config

@pytest.fixture(autouse=True)
def reset_env():
    """Limpa variáveis de ambiente relevantes antes de cada teste."""
    vars_to_clear = [
        "GEMINI_API_KEY",
        "DEFAULT_MODEL",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_DATA_POLICY",
        "LLM_ROUTING",
        "LLM_PROVIDER_PRIORITY",
        "AGENT_TIMEOUT_SECONDS",
        "DATABASE_URL",
        "DEPLOYMENT_PROFILE",
    ]
    old_vars = {k: os.environ.get(k) for k in vars_to_clear}
    for k in vars_to_clear:
        if k in os.environ:
            del os.environ[k]
    
    # Mock load_dotenv para evitar carregar o .env real durante os testes unitários
    with patch("dotenv.load_dotenv"):
        yield
    
    # Restaura variáveis após o teste
    for k, v in old_vars.items():
        if v is not None:
            os.environ[k] = v
        elif k in os.environ:
            del os.environ[k]

@pytest.mark.unit
def test_config_gemini_api_key_nao_e_obrigatoria():
    """Sem GEMINI_API_KEY a importação não falha: só o provedor Google fica indisponível (ADR 017)."""
    with patch.dict(os.environ, {}, clear=True):
        importlib.reload(src.config)
        assert src.config.GEMINI_API_KEY is None

@pytest.mark.unit
def test_config_default_values():
    """Testa se os valores padrão são aplicados corretamente."""
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}):
        importlib.reload(src.config)
        assert src.config.AGENT_TIMEOUT_SECONDS == 300
        assert "postgresql://" in src.config.DATABASE_URL
        assert not hasattr(src.config, "SQLITE_DB_PATH") or src.config.DATABASE_URL

@pytest.mark.unit
def test_config_llm_routing_defaults():
    """Padrões do roteamento: política restritiva, modo flexível, sem lista de permissão explícita."""
    with patch.dict(os.environ, {}, clear=True):
        importlib.reload(src.config)
        assert src.config.LLM_DATA_POLICY == "self_hosted_only"
        assert src.config.LLM_ROUTING == "flexible"
        assert src.config.LLM_PROVIDER_PRIORITY == ""
        assert src.config.LLM_HEALTH_CHECK_TIMEOUT_SECONDS == 5
        assert src.config.LLM_CATALOG_LOCAL_PATH == ""

@pytest.mark.unit
def test_config_llm_routing_overrides():
    env = {"LLM_DATA_POLICY": "Third_Party_Allowed", "LLM_ROUTING": "STRICT", "LLM_HEALTH_CHECK_TIMEOUT_SECONDS": "2"}
    with patch.dict(os.environ, env, clear=True):
        importlib.reload(src.config)
        assert src.config.LLM_DATA_POLICY == "third_party_allowed"
        assert src.config.LLM_ROUTING == "strict"
        assert src.config.LLM_HEALTH_CHECK_TIMEOUT_SECONDS == 2

@pytest.mark.unit
def test_config_variaveis_de_modelo_removidas():
    """LLM_PROVIDER/LLM_MODEL/DEFAULT_MODEL deixam de existir (o roteador decide por papel)."""
    with patch.dict(os.environ, {"LLM_PROVIDER": "ollama", "LLM_MODEL": "x", "DEFAULT_MODEL": "y"}, clear=True):
        importlib.reload(src.config)
        assert not hasattr(src.config, "LLM_PROVIDER")
        assert not hasattr(src.config, "LLM_MODEL")
        assert not hasattr(src.config, "DEFAULT_MODEL")

@pytest.mark.unit
def test_config_custom_database_url():
    """Testa se DATABASE_URL personalizada sobrescreve o padrão."""
    custom_url = "postgresql://user:pass@myhost:5432/mydb"
    custom_env = {
        "GEMINI_API_KEY": "another_key",
        "DATABASE_URL": custom_url,
    }
    with patch.dict(os.environ, custom_env):
        importlib.reload(src.config)
        assert src.config.DATABASE_URL == custom_url


@pytest.mark.unit
def test_config_strict_validation_removida():
    """STRICT_VALIDATION não tinha leitor em lugar nenhum (código morto) e foi removida."""
    with patch.dict(os.environ, {"STRICT_VALIDATION": "true"}, clear=True):
        importlib.reload(src.config)
        assert not hasattr(src.config, "STRICT_VALIDATION")
        for profile in ("pi5", "default"):
            with patch.dict(os.environ, {"DEPLOYMENT_PROFILE": profile}):
                importlib.reload(src.config)
                assert not hasattr(src.config, "STRICT_VALIDATION")
