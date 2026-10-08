"""Roteador de provedores LLM por papel de agente (ADR 017).

``ModelRouter.get_provider(papel)`` lê o **mapa resolvido da sessão** (ver ``src/llm/session.py``):
nenhuma variável de ambiente é consultada aqui. ``get_provider()`` sem papel delega ao
``researcher``. A dica de modelo do plano chega em ``model`` no formato ``provedor/modelo`` e só é
aceita se o roteador a validar (catálogo, requisitos, política e disponibilidade).
"""

from typing import Dict, Optional

# Import com efeito colateral: popula o registro de provedores (src.llm.providers.__init__).
import src.llm.providers  # noqa: F401
from src.egress.gate import Destination, GatedProvider
from src.llm.base import LLMProvider
from src.llm.catalog import split_model_id
from src.llm.registry import create_provider
from src.llm.session import clear_catalog_cache, get_session_routing
from src.logger import get_logger

logger = get_logger(__name__)

# Cache de instâncias de provedores indexado por (provider, model)
_provider_cache: Dict[tuple[str, str], LLMProvider] = {}
# Provedores envolvidos pela camada de saída, por (provider, model, papel): o destino depende do papel.
_gated_cache: Dict[tuple[str, str, str], GatedProvider] = {}


def _destination_for(papel: str, model_id: str) -> Destination:
    """Destino de um envio ao modelo ``model_id`` no papel ``papel``, lido do catálogo da sessão corrente.

    Modelo fora do catálogo: o lado seguro (fora do nó, sem dados brutos).
    """
    routing = get_session_routing()
    provider_name, model = split_model_id(model_id)
    entry = routing.catalogo.modelos.get(model_id)
    if entry is None:
        return Destination(
            canal="llm", provedor=provider_name, modelo=model, trust="third_party", localidade="fora_do_no",
            aceita_dados_brutos=False, papel=papel,
        )
    return Destination(
        canal="llm",
        provedor=entry.provedor,
        modelo=entry.modelo,
        trust=entry.trust,
        localidade=entry.localidade,
        aceita_dados_brutos=entry.aceita_dados_brutos,
        papel=papel,
        versao_efetiva=routing.versions.current(model_id),
    )


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
        papel = resolution.papel

        gated_key = (provider_name, effective_model, papel)
        if gated_key in _gated_cache:
            return _gated_cache[gated_key]

        provider_instance = _provider_cache.get(cache_key)
        if provider_instance is None:
            provider_instance = create_provider(
                provider_name, effective_model, fallback_model=routing.fallback_for(effective_id)
            )
            logger.info(
                "ModelRouter instanciou provedor",
                extra={
                    "role": papel,
                    "provider": provider_name,
                    "model": effective_model,
                    "origem": resolution.origem,
                },
            )
            _provider_cache[cache_key] = provider_instance
        gated = GatedProvider(provider_instance, lambda: _destination_for(papel, effective_id))
        _gated_cache[gated_key] = gated
        return gated

    @classmethod
    def clear_cache(cls) -> None:
        """Limpa o cache de provedores e o do catálogo (útil para testes unitários)."""
        _provider_cache.clear()
        _gated_cache.clear()
        clear_catalog_cache()
