"""Perfil de alocação da sessão: localidade, família e versão efetiva por papel (v18.5-model-catalog-locality).

API pública para as demais mudanças (``v18.5-egress-gate``, ``v18.5-claim-verification``, relatórios), sem acesso
direto ao YAML do catálogo: ``current_allocation(papel)`` devolve o :class:`RoleAllocation` do papel na sessão
corrente. Os valores de ``localidade`` e ``aceita_dados_brutos`` são **como declarados** no catálogo (ADR 019 §1),
com ``aceita_dados_brutos`` efetivo (após a regra do ``no_no``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.llm import availability
from src.llm.availability import ProviderFactory
from src.llm.catalog import split_model_id
from src.llm.versions import UNKNOWN_VERSION, VersionTracker
from src.logger import get_logger

if TYPE_CHECKING:
    from src.llm.session import SessionRouting

logger = get_logger(__name__)


@dataclass(frozen=True)
class RoleAllocation:
    """Alocação de um papel: modelo, confiança, localidade, aceitação de dados brutos, família e versão."""

    papel: str
    provedor: str
    modelo: str
    trust: str  # "self_hosted" | "third_party"
    localidade: str  # "no_no" | "fora_do_no"
    aceita_dados_brutos: bool  # valor efetivo
    familia_modelo: str
    versao_efetiva: str  # "desconhecida" até ser observada


def allocation_for(routing: "SessionRouting", papel: str) -> RoleAllocation:
    """Alocação do papel no mapa resolvido (aplica ``aliases_papel``; papel desconhecido -> ``ValueError``)."""
    resolution = routing.resolution(papel)
    entry = routing.catalogo.modelos[resolution.id]
    return RoleAllocation(
        papel=resolution.papel,
        provedor=entry.provedor,
        modelo=entry.modelo,
        trust=entry.trust,
        localidade=entry.localidade,
        aceita_dados_brutos=entry.aceita_dados_brutos,
        familia_modelo=entry.familia_modelo,
        versao_efetiva=routing.versions.current(entry.id),
    )


def current_allocation(papel: str) -> RoleAllocation:
    """Alocação do papel na sessão corrente (fora de sessão, a resolvida na hora, sem rede)."""
    from src.llm.session import get_session_routing

    return allocation_for(get_session_routing(), papel)


def build_allocation_profile(routing: "SessionRouting") -> dict[str, Any]:
    """Conteúdo de ``payload["allocation_profile"]`` (sem segredos; JSON-serializável)."""
    papeis: dict[str, Any] = {}
    for role in routing.papeis:
        allocation = allocation_for(routing, role)
        entry: dict[str, Any] = {
            "provedor_modelo": f"{allocation.provedor}/{allocation.modelo}",
            "trust": allocation.trust,
            "localidade": allocation.localidade,
            "aceita_dados_brutos": allocation.aceita_dados_brutos,
            "familia_modelo": allocation.familia_modelo,
            "versao_efetiva": allocation.versao_efetiva,
        }
        desempate = routing.papeis[role].desempate
        if desempate is not None:
            entry["desempate"] = dict(desempate)
        papeis[role] = entry
    catalog = routing.catalogo
    return {
        "catalogo": {
            "versao": catalog.versao,
            "hash": catalog.hash,
            "local": catalog.local,
            "local_hash": catalog.local_hash,
        },
        "papeis": papeis,
    }


def allocation_catalog_line(routing: "SessionRouting") -> str:
    """Linha do catálogo no bloco "Alocação": versão e hash, e se há catálogo local (com o seu hash)."""
    catalog = routing.catalogo
    local = f"local: sim (hash {(catalog.local_hash or '')[:12]})" if catalog.local else "local: não"
    return f"catálogo v{catalog.versao} (hash {catalog.hash[:12]}) · {local}"


def allocation_banner_lines(routing: "SessionRouting") -> list[str]:
    """Bloco "Alocação" do banner: uma linha por papel, sem segredos."""
    width = max((len(role) for role in routing.papeis), default=0)
    lines = []
    for role in routing.papeis:
        a = allocation_for(routing, role)
        raw = "sim" if a.aceita_dados_brutos else "não"
        lines.append(
            f"{role.ljust(width)} → {a.provedor}/{a.modelo} · {a.trust} · {a.localidade} · dados brutos: {raw}"
        )
    return lines


def roles_for_model(routing: "SessionRouting", provider_name: str, model_name: str) -> tuple[str, ...]:
    """Papéis do mapa cujo modelo resolvido é ``provider_name``/``model_name`` (provedor sem sublinhado/caixa)."""
    wanted = provider_name.replace("_", "").lower()
    return tuple(
        role
        for role, res in routing.papeis.items()
        if split_model_id(res.id)[1] == model_name and split_model_id(res.id)[0].replace("_", "").lower() == wanted
    )


def record_call_version(provider_name: str, model_name: str, versao: str) -> str:
    """Registra a versão efetiva de uma chamada no rastreador da sessão e a devolve.

    Fora de sessão (sem mapa vinculado) apenas devolve o valor; a troca de versão só é detectada para o modelo de um
    papel do mapa. Chamado pelo laço do agente após cada resposta do provedor.
    """
    from src.llm.session import current_session_routing

    routing = current_session_routing()
    if routing is None:
        return versao
    roles = roles_for_model(routing, provider_name, model_name)
    key = routing.papeis[roles[0]].id if roles else f"{provider_name}/{model_name}"
    routing.versions.observe(key, versao, roles)
    return versao


async def _fetch_ollama_digest(
    routing: "SessionRouting", model_id: str, provider_factory: ProviderFactory | None
) -> str | None:
    provider_name, model = split_model_id(model_id)
    try:
        provider = (provider_factory or availability.default_provider_factory)(provider_name, model)
    except Exception as exc:  # noqa: BLE001 — a versão é telemetria
        logger.warning("Provedor Ollama indisponível para ler o digest", extra={"erro": type(exc).__name__})
        return None
    try:
        fetch = getattr(provider, "fetch_digest", None)
        return await fetch() if fetch is not None else None
    finally:
        close = getattr(provider, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001 — fechar o cliente nunca derruba a sessão
                logger.warning("Falha ao fechar o cliente do provedor de digest", extra={"provedor_modelo": model_id})


async def seed_ollama_versions(routing: "SessionRouting", provider_factory: ProviderFactory | None = None) -> None:
    """Início da sessão: lê o digest de cada modelo Ollama do mapa e o guarda como versão inicial (sem evento)."""
    for model_id in sorted({res.id for res in routing.papeis.values() if res.id.startswith("ollama/")}):
        digest = await _fetch_ollama_digest(routing, model_id, provider_factory)
        # Só o seed inicial grava ``desconhecida`` quando a leitura falha.
        routing.versions.seed(model_id, digest if digest is not None else UNKNOWN_VERSION)


async def refresh_ollama_versions(
    routing: "SessionRouting | None" = None, provider_factory: ProviderFactory | None = None
) -> list[dict[str, Any]]:
    """A cada checkpoint: relê os digests; uma troca vira evento ``versao_modelo_alterada``. Devolve os eventos."""
    from src.llm.session import current_session_routing

    routing = routing or current_session_routing()
    if routing is None:
        return []
    events: list[dict[str, Any]] = []
    for model_id in sorted({res.id for res in routing.papeis.values() if res.id.startswith("ollama/")}):
        digest = await _fetch_ollama_digest(routing, model_id, provider_factory)
        if digest is None:  # leitura falhou: mantém a versão conhecida (falha transitória não é troca)
            logger.warning("Digest do Ollama não lido; mantendo a versão anterior", extra={"provedor_modelo": model_id})
            continue
        roles = tuple(role for role, res in routing.papeis.items() if res.id == model_id)
        event = routing.versions.observe(model_id, digest, roles)
        if event is not None:
            events.append(event)
    return events


def new_version_tracker(modo: str) -> VersionTracker:
    """Rastreador da sessão; em ``strict`` a versão desconhecida ou alterada marca a parada pendente."""
    from src.llm.routing import ROUTING_STRICT

    return VersionTracker(strict=modo == ROUTING_STRICT)


__all__ = [
    "RoleAllocation",
    "allocation_banner_lines",
    "allocation_catalog_line",
    "allocation_for",
    "build_allocation_profile",
    "current_allocation",
    "new_version_tracker",
    "record_call_version",
    "refresh_ollama_versions",
    "roles_for_model",
    "seed_ollama_versions",
]
