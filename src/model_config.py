"""Configuração de modelos e provedores por papel de agente (Roadmap V14.1).

Define o mapeamento de cada papel arquitetural para seu provedor e modelo correspondentes,
permitindo customização via variáveis de ambiente com fallback para compatibilidade.
"""

from dataclasses import dataclass
from typing import Dict
from src import config


@dataclass(frozen=True)
class RoleModelConfig:
    """Configuração de modelo para um papel específico."""

    role: str
    provider: str
    model: str


# Mapeamento padrão por papel (ADR 007 / Roadmap V14.1)
DEFAULT_ROLE_CONFIGS: Dict[str, Dict[str, str]] = {
    "researcher": {
        "provider": "google",
        "model": "gemini-2.0-flash",
    },
    "validator": {
        "provider": "ollama",
        "model": "qwen3:8b",
    },
    "developer": {
        "provider": "google",
        "model": "gemini-2.0-flash",
    },
}


def get_role_model_config(role: str) -> RoleModelConfig:
    """Retorna a configuração de modelo e provedor para o papel especificado.

    Prioriza variáveis de ambiente:
    - {ROLE}_PROVIDER (ex: RESEARCHER_PROVIDER)
    - {ROLE}_MODEL (ex: RESEARCHER_MODEL)

    Args:
        role: Nome do papel ('researcher', 'validator', 'developer').

    Returns:
        RoleModelConfig com provider e model resolvidos.

    Raises:
        ValueError: Se o papel informado for desconhecido.
    """
    normalized_role = role.strip().lower()
    if normalized_role not in DEFAULT_ROLE_CONFIGS:
        valid_roles = ", ".join(sorted(DEFAULT_ROLE_CONFIGS.keys()))
        raise ValueError(
            f"Papel desconhecido para ModelRouter: '{role}'. "
            f"Papéis válidos suportados: {valid_roles}."
        )

    defaults = DEFAULT_ROLE_CONFIGS[normalized_role]
    prefix = normalized_role.upper()

    provider = config.get_env(f"{prefix}_PROVIDER", default=defaults["provider"]).lower()
    model = config.get_env(f"{prefix}_MODEL", default=defaults["model"])

    return RoleModelConfig(
        role=normalized_role,
        provider=provider,
        model=model,
    )
