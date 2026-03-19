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
GENAI_API_KEY = get_env("GENAI_API_KEY", required=True)

# Variáveis opcionais com valores padrão
DEFAULT_MODEL = get_env("DEFAULT_MODEL", default="gemini-3-flash-preview")
AGENT_TIMEOUT_SECONDS = int(get_env("AGENT_TIMEOUT_SECONDS", default="120"))
SQLITE_DB_PATH = get_env("SQLITE_DB_PATH", default="store/geminiclaw.db")

# Garante que o diretório do banco de dados existe
db_dir = Path(SQLITE_DB_PATH).parent
if not db_dir.exists():
    db_dir.mkdir(parents=True, exist_ok=True)
