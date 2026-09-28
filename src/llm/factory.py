# Import com efeito colateral: popula o registro de provedores (src.llm.providers.__init__).
import src.llm.providers  # noqa: F401
from src import config
from src.llm.base import LLMProvider
from src.llm.registry import create_provider

_provider_instance: LLMProvider | None = None


def get_provider() -> LLMProvider:
    """Retorna uma instância singleton do provedor configurado em `LLM_PROVIDER`."""
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    _provider_instance = create_provider(config.LLM_PROVIDER, config.LLM_MODEL)
    return _provider_instance
