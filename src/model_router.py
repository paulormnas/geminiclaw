"""Factory e roteador de provedores LLM por papel de agente (Roadmap V14.1).

Implementa o Model Router para selecionar dinamicamente o provedor e modelo
adequados para cada papel arquitetural (Researcher, Validator, Developer).
"""

from typing import Dict, Optional
from src.llm.base import LLMProvider
from src.model_config import get_role_model_config, RoleModelConfig
from src import config
from src.logger import get_logger

logger = get_logger(__name__)

# Cache de instâncias de provedores indexado por (provider, model)
_provider_cache: Dict[tuple[str, str], LLMProvider] = {}


class ModelRouter:
    """Roteador de modelos e provedores LLM por papel."""

    @classmethod
    def get_provider(cls, role: Optional[str] = None) -> LLMProvider:
        """Retorna uma instância de LLMProvider configurada para o papel.

        Args:
            role: Nome do papel ('researcher', 'validator', 'developer').
                  Se None, retorna o provedor padrão do sistema (compatibilidade retroativa).

        Returns:
            Instância de LLMProvider configurada.

        Raises:
            ValueError: Se o papel ou o provedor configurado for inválido.
        """
        if role is None:
            # Fallback para o provedor singleton padrão (V18/retrocompatibilidade)
            from src.llm.factory import get_provider
            return get_provider()

        role_cfg: RoleModelConfig = get_role_model_config(role)
        cache_key = (role_cfg.provider.lower(), role_cfg.model)

        if cache_key in _provider_cache:
            return _provider_cache[cache_key]

        provider_type = role_cfg.provider.lower()
        provider_instance: LLMProvider

        if provider_type == "google":
            from src.llm.providers.google import GoogleProvider
            provider_instance = GoogleProvider(
                api_key=config.GEMINI_API_KEY,
                model=role_cfg.model,
            )
        elif provider_type in ("ollama", "local"):
            from src.llm.providers.ollama import OllamaProvider
            provider_instance = OllamaProvider(
                base_url=config.OLLAMA_BASE_URL,
                model=role_cfg.model,
            )
        else:
            raise ValueError(
                f"Provedor '{provider_type}' não suportado para o papel '{role}'. "
                "Use: google | ollama | local."
            )

        logger.info(
            "ModelRouter instanciou provedor",
            extra={
                "role": role_cfg.role,
                "provider": role_cfg.provider,
                "model": role_cfg.model,
            },
        )
        _provider_cache[cache_key] = provider_instance
        return provider_instance

    @classmethod
    def clear_cache(cls) -> None:
        """Limpa o cache de provedores (útil para testes unitários)."""
        _provider_cache.clear()
