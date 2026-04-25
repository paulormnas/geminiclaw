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

def get_env_bool(key: str, default: bool = False) -> bool:
    """Obtém uma variável de ambiente convertendo para booleano.
    
    Aceita 'true', '1', 't', 'y', 'yes' como True (case-insensitive).
    """
    value = os.environ.get(key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "t", "y", "yes")

# --- Configuração LLM (V18) ---

# Provedor e modelo — novos
LLM_PROVIDER = get_env("LLM_PROVIDER", default="google")
LLM_MODEL = get_env("LLM_MODEL") or get_env("DEFAULT_MODEL", default="gemini-3.1-pro-preview")
DEFAULT_MODEL = LLM_MODEL  # Retrocompatibilidade

# Configurações Ollama
OLLAMA_BASE_URL = get_env("OLLAMA_BASE_URL", default="http://localhost:11434")
OLLAMA_NUM_CTX = int(get_env("OLLAMA_NUM_CTX", default="4096"))
OLLAMA_ENABLE_THINKING = get_env("OLLAMA_ENABLE_THINKING", default="false").lower() == "true"

# Google API key: obrigatória APENAS quando provider for google
GEMINI_API_KEY = get_env(
    "GEMINI_API_KEY",
    required=(LLM_PROVIDER == "google"),
)

# Rate limiting — ler nova variável com fallback para a antiga (retrocompatibilidade)
LLM_REQUESTS_PER_MINUTE = int(
    get_env("LLM_REQUESTS_PER_MINUTE")
    or get_env("GEMINI_REQUESTS_PER_MINUTE", default="15")
)
LLM_RATE_LIMIT_COOLDOWN_SECONDS = int(
    get_env("LLM_RATE_LIMIT_COOLDOWN_SECONDS")
    or get_env("GEMINI_RATE_LIMIT_COOLDOWN_SECONDS", default="30")
)
GEMINI_REQUESTS_PER_MINUTE = LLM_REQUESTS_PER_MINUTE  # Retrocompatibilidade
GEMINI_RATE_LIMIT_COOLDOWN_SECONDS = LLM_RATE_LIMIT_COOLDOWN_SECONDS  # Retrocompatibilidade

# --- Perfil de Deployment (V18.1) ---
DEPLOYMENT_PROFILE = get_env("DEPLOYMENT_PROFILE", default="default")

# Validação e rigor (Etapa V22)
STRICT_VALIDATION = get_env_bool("STRICT_VALIDATION", default=True)
if DEPLOYMENT_PROFILE == "pi5" or LLM_PROVIDER == "ollama":
    STRICT_VALIDATION = get_env_bool("STRICT_VALIDATION", default=False)

if DEPLOYMENT_PROFILE == "pi5":
    MAX_SUBTASKS_PER_TASK = int(get_env("MAX_SUBTASKS_PER_TASK", default="5"))
    MAX_CONCURRENT_AGENTS = int(get_env("MAX_CONCURRENT_AGENTS", default="2"))
    AGENT_TIMEOUT_SECONDS = int(get_env("AGENT_TIMEOUT_SECONDS", default="300"))
    # No Pi 5, o Ollama local é o padrão se não especificado
    if not os.environ.get("LLM_PROVIDER"):
        LLM_PROVIDER = "ollama"
else:
    MAX_SUBTASKS_PER_TASK = int(get_env("MAX_SUBTASKS_PER_TASK", default="10"))
    MAX_CONCURRENT_AGENTS = int(get_env("MAX_CONCURRENT_AGENTS", default="3"))
    AGENT_TIMEOUT_SECONDS = int(get_env("AGENT_TIMEOUT_SECONDS", default="120"))

# --- Outras Configurações ---
SQLITE_DB_PATH = get_env("SQLITE_DB_PATH", default="store/geminiclaw.db")
OUTPUT_BASE_DIR = get_env("OUTPUT_BASE_DIR", default="outputs")
LOGS_BASE_DIR = get_env("LOGS_BASE_DIR", default="logs")
SEARCH_CACHE_TTL_SECONDS = int(get_env("SEARCH_CACHE_TTL_SECONDS", default="3600"))

# Deep Search Skill (S2)
SKILL_DEEP_SEARCH_ENABLED = get_env("SKILL_DEEP_SEARCH_ENABLED", default="false").lower() == "true"
DEEP_SEARCH_DOMAINS = get_env("DEEP_SEARCH_DOMAINS", default="docs.python.org,arxiv.org")
DEEP_SEARCH_MAX_PAGES_PER_DOMAIN = int(get_env("DEEP_SEARCH_MAX_PAGES_PER_DOMAIN", default="50"))
DEEP_SEARCH_CACHE_TTL_SECONDS = int(get_env("DEEP_SEARCH_CACHE_TTL_SECONDS", default="86400"))
QDRANT_URL = get_env("QDRANT_URL", default="http://localhost:6333")
EMBEDDING_MODEL = get_env("EMBEDDING_MODEL", default="sentence-transformers/all-MiniLM-L6-v2")

# Web Reader Skill (S5)
SKILL_WEB_READER_ENABLED = get_env("SKILL_WEB_READER_ENABLED", default="false").lower() == "true"

# Health Monitoring (S7)
HEALTH_CHECK_ENABLED = get_env("HEALTH_CHECK_ENABLED", default="true").lower() == "true"
PI_TEMPERATURE_LIMIT = float(get_env("PI_TEMPERATURE_LIMIT", default="75.0"))
PI_MIN_AVAILABLE_MEMORY_MB = float(get_env("PI_MIN_AVAILABLE_MEMORY_MB", default="512.0"))

# Garante que os diretórios necessários existem (com tolerância a containers)
try:
    Path(SQLITE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
except PermissionError:
    if not Path(SQLITE_DB_PATH).parent.exists():
        raise

for directory in [OUTPUT_BASE_DIR, LOGS_BASE_DIR]:
    try:
        # Se for um caminho absoluto começando com /, assumimos que é um volume gerenciado
        # e que o orquestrador já garantiu sua existência e permissões.
        if directory.startswith("/"):
             if not Path(directory).exists():
                 logger.warning(f"Diretório de volume {directory} não encontrado no container.")
             continue
             
        Path(directory).mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Em containers, o volume pode já estar montado mas sem permissão de mkdir no root do volume
        if not Path(directory).exists():
            raise
