"""Adaptador de papel -> provedor/modelo sobre o mapa resolvido da sessão (ADR 017).

Não há mais padrões próprios aqui: o catálogo (``src/llm/catalog.yaml``) e o roteador
(``src/llm/routing.py``) decidem o modelo de cada papel. Este módulo só expõe a visão
``RoleModelConfig`` usada pelo orquestrador, pelo runtime e pelo relatório.
"""

from dataclasses import dataclass

from src.llm.catalog import split_model_id
from src.llm.session import get_session_routing


@dataclass(frozen=True)
class RoleModelConfig:
    """Provedor e modelo resolvidos para um papel específico."""

    role: str
    provider: str
    model: str


def known_roles() -> tuple[str, ...]:
    """Papéis do catálogo efetivo (sem aliases como ``planner``)."""
    return tuple(get_session_routing().papeis)


def get_role_model_config(role: str) -> RoleModelConfig:
    """Retorna o provedor e o modelo resolvidos para o papel (mapa da sessão corrente).

    Args:
        role: Nome do papel (ou alias, como ``planner``).

    Raises:
        ValueError: Se o papel for desconhecido.
    """
    routing = get_session_routing()
    resolution = routing.resolution(role)
    provider, model = split_model_id(resolution.id)
    return RoleModelConfig(role=resolution.papel, provider=provider, model=model)
