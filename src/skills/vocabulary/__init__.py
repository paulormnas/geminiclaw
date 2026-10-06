"""Skill ``vocabulary``: ferramenta somente leitura ``buscar_dominio`` (v17-domain-search §6)."""

from src.skills.vocabulary.skill import (
    DOMAIN_SEARCH_ROLES,
    DomainSearchSkill,
    domain_search_tools,
)

__all__ = ["DOMAIN_SEARCH_ROLES", "DomainSearchSkill", "domain_search_tools"]
