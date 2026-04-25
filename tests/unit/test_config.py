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
        "AGENT_TIMEOUT_SECONDS",
        "SQLITE_DB_PATH"
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
        # O valor padrão no código é "gemini-2.0-flash"
        assert src.config.DEFAULT_MODEL == "gemini-2.0-flash"
        assert src.config.AGENT_TIMEOUT_SECONDS == 120
        assert src.config.SQLITE_DB_PATH == "store/geminiclaw.db"

@pytest.mark.unit
def test_config_custom_values():
    """Testa se valores personalizados no ambiente sobrescrevem os padrões."""
    custom_env = {
        "GEMINI_API_KEY": "another_key",
        "DEFAULT_MODEL": "gemini-ultra",
        "AGENT_TIMEOUT_SECONDS": "240",
        "SQLITE_DB_PATH": "custom/path.db"
    }
    with patch.dict(os.environ, custom_env):
        importlib.reload(src.config)
        assert src.config.GEMINI_API_KEY == "another_key"
        assert src.config.DEFAULT_MODEL == "gemini-ultra"
        assert src.config.AGENT_TIMEOUT_SECONDS == 240
        assert src.config.SQLITE_DB_PATH == "custom/path.db"
