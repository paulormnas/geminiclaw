import os
import pytest
from unittest.mock import patch
import importlib

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
        "AGENT_TIMEOUT_SECONDS",
        "DATABASE_URL",
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
def test_config_missing_required_variable_raises_error():
    """Testa se omitir GEMINI_API_KEY lança RuntimeError."""
    with patch.dict(os.environ, {}, clear=True):
        # Como o módulo é importado uma vez, precisamos recarregá-lo
        with pytest.raises(RuntimeError) as excinfo:
            importlib.reload(src.config)
        assert "GEMINI_API_KEY" in str(excinfo.value)

@pytest.mark.unit
def test_config_default_values():
    """Testa se os valores padrão são aplicados corretamente."""
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key"}):
        importlib.reload(src.config)
        assert src.config.DEFAULT_MODEL == "gemini-3.1-pro-preview"
        assert src.config.AGENT_TIMEOUT_SECONDS == 120
        assert "postgresql://" in src.config.DATABASE_URL
        assert not hasattr(src.config, "SQLITE_DB_PATH") or src.config.DATABASE_URL

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
