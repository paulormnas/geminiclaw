import os
import pytest

# Define variáveis de ambiente necessárias para a importação do src.config nos testes unitários
os.environ["GENAI_API_KEY"] = "dummy_key_for_testing"
os.environ["DEFAULT_MODEL"] = "gemini-3-flash-preview"
os.environ["AGENT_TIMEOUT_SECONDS"] = "120"
os.environ["SQLITE_DB_PATH"] = ":memory:"
os.environ["SEARCH_CACHE_TTL_SECONDS"] = "3600"
