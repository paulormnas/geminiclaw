"""Registro único de provedores LLM (ADR 011, V16).

Cada provedor se registra por nome com uma fábrica. O roteamento por papel
(`src.model_router.ModelRouter`) e o catálogo (`src.llm.catalog`) consultam este mesmo registro — adicionar um
provedor passa a significar implementar `LLMProvider` e chamar
`register_provider`, sem editar nenhum dos dois consumidores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict

from src import config
from src.llm.base import LLMProvider
from src.llm.endpoints import validate_remote_endpoint


@dataclass(frozen=True)
class ProviderSettings:
    """Parâmetros resolvidos para instanciar um provedor.

    Args:
        name: Nome canônico do provedor (após resolução de alias).
        model: Nome do modelo a usar.
        base_url: URL base do servidor, quando aplicável.
        api_key: Chave de API, quando aplicável. Nunca aparece em `repr()`
            nem em logs — ver `Scenario: Chave de API não vaza` no spec.
        fallback_model: Modelo de contingência para limite de requisições, já validado pelo
            roteador (catálogo, `trust` e requisitos do papel); `None` desliga o fallback.
    """

    name: str
    model: str
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    fallback_model: str | None = None


ProviderFactory = Callable[[ProviderSettings], LLMProvider]

# Nome canônico -> variável de ambiente, apenas quando diverge da convenção
# <PROVIDER>_BASE_URL / <PROVIDER>_API_KEY (nome já consagrado no ecossistema
# daquele provedor). Ver `openspec/changes/v16-provider-registry/design.md`.
#
# ADR 017 §8: `openai` e `openai_compatible` NÃO compartilham variáveis (a chave real da OpenAI nunca
# pode ir a um servidor compatível): `openai` usa OPENAI_API_KEY/OPENAI_BASE_URL (convenção do
# ecossistema OpenAI) e `openai_compatible` usa OPENAI_COMPATIBLE_API_KEY/OPENAI_COMPATIBLE_BASE_URL.
_BASE_URL_ENV_OVERRIDES: Dict[str, str] = {
    "openai": "OPENAI_BASE_URL",
}
_API_KEY_ENV_OVERRIDES: Dict[str, str] = {
    "google": "GEMINI_API_KEY",
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


def base_url_env_name(name: str) -> str:
    """Nome da variável de ambiente do endpoint do provedor."""
    canonical = _resolve_canonical_name(name)
    return _BASE_URL_ENV_OVERRIDES.get(canonical, f"{canonical.upper()}_BASE_URL")


def _resolve_api_key(canonical_name: str) -> str | None:
    env_name = _API_KEY_ENV_OVERRIDES.get(canonical_name, f"{canonical_name.upper()}_API_KEY")
    return getattr(config, env_name, None)


def canonical_name(name: str) -> str:
    """Nome canônico de um provedor (resolve aliases como ``local`` -> ``ollama``)."""
    return _resolve_canonical_name(name)


def resolve_base_url(name: str) -> str | None:
    """Endpoint configurado para o provedor, ou ``None`` se não houver."""
    return _resolve_base_url(_resolve_canonical_name(name))


def has_api_key(name: str) -> bool:
    """Informa se há chave de API configurada para o provedor (sem expor o valor)."""
    return bool(_resolve_api_key(_resolve_canonical_name(name)))


def create_provider(name: str, model: str, fallback_model: str | None = None) -> LLMProvider:
    """Cria uma instância do provedor pedido, resolvendo `base_url`/`api_key`.

    Args:
        name: Nome canônico ou alias do provedor.
        model: Nome do modelo a usar.
        fallback_model: Modelo de contingência já validado pelo roteador (ver `ProviderSettings`).

    Returns:
        Instância de `LLMProvider` criada pela fábrica registrada.

    Raises:
        ValueError: Se `name` (após resolução de alias) não estiver registrado.
        EndpointError: Se o endpoint configurado é remoto e não usa https.
    """
    canonical = _resolve_canonical_name(name)
    factory = _registry.get(canonical)
    if factory is None:
        available = ", ".join(available_providers())
        raise ValueError(f"Provedor '{name}' desconhecido. Provedores disponíveis: {available}.")

    base_url = _resolve_base_url(canonical)
    if base_url:
        # Defesa em profundidade: a chave só vai a endpoint local, privado ou https.
        validate_remote_endpoint(canonical, base_url, base_url_env_name(canonical))

    settings = ProviderSettings(
        name=canonical,
        model=model,
        base_url=base_url,
        api_key=_resolve_api_key(canonical),
        fallback_model=fallback_model,
    )
    return factory(settings)
