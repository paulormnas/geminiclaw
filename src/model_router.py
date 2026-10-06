"""Roteador de provedores LLM por papel de agente (ADR 017).

``ModelRouter.get_provider(papel)`` lê o **mapa resolvido da sessão** (ver ``src/llm/session.py``):
nenhuma variável de ambiente é consultada aqui. ``get_provider()`` sem papel delega ao
``researcher``. A dica de modelo do plano chega em ``model`` no formato ``provedor/modelo`` e só é
aceita se o roteador a validar (catálogo, requisitos, política e disponibilidade).
"""

from typing import Dict, Optional

# Import com efeito colateral: popula o registro de provedores (src.llm.providers.__init__).
import src.llm.providers  # noqa: F401
from src.llm.base import LLMProvider
from src.llm.catalog import split_model_id
from src.llm.registry import create_provider
from src.llm.session import clear_catalog_cache, get_session_routing
from src.logger import get_logger

logger = get_logger(__name__)

# Cache de instâncias de provedores indexado por (provider, model)
_provider_cache: Dict[tuple[str, str], LLMProvider] = {}


class ModelRouter:
    """Roteador de modelos e provedores LLM por papel."""

    @classmethod
    def get_provider(cls, role: Optional[str] = None, model: Optional[str] = None) -> LLMProvider:
        """Retorna uma instância de LLMProvider para o papel, conforme o mapa resolvido da sessão.

        Args:
            role: Nome do papel (``researcher``, ``developer``, ``validator``, ``reviewer``,
                ``summarizer``, ``base``; ``planner`` é alias de ``researcher``). ``None``
                delega para ``researcher``.
            model: Dica ``provedor/modelo`` (ex.: ``AgentTask.preferred_model`` do plano).
                É validada pelo roteador; se não valer, o modelo resolvido do papel é usado.

        Returns:
            Instância de LLMProvider configurada.

        Raises:
            ValueError: Se o papel for desconhecido.
        """
        routing = get_session_routing()
        resolution = routing.resolution(role or "researcher")
        effective_id = routing.apply_hint(resolution.papel, model)
        provider_name, effective_model = split_model_id(effective_id)
        cache_key = (provider_name, effective_model)

        if cache_key in _provider_cache:
            return _provider_cache[cache_key]

        provider_instance = create_provider(
            provider_name, effective_model, fallback_model=routing.fallback_for(effective_id)
        )

        logger.info(
            "ModelRouter instanciou provedor",
            extra={
                "role": resolution.papel,
                "provider": provider_name,
                "model": effective_model,
                "origem": resolution.origem,
            },
        )
        _provider_cache[cache_key] = provider_instance
        return provider_instance

    @classmethod
    def clear_cache(cls) -> None:
        """Limpa o cache de provedores e o do catálogo (útil para testes unitários)."""
        _provider_cache.clear()
        clear_catalog_cache()
