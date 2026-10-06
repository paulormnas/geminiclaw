"""Disponibilidade de provedores e modelos para o roteador (ADR 017 §4, §9).

Um ``(provedor, modelo)`` está disponível na sessão quando, nesta ordem:

1. há credencial (Google, Anthropic, OpenAI) ou endpoint (Ollama, ``openai_compatible``);
2. o provedor está na lista de permissão ``LLM_PROVIDER_PRIORITY`` (a ordem da lista não muda a
   preferência do papel; só exclui o que não está nela);
3. o health check passa dentro de ``LLM_HEALTH_CHECK_TIMEOUT_SECONDS``. O check **não gera texto**
   e, para provedores locais, confirma que o modelo está instalado.

O resultado é calculado uma vez por sessão (``SessionRouting`` o guarda) e os checks rodam em
paralelo. Erros são reduzidos a ``classe da exceção + código HTTP``: corpo de resposta e
cabeçalhos (que podem conter a chave) nunca chegam ao log nem ao motivo.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from src.llm import registry
from src.llm.base import LLMProvider
from src.llm.catalog import Catalog
from src.logger import get_logger

logger = get_logger(__name__)

_NEEDS_API_KEY = {"google", "anthropic", "openai"}
_NEEDS_BASE_URL = {"ollama", "openai_compatible"}

PROFILE_PRIORITY: dict[str, tuple[str, ...]] = {
    "pi5": ("ollama", "openai_compatible", "google", "anthropic", "openai"),
    "default": ("google", "anthropic", "openai", "ollama", "openai_compatible"),
}

# Motivos de indisponibilidade (usados também na auditoria dos descartados).
MOTIVO_SEM_CREDENCIAL = "sem_credencial"
MOTIVO_SEM_ENDPOINT = "sem_endpoint"
MOTIVO_FORA_DA_LISTA = "provedor_fora_da_lista_de_permissao"
MOTIVO_NAO_VERIFICADO = "nao_verificado"


@dataclass(frozen=True)
class Availability:
    """Resultado da disponibilidade de um modelo (``motivo`` é ``None`` quando disponível)."""

    ok: bool
    motivo: str | None = None


ProviderFactory = Callable[[str, str], LLMProvider]


def default_provider_factory(provider: str, model: str) -> LLMProvider:
    """Instancia o provedor real para o health check (seam substituível em testes)."""
    return registry.create_provider(provider, model)


def sanitize_error(exc: BaseException) -> str:
    """Reduz um erro a ``classe`` + código HTTP, sem corpo de resposta nem cabeçalhos."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    name = type(exc).__name__
    return f"{name}:{status}" if isinstance(status, int) else name


def parse_priority(raw: str | None, profile: str) -> tuple[str, ...]:
    """Lista de permissão: ``LLM_PROVIDER_PRIORITY`` ou o padrão do perfil de deployment."""
    names = [item.strip() for item in (raw or "").split(",") if item.strip()]
    if not names:
        return PROFILE_PRIORITY.get(profile, PROFILE_PRIORITY["default"])
    return tuple(registry.canonical_name(name) for name in names)


def _credential_reason(provider: str) -> str | None:
    if provider in _NEEDS_API_KEY and not registry.has_api_key(provider):
        return MOTIVO_SEM_CREDENCIAL
    if provider in _NEEDS_BASE_URL and not registry.resolve_base_url(provider):
        return MOTIVO_SEM_ENDPOINT
    return None


async def _close_client(instance: LLMProvider) -> None:
    """Fecha, sem falhar, o cliente HTTP da instância descartável do health check."""
    client = getattr(instance, "_client", None)
    for name in ("aclose", "close"):
        closer = getattr(client, name, None)
        if callable(closer):
            try:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001 — limpeza best-effort
                pass
            return


async def _check_one(
    provider: str, model: str, factory: ProviderFactory, timeout: float
) -> Availability:
    instance: LLMProvider | None = None
    try:
        instance = factory(provider, model)
        reason = await asyncio.wait_for(instance.check_availability(), timeout=timeout)
    except asyncio.TimeoutError:
        return Availability(False, f"health_check_timeout:{timeout:g}s")
    except Exception as exc:  # noqa: BLE001 — qualquer falha vira motivo sanitizado
        reduced = sanitize_error(exc)
        logger.warning("Health check falhou", extra={"provider": provider, "model": model, "error": reduced})
        return Availability(False, f"health_check_falhou:{reduced}")
    finally:
        if instance is not None:
            await _close_client(instance)
    return Availability(True) if reason is None else Availability(False, reason)


def static_availability(
    catalog: Catalog, ids: Iterable[str] | None = None, *, priority: tuple[str, ...]
) -> tuple[dict[str, Availability], dict[str, tuple[str, str]]]:
    """Passos 1 e 2 (credencial/endpoint e lista de permissão), sem rede.

    Returns:
        ``(resultados, pendentes)``: ``resultados`` já decididos (indisponíveis, ou disponíveis
        quando não há check a fazer) e ``pendentes`` (``id`` -> ``(provedor, modelo)``) que ainda
        precisam do health check.
    """
    if ids is None:
        ids = {model_id for spec in catalog.papeis.values() for model_id in spec.preferencia}
    results: dict[str, Availability] = {}
    pending: dict[str, tuple[str, str]] = {}
    for model_id in sorted(set(ids)):
        entry = catalog.modelos.get(model_id)
        if entry is None:
            results[model_id] = Availability(False, "fora_do_catalogo")
            continue
        provider = registry.canonical_name(entry.provedor)
        reason = _credential_reason(provider)
        if reason is None and provider not in priority:
            reason = MOTIVO_FORA_DA_LISTA
        if reason is not None:
            results[model_id] = Availability(False, reason)
        else:
            pending[model_id] = (provider, entry.modelo)
    return results, pending


async def compute_availability(
    catalog: Catalog,
    ids: Iterable[str] | None = None,
    *,
    priority: tuple[str, ...],
    timeout: float,
    provider_factory: ProviderFactory | None = None,
) -> dict[str, Availability]:
    """Calcula a disponibilidade de cada modelo pedido (padrão: todos os da ``preferencia``).

    Args:
        catalog: Catálogo efetivo.
        ids: ``id`` a verificar; o padrão é a união das preferências de todos os papéis.
        priority: Lista de permissão de provedores.
        timeout: Timeout (s) de cada health check.
        provider_factory: Cria a instância usada no check; padrão ``default_provider_factory``.

    Returns:
        Mapa ``id`` -> ``Availability``. Os checks rodam em paralelo.
    """
    factory = provider_factory or default_provider_factory
    results, pending = static_availability(catalog, ids, priority=priority)
    if pending:
        checked = await asyncio.gather(
            *(_check_one(provider, model, factory, timeout) for provider, model in pending.values())
        )
        results.update(zip(pending.keys(), checked))
    return results


def availability_view(results: Mapping[str, Availability]) -> dict[str, str | None]:
    """Resumo ``id`` -> motivo (``None`` = disponível), para auditoria e testes."""
    return {model_id: (None if item.ok else item.motivo) for model_id, item in results.items()}

