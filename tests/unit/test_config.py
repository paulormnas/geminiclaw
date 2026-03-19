import os
import pytest
from unittest.mock import patch
import importlib

# Define uma chave fictícia para permitir a importação inicial sem erro
os.environ["GENAI_API_KEY"] = "dummy_initial_key"
import src.config

@pytest.fixture(autouse=True)
def reset_env():
    """Limpa variáveis de ambiente relevantes antes de cada teste."""
    vars_to_clear = [
        "GENAI_API_KEY",
        "DEFAULT_MODEL",
        "AGENT_TIMEOUT_SECONDS",
        "SQLITE_DB_PATH"
    ]
    old_vars = {k: os.environ.get(k) for k in vars_to_clear}
    for k in vars_to_clear:
        if k in os.environ:
            del os.environ[k]
    yield
    # Restaura variáveis após o teste
    for k, v in old_vars.items():
        if v is not None:
            os.environ[k] = v
        elif k in os.environ:
            del os.environ[k]

@pytest.mark.unit
def test_config_missing_required_variable_raises_error():
    """Testa se omitir GENAI_API_KEY lança RuntimeError."""
    with patch.dict(os.environ, {}, clear=True):
        # Como o módulo é importado uma vez, precisamos recarregá-lo
        # ou testar apenas a função de auxílio se estivermos isolando.
        # Mas o objetivo é testar o carregamento do módulo.
        with pytest.raises(RuntimeError) as excinfo:
            importlib.reload(src.config)
        assert "GENAI_API_KEY" in str(excinfo.value)

@pytest.mark.unit
def test_config_default_values():
    """Testa se os valores padrão são aplicados corretamente."""
    with patch.dict(os.environ, {"GENAI_API_KEY": "fake_key"}):
        importlib.reload(src.config)
        assert src.config.DEFAULT_MODEL == "gemini-3-flash-preview"
        assert src.config.AGENT_TIMEOUT_SECONDS == 120
        assert src.config.SQLITE_DB_PATH == "store/geminiclaw.db"

@pytest.mark.unit
def test_config_custom_values():
    """Testa se valores personalizados no ambiente sobrescrevem os padrões."""
    custom_env = {
        "GENAI_API_KEY": "another_key",
        "DEFAULT_MODEL": "gemini-ultra",
        "AGENT_TIMEOUT_SECONDS": "240",
        "SQLITE_DB_PATH": "custom/path.db"
    }
    with patch.dict(os.environ, custom_env):
        importlib.reload(src.config)
        assert src.config.GENAI_API_KEY == "another_key"
        assert src.config.DEFAULT_MODEL == "gemini-ultra"
        assert src.config.AGENT_TIMEOUT_SECONDS == 240
        assert src.config.SQLITE_DB_PATH == "custom/path.db"
