"""Validação de endpoints (``base_url``) dos provedores LLM (ADR 017 §8).

A chave de API e os prompts só podem trafegar em claro para loopback ou rede privada; qualquer
outro host exige ``https``. A regra vale para **todo** provedor que tenha ``base_url`` (``openai``,
``openai_compatible``, ``ollama``, ``anthropic`` e os que vierem), na validação do catálogo e na
criação do provedor.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# 100.64.0.0/10 (RFC 6598, "carrier-grade NAT"): faixa das redes sobrepostas privadas e cifradas,
# como o Tailscale (usado para alcançar o Raspberry Pi). Não é roteável na internet pública.
_OVERLAY_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class EndpointError(ValueError):
    """Endpoint remoto sem ``https``."""


def is_private_host(host: str) -> bool:
    """Loopback ou faixa privada, sem resolver DNS (um nome só vale se for ``localhost``).

    Endereços link-local (``169.254.0.0/16``, ``fe80::/10``, inclusive o endpoint de metadados de
    nuvem) **não** contam como rede privada. A faixa 100.64.0.0/10 (rede sobreposta, ex.: Tailscale)
    conta como privada.
    """
    if host.lower() in ("localhost", "localhost.localdomain"):
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    if address.is_link_local:
        return False
    return address.is_loopback or address.is_private or (address.version == 4 and address in _OVERLAY_NETWORK)


def validate_remote_endpoint(provider: str, base_url: str, env_name: str | None = None) -> None:
    """Recusa endpoint fora de loopback/rede privada que não use ``https``.

    A mensagem cita só ``scheme://host`` (nunca credenciais embutidas na URL).

    Raises:
        EndpointError: Pede ``https`` para um host que não é local nem privado.
    """
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if parsed.scheme == "https" or is_private_host(host):
        return
    variable = f"configure {env_name} com https:// " if env_name else "use https:// "
    raise EndpointError(
        f"Endpoint do provedor '{provider}' ('{parsed.scheme}://{host}') está fora de loopback e de redes "
        f"privadas e não usa https: {variable}(a chave de API e os prompts não podem trafegar em claro)."
    )


def endpoint_host(base_url: str) -> str:
    """Host de uma URL de endpoint (``unix`` para socket Unix); nunca inclui credenciais."""
    parsed = urlparse(base_url)
    if parsed.scheme in ("unix", "http+unix", "https+unix"):
        return "unix"
    return parsed.hostname or ""


def is_loopback_host(host: str) -> bool:
    """``localhost``, ``127.0.0.0/8``, ``::1`` ou socket Unix (sem resolver DNS)."""
    if host.lower() in ("localhost", "localhost.localdomain", "unix"):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False
