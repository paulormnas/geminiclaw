"""Registro único de provedores LLM (ADR 011, V16).

Cada provedor se registra por nome com uma fábrica. A seleção global
(`src.llm.factory.get_provider`) e o roteamento por papel
(`src.model_router.ModelRouter`) consultam este mesmo registro — adicionar um
provedor passa a significar implementar `LLMProvider` e chamar
`register_provider`, sem editar nenhum dos dois consumidores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict

from src import config
from src.llm.base import LLMProvider


@dataclass(frozen=True)
class ProviderSettings:
    """Parâmetros resolvidos para instanciar um provedor.

    Args:
        name: Nome canônico do provedor (após resolução de alias).
        model: Nome do modelo a usar.
        base_url: URL base do servidor, quando aplicável.
        api_key: Chave de API, quando aplicável. Nunca aparece em `repr()`
            nem em logs — ver `Scenario: Chave de API não vaza` no spec.
    """

    name: str
    model: str
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)


ProviderFactory = Callable[[ProviderSettings], LLMProvider]

# Nome canônico -> variável de ambiente, apenas quando diverge da convenção
# <PROVIDER>_BASE_URL / <PROVIDER>_API_KEY (nome já consagrado no ecossistema
# daquele provedor). Ver `openspec/changes/v16-provider-registry/design.md`.
_BASE_URL_ENV_OVERRIDES: Dict[str, str] = {
    "openai_compatible": "OPENAI_BASE_URL",
    "openai": "OPENAI_BASE_URL",
}
_API_KEY_ENV_OVERRIDES: Dict[str, str] = {
    "google": "GEMINI_API_KEY",
    "openai_compatible": "OPENAI_API_KEY",
    "openai": "OPENAI_API_KEY",
}

_registry: Dict[str, ProviderFactory] = {}
_aliases: Dict[str, str] = {}


def register_provider(
    name: str,
    factory: ProviderFactory,
    aliases: tuple[str, ...] = (),
) -> None:
    """Registra a fábrica de um provedor sob um nome canônico e aliases.

    Args:
        name: Nome canônico do provedor (ex: 'ollama').
        factory: Callable que recebe `ProviderSettings` e retorna `LLMProvider`.
            Deve importar o módulo do provedor internamente (import
            preguiçoso), para que um pacote opcional ausente só quebre a
            criação daquele provedor específico.
        aliases: Nomes alternativos que resolvem para o mesmo provedor
            (ex: 'local' -> 'ollama').
    """
    canonical = name.strip().lower()
    _registry[canonical] = factory
    for alias in aliases:
        _aliases[alias.strip().lower()] = canonical


def available_providers() -> list[str]:
    """Lista os nomes canônicos de todos os provedores registrados."""
    return sorted(_registry.keys())


def _resolve_canonical_name(name: str) -> str:
    normalized = name.strip().lower()
    return _aliases.get(normalized, normalized)


def _resolve_base_url(canonical_name: str) -> str | None:
    # Lido do módulo `config` (não diretamente do ambiente): `config.py` é a fonte
    # de verdade já resolvida na inicialização (ADR de configuração explícita),
    # e é o que os testes patcham (`patch("src.config.OLLAMA_BASE_URL", ...)`).
    # Um provedor novo que não declare sua variável em `config.py` simplesmente
    # resolve para `None` aqui — só `factory.py`/`model_router.py` são
    # protegidos de alteração pelo spec, não `config.py`.
    env_name = _BASE_URL_ENV_OVERRIDES.get(canonical_name, f"{canonical_name.upper()}_BASE_URL")
    return getattr(config, env_name, None)


def _resolve_api_key(canonical_name: str) -> str | None:
    env_name = _API_KEY_ENV_OVERRIDES.get(canonical_name, f"{canonical_name.upper()}_API_KEY")
    return getattr(config, env_name, None)


def create_provider(name: str, model: str) -> LLMProvider:
    """Cria uma instância do provedor pedido, resolvendo `base_url`/`api_key`.

    Args:
        name: Nome canônico ou alias do provedor.
        model: Nome do modelo a usar.

    Returns:
        Instância de `LLMProvider` criada pela fábrica registrada.

    Raises:
        ValueError: Se `name` (após resolução de alias) não estiver registrado.
    """
    canonical = _resolve_canonical_name(name)
    factory = _registry.get(canonical)
    if factory is None:
        available = ", ".join(available_providers())
        raise ValueError(f"Provedor '{name}' desconhecido. Provedores disponíveis: {available}.")

    settings = ProviderSettings(
        name=canonical,
        model=model,
        base_url=_resolve_base_url(canonical),
        api_key=_resolve_api_key(canonical),
    )
    return factory(settings)
