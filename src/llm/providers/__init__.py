"""Provedores de LLM para o GeminiClaw — registro com imports preguiçosos.

Importar este pacote popula o registro em `src.llm.registry`. Cada fábrica
importa o módulo do provedor apenas quando chamada, para que um pacote
opcional ausente (ex: `google-genai`) só quebre a criação daquele provedor
específico, nunca a importação do pacote inteiro.
"""

from src.llm.registry import ProviderSettings, register_provider


def _create_ollama(settings: ProviderSettings):
    from src.llm.providers.ollama import OllamaProvider

    return OllamaProvider(base_url=settings.base_url, model=settings.model)


def _create_google(settings: ProviderSettings):
    try:
        from src.llm.providers.google import GoogleProvider
    except ImportError as exc:
        raise ValueError(
            "Provedor 'google' requer o pacote 'google-genai'. "
            "Instale com: uv sync --extra google"
        ) from exc

    return GoogleProvider(
        api_key=settings.api_key,
        model=settings.model,
        fallback_model=settings.fallback_model,
    )


def _create_openai_compatible(settings: ProviderSettings):
    from src.llm.providers.openai_compatible import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
    )


def _create_openai(settings: ProviderSettings):
    from src import config
    from src.llm.providers.openai import OpenAIProvider

    return OpenAIProvider(
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url,
        reasoning_effort=config.OPENAI_REASONING_EFFORT,
    )


def _create_anthropic(settings: ProviderSettings):
    try:
        from src.llm.providers.anthropic import AnthropicProvider
    except ImportError as exc:
        raise ValueError(
            "Provedor 'anthropic' requer o pacote 'anthropic'. "
            "Instale com: uv sync --extra anthropic"
        ) from exc

    from src import config

    return AnthropicProvider(
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url,
        effort=config.ANTHROPIC_EFFORT,
        refusal_fallback=config.ANTHROPIC_REFUSAL_FALLBACK,
    )


register_provider("ollama", _create_ollama, aliases=("local",))
register_provider("google", _create_google)
register_provider("openai_compatible", _create_openai_compatible)
register_provider("openai", _create_openai)
register_provider("anthropic", _create_anthropic)
