import os
from pathlib import Path
from dotenv import load_dotenv

# Carrega o arquivo .env se existir
load_dotenv()

def get_env(key: str, default: str | None = None, required: bool = False) -> str:
    """Obtém uma variável de ambiente com opção de valor padrão ou obrigatoriedade.

    Args:
        key: A chave da variável de ambiente.
        default: O valor padrão caso a variável não exista.
        required: Se True, lança um RuntimeError se a variável não estiver definida.

    Returns:
        O valor da variável de ambiente.

    Raises:
        RuntimeError: Se a variável for obrigatória e não estiver definida.
    """
    value = os.environ.get(key, default)
    if required and value is None:
        raise RuntimeError(f"Variável de ambiente obrigatória '{key}' não está definida.")
    return value  # type: ignore

# Variáveis obrigatórias
GEMINI_API_KEY = get_env("GEMINI_API_KEY", required=True)

# Variáveis opcionais com valores padrão
DEFAULT_MODEL = get_env("DEFAULT_MODEL", default="gemini-3.1-pro-preview")
AGENT_TIMEOUT_SECONDS = int(get_env("AGENT_TIMEOUT_SECONDS", default="120"))
SQLITE_DB_PATH = get_env("SQLITE_DB_PATH", default="store/geminiclaw.db")
OUTPUT_BASE_DIR = get_env("OUTPUT_BASE_DIR", default="outputs")
SEARCH_CACHE_TTL_SECONDS = int(get_env("SEARCH_CACHE_TTL_SECONDS", default="3600"))

# Deep Search Skill (S2)
SKILL_DEEP_SEARCH_ENABLED = get_env("SKILL_DEEP_SEARCH_ENABLED", default="false").lower() == "true"
DEEP_SEARCH_DOMAINS = get_env("DEEP_SEARCH_DOMAINS", default="docs.python.org,arxiv.org")
DEEP_SEARCH_MAX_PAGES_PER_DOMAIN = int(get_env("DEEP_SEARCH_MAX_PAGES_PER_DOMAIN", default="50"))
DEEP_SEARCH_CACHE_TTL_SECONDS = int(get_env("DEEP_SEARCH_CACHE_TTL_SECONDS", default="86400"))
QDRANT_URL = get_env("QDRANT_URL", default="http://localhost:6333")
EMBEDDING_MODEL = get_env("EMBEDDING_MODEL", default="sentence-transformers/all-MiniLM-L6-v2")

# Garante que os diretórios necessários existem
Path(SQLITE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

try:
    Path(OUTPUT_BASE_DIR).mkdir(parents=True, exist_ok=True)
except PermissionError:
    # Em containers, o volume pode já estar montado mas sem permissão de mkdir no root do volume
    if not Path(OUTPUT_BASE_DIR).exists():
        raise
