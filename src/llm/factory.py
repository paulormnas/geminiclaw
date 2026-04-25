import os
from src.llm.base import LLMProvider

_provider_instance: LLMProvider | None = None

def get_provider() -> LLMProvider:
    """Retorna uma instância singleton do provedor configurado."""
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    # LLM_PROVIDER pode ser: google | ollama | local
    provider_type = os.getenv("LLM_PROVIDER", "google").lower()

    if provider_type in ("local", "ollama"):
        from src.llm.providers.ollama import OllamaProvider
        _provider_instance = OllamaProvider(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=os.getenv("LLM_MODEL", os.getenv("DEFAULT_MODEL", "qwen3.5:4b")),
        )
    elif provider_type == "google":
        from src.llm.providers.google import GoogleProvider
        _provider_instance = GoogleProvider()
    else:
        # Fallback para google se não especificado corretamente mas houver chave
        if os.getenv("GEMINI_API_KEY"):
            from src.llm.providers.google import GoogleProvider
            _provider_instance = GoogleProvider()
        else:
            raise ValueError(
                f"LLM_PROVIDER inválido: '{provider_type}'. Use: google | ollama | local"
            )

    return _provider_instance
