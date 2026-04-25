from src.llm.base import LLMProvider
from src import config

_provider_instance: LLMProvider | None = None

def get_provider() -> LLMProvider:
    """Retorna uma instância singleton do provedor configurado."""
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    # LLM_PROVIDER pode ser: google | ollama | local
    provider_type = config.LLM_PROVIDER.lower()

    if provider_type in ("local", "ollama"):
        from src.llm.providers.ollama import OllamaProvider
        _provider_instance = OllamaProvider(
            base_url=config.OLLAMA_BASE_URL,
            model=config.LLM_MODEL,
        )
    elif provider_type == "google":
        from src.llm.providers.google import GoogleProvider
        _provider_instance = GoogleProvider(
            api_key=config.GEMINI_API_KEY,
            model=config.LLM_MODEL,
        )
    else:
        raise ValueError(
            f"LLM_PROVIDER inválido: '{provider_type}'. Use: google | ollama | local"
        )

    return _provider_instance
