from typing import Callable, Optional

from src.llm.base import LLMProvider

_RESOLVER_MISSING = "resolvedor de provedor não registrado: a partida deve registrar o roteador com filtro de egresso"
_PROVIDER_UNGATED = "provedor sem filtro de egresso: o resolvedor registrado deve devolver o provedor do roteador"

# Função registrada na partida pela camada de composição (``src.egress.routing.install_provider_resolver``).
_resolver: Optional[Callable[[Optional[str]], LLMProvider]] = None


class ProviderResolverError(RuntimeError):
    """O resolvedor de provedor não está registrado ou devolveu um provedor sem o filtro de egresso."""


def set_provider_resolver(resolver: Optional[Callable[[Optional[str]], LLMProvider]]) -> None:
    """Registra a função que obtém o provedor de um papel (``None`` desfaz o registro)."""
    global _resolver
    _resolver = resolver


def get_provider() -> LLMProvider:
    """Provedor do papel ``researcher``, obtido pelo resolvedor registrado na partida (ADR 017 §10).

    Mantido por compatibilidade com chamadores sem papel (laço de agente sem provedor
    explícito, triagem). Não há mais singleton nem leitura de ``LLM_PROVIDER``/``LLM_MODEL``.

    Raises:
        ProviderResolverError: Sem resolvedor registrado, ou o resolvedor devolveu um provedor que não está
            envolvido pelo filtro de egresso (ADR 019): nesse caso o provedor não é devolvido.
    """
    if _resolver is None:
        raise ProviderResolverError(_RESOLVER_MISSING)
    provider = _resolver(None)
    if provider.unwrap() is provider:
        raise ProviderResolverError(_PROVIDER_UNGATED)
    return provider
