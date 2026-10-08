"""Mapa resolvido da sessão: catálogo + disponibilidade + política -> modelo de cada papel.

A sessão resolve todos os papéis **uma vez**, antes do banner e da primeira chamada de LLM
(ADR 017 §6, §10), e não troca o modelo de um papel durante a execução. O mapa fica num
``ContextVar`` definido pelo orquestrador e é lido por ``ModelRouter.get_provider``. Fora de uma
sessão (testes, CLI auxiliar) o mesmo mapa é calculado na hora, **sem health check** (só
credencial/endpoint e lista de permissão), para não fazer rede em chamadas síncronas.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from src import config
from src.llm import registry
from src.llm.availability import (
    Availability,
    ProviderFactory,
    compute_availability,
    parse_priority,
    static_availability,
)
from src.llm.catalog import Catalog, load_catalog, split_model_id
from src.llm.routing import (
    POLICY_SELF_HOSTED,
    ROUTING_STRICT,
    Pin,
    RoleResolution,
    is_eligible,
    read_pins,
    resolve_session,
    validate_hint,
    validate_policy,
    validate_routing_mode,
)
from src.llm.versions import VersionTracker
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SessionRouting:
    """Mapa resolvido da sessão (imutável)."""

    politica: str
    modo: str
    catalogo: Catalog
    papeis: Mapping[str, RoleResolution]
    disponiveis: Mapping[str, Availability]
    # Versão efetiva por modelo e eventos de troca da sessão (v18.5-model-catalog-locality, design §4).
    versions: VersionTracker = field(default_factory=VersionTracker, compare=False, repr=False)

    def resolution(self, papel: str) -> RoleResolution:
        """Resolução do papel (aplica ``aliases_papel``; papel desconhecido -> ``ValueError``)."""
        return self.papeis[self.catalogo.normalize_role(papel)]

    def apply_hint(self, papel: str, hint: str | None) -> str:
        """``id`` efetivo do papel: a dica ``provedor/modelo`` do plano, se válida; senão o resolvido.

        A dica é texto gerado pelo LLM do planejamento (superfície de injeção de prompt): ela
        **nunca** sobrepõe um pin do pesquisador (``origem`` ``pin`` ou ``pin_legado``).
        """
        resolved = self.resolution(papel)
        if not hint or hint == resolved.id:
            return resolved.id
        if resolved.origem != "preferencia":
            logger.warning(
                "Dica de modelo do plano ignorada: o papel tem pin do pesquisador",
                extra={"hint": hint, "role": resolved.papel, "pin": resolved.id},
            )
            return resolved.id
        accepted = validate_hint(papel, hint, self.catalogo, self.disponiveis, self.politica, self.modo)
        return accepted or resolved.id

    def fallback_for(self, resolved_id: str) -> str | None:
        """Modelo de fallback do Google no 429, se aceito (ADR 017 §6, design §4).

        Só vale se estiver no catálogo com o mesmo ``trust`` do modelo principal, atender à política
        e aos requisitos de ao menos o mesmo uso; fica desligado em ``LLM_ROUTING=strict``.
        """
        configured = (config.GOOGLE_FALLBACK_MODEL or "").strip()
        provider, _ = split_model_id(resolved_id)
        if not configured or provider != "google":
            return None
        if self.modo == ROUTING_STRICT:
            return None
        fallback_id = f"google/{configured}"
        entry = self.catalogo.modelos.get(fallback_id)
        primary = self.catalogo.modelos.get(resolved_id)
        if (
            entry is None
            or primary is None
            or entry.trust != primary.trust
            # v18.5-egress-gate: o prompt já foi filtrado para o destino do principal; o fallback não pode ter
            # localidade nem aceitação de dados brutos diferentes (mandaria dado bruto a modelo que não o aceita).
            or entry.localidade != primary.localidade
            or entry.aceita_dados_brutos != primary.aceita_dados_brutos
        ):
            logger.warning(
                "GOOGLE_FALLBACK_MODEL ignorado: precisa estar no catálogo com o mesmo trust, localidade e dados brutos",
                extra={"fallback": fallback_id, "model": resolved_id},
            )
            return None
        requirements: dict[str, Any] = {}
        for role, resolution in self.papeis.items():
            if resolution.id == resolved_id:
                requirements.update(self.catalogo.papeis[role].requisitos)
        if not is_eligible(entry, requirements, self.politica):
            logger.warning(
                "GOOGLE_FALLBACK_MODEL ignorado: não atende aos requisitos do papel ou à política",
                extra={"fallback": fallback_id, "model": resolved_id},
            )
            return None
        return configured

    def payload(self) -> dict[str, Any]:
        """Conteúdo de ``payload["llm_routing"]`` (sem segredos)."""
        return {
            "politica": self.politica,
            "routing": self.modo,
            "catalogo": {
                "versao": self.catalogo.versao,
                "hash": self.catalogo.hash,
                "local": self.catalogo.local,
                "local_hash": self.catalogo.local_hash,
            },
            "papeis": {
                role: {"id": res.id, "trust": res.trust, "origem": res.origem}
                for role, res in self.papeis.items()
            },
        }

    def banner_lines(self) -> list[str]:
        """Linhas do banner: política, modo, catálogo e uma linha por papel."""
        width = max((len(role) for role in self.papeis), default=0)
        lines = [
            f"Modelos │ política: {self.politica} │ roteamento: {self.modo} │ "
            f"catálogo v{self.catalogo.versao} · {self.catalogo.short_hash}"
        ]
        for role, res in self.papeis.items():
            lines.append(f"{role.ljust(width)}  {res.id}  ({res.trust})")
        return lines


_current: ContextVar[SessionRouting | None] = ContextVar("geminiclaw_session_routing", default=None)
_catalog_cache: dict[tuple, Catalog] = {}


def bind_session_routing(routing: SessionRouting) -> Any:
    """Vincula o mapa resolvido ao contexto corrente (``asyncio`` o propaga às tarefas filhas)."""
    return _current.set(routing)


def current_session_routing() -> SessionRouting | None:
    """Mapa da sessão corrente, ou ``None`` fora de uma sessão."""
    return _current.get()


def _local_catalog_path() -> Path:
    from src.llm.catalog import DEFAULT_LOCAL_PATH

    return Path(config.LLM_CATALOG_LOCAL_PATH) if config.LLM_CATALOG_LOCAL_PATH else DEFAULT_LOCAL_PATH


def get_catalog() -> Catalog:
    """Catálogo efetivo, em cache por (provedores registrados, catálogo local, endpoint)."""
    local = _local_catalog_path()
    try:
        stamp = local.stat().st_mtime_ns if local.is_file() else None
    except OSError:
        stamp = None
    key = (tuple(registry.available_providers()), str(local), stamp, registry.resolve_base_url("openai_compatible"))
    catalog = _catalog_cache.get(key)
    if catalog is None:
        catalog = load_catalog()
        _catalog_cache.clear()
        _catalog_cache[key] = catalog
    return catalog


def clear_catalog_cache() -> None:
    """Limpa o cache do catálogo (uso em testes)."""
    _catalog_cache.clear()


def _relevant_ids(catalog: Catalog, pins: Mapping[str, Pin], politica: str) -> set[str]:
    """Modelos cuja disponibilidade importa: preferências e pins (sem checar o que a política já exclui)."""
    ids = {model_id for spec in catalog.papeis.values() for model_id in spec.preferencia}
    ids |= {pin.id for pin in pins.values()}
    if politica == POLICY_SELF_HOSTED:
        ids = {i for i in ids if i not in catalog.modelos or catalog.modelos[i].trust == "self_hosted"}
    return ids


def _resolve(
    catalog: Catalog,
    pins: Mapping[str, Pin],
    politica: str,
    modo: str,
    disponiveis: Mapping[str, Availability],
) -> SessionRouting:
    papeis = resolve_session(catalog, disponiveis, politica, pins, modo)
    return SessionRouting(
        politica, modo, catalog, papeis, dict(disponiveis), VersionTracker(strict=modo == ROUTING_STRICT)
    )


async def build_session_routing(
    cli_pins: Mapping[str, str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    provider_factory: ProviderFactory | None = None,
) -> SessionRouting:
    """Resolve todos os papéis para a sessão, com health check de cada ``(provedor, modelo)``.

    Args:
        cli_pins: Pins da CLI por papel (``{"researcher": "provedor/modelo"}``; ``--model``).
        env: Ambiente a ler (padrão: ``os.environ``).
        provider_factory: Seam de teste para o health check.

    Raises:
        RoutingError: Política/modo inválidos, pin inválido ou nenhum modelo elegível.
        CatalogError: Catálogo inválido.
    """
    politica = validate_policy(config.LLM_DATA_POLICY)
    modo = validate_routing_mode(config.LLM_ROUTING)
    catalog = get_catalog()
    pins = read_pins(catalog, env, cli_pins)
    priority = parse_priority(config.LLM_PROVIDER_PRIORITY, config.DEPLOYMENT_PROFILE)
    disponiveis = await compute_availability(
        catalog,
        _relevant_ids(catalog, pins, politica),
        priority=priority,
        timeout=config.LLM_HEALTH_CHECK_TIMEOUT_SECONDS,
        provider_factory=provider_factory,
    )
    routing = _resolve(catalog, pins, politica, modo, disponiveis)
    from src.llm.allocation import seed_ollama_versions

    await seed_ollama_versions(routing, provider_factory)
    return routing


def build_offline_routing(
    cli_pins: Mapping[str, str] | None = None, *, env: Mapping[str, str] | None = None
) -> SessionRouting:
    """Resolução sem rede (fora de sessão): credencial/endpoint e lista de permissão, sem health check."""
    politica = validate_policy(config.LLM_DATA_POLICY)
    modo = validate_routing_mode(config.LLM_ROUTING)
    catalog = get_catalog()
    pins = read_pins(catalog, env, cli_pins)
    priority = parse_priority(config.LLM_PROVIDER_PRIORITY, config.DEPLOYMENT_PROFILE)
    decided, pending = static_availability(catalog, _relevant_ids(catalog, pins, politica), priority=priority)
    decided.update({model_id: Availability(True) for model_id in pending})
    return _resolve(catalog, pins, politica, modo, decided)


def get_session_routing() -> SessionRouting:
    """Mapa da sessão corrente ou, fora de sessão, o resolvido na hora (sem health check)."""
    return current_session_routing() or build_offline_routing()
