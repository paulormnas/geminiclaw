"""Download dos ativos declarados (v18.5-sandbox-phases, design §3).

Script **fixo do projeto**, somente biblioteca padrão: é injetado e executado dentro do container da
fase ``fetch_assets`` (com rede e sem dados) e também importado no host para reutilizar a validação
de URL. Nada aqui vem do LLM além da lista ``{url, destino}`` validada antes pelo host.

Uso no container: ``python fetch_assets.py <spec.json>``. O JSON é
``{"assets": [{"url", "destino"}], "max_bytes": N, "total_max_bytes": N, "allow_private_hosts": [...]}``. Cada arquivo é
gravado em ``/staging/<destino>``; o hash é calculado e verificado pelo host.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import socket
import ssl
import sys
import urllib.parse
from typing import Iterable

STAGING_DIR = "/staging"
MAX_REDIRECTS = 5
CHUNK_BYTES = 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 30
_CLOUD_METADATA_HOST = "169.254.169.254"
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class AssetError(Exception):
    """Falha de validação ou de download de um ativo (mensagem acionável, sem conteúdo remoto)."""


def blocked_address(address: str) -> bool:
    """True se o endereço não é globalmente roteável (loopback, privado, link-local, CGNAT, metadados)."""
    addr = ipaddress.ip_address(address.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return not addr.is_global or addr.is_multicast or str(addr) == _CLOUD_METADATA_HOST


def validate_url(url: str, allow_private_hosts: Iterable[str] = ()) -> urllib.parse.SplitResult:
    """Valida esquema e host literal de ``url``; devolve a URL decomposta.

    Raises:
        AssetError: Esquema diferente de http/https, host ausente ou IP literal bloqueado.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 — valida a porta
    except ValueError as exc:
        raise AssetError(f"URL inválida: {exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise AssetError(f"esquema '{parts.scheme}' não permitido: use http ou https")
    if not host:
        raise AssetError("URL sem host")
    if host in set(allow_private_hosts):
        return parts
    if host.lower() in ("localhost", "localhost.localdomain"):
        raise AssetError("o host 'localhost' está bloqueado")
    try:
        is_literal = bool(ipaddress.ip_address(host.split("%")[0]))
    except ValueError:
        is_literal = False
    if is_literal and blocked_address(host):
        raise AssetError(f"o endereço '{host}' é interno ou reservado e está bloqueado")
    return parts


def _resolve(host: str, port: int, allow_private_hosts: Iterable[str]) -> str:
    """Resolve ``host`` uma vez e devolve um IP seguro (todos os endereços resolvidos precisam ser globais)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise AssetError(f"não foi possível resolver o host '{host}'") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise AssetError(f"o host '{host}' não resolve para nenhum endereço")
    if host not in set(allow_private_hosts):
        for address in addresses:
            if blocked_address(address):
                raise AssetError(f"o host '{host}' resolve para um endereço interno ou reservado: bloqueado")
    return addresses[0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Conecta ao IP já validado (sem nova resolução de nome: evita DNS rebinding)."""

    def __init__(self, ip: str, port: int) -> None:
        super().__init__(ip, port, timeout=CONNECT_TIMEOUT_SECONDS)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Como a HTTP, com TLS validado contra o nome original (SNI e certificado)."""

    def __init__(self, ip: str, port: int, server_name: str) -> None:
        super().__init__(ip, port, timeout=CONNECT_TIMEOUT_SECONDS, context=ssl.create_default_context())
        self._server_name = server_name

    def connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self._server_name)


def download(url: str, destination: str, max_bytes: int, allow_private_hosts: Iterable[str] = ()) -> int:
    """Baixa ``url`` para ``destination`` seguindo redirecionamentos com revalidação a cada salto.

    Args:
        url: URL http/https do ativo.
        destination: Caminho do arquivo a gravar.
        max_bytes: Tamanho máximo aceito (o download é interrompido ao exceder).
        allow_private_hosts: Hosts liberados (somente testes; nunca vem do LLM).

    Returns:
        Quantidade de bytes gravados.

    Raises:
        AssetError: URL bloqueada, redirecionamento excessivo, HTTP != 200 ou tamanho acima do limite.
    """
    allow = tuple(allow_private_hosts)
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        parts = validate_url(current, allow)
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
        ip = _resolve(host, port, allow)
        conn = _PinnedHTTPSConnection(ip, port, host) if parts.scheme == "https" else _PinnedHTTPConnection(ip, port)
        try:
            path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
            headers = {"Host": parts.netloc.rsplit("@", 1)[-1], "User-Agent": "geminiclaw-fetch"}
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            if response.status in _REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    raise AssetError(f"redirecionamento (HTTP {response.status}) sem destino")
                current = urllib.parse.urljoin(current, location)
                continue
            if response.status != 200:
                raise AssetError(f"o servidor respondeu HTTP {response.status}")
            declared = response.getheader("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise AssetError(f"o ativo declara {declared} bytes, acima do limite de {max_bytes}")
            written = 0
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise AssetError(f"o ativo excede o limite de {max_bytes} bytes")
                    handle.write(chunk)
            return written
        except (OSError, http.client.HTTPException) as exc:
            raise AssetError(f"falha de rede ao baixar o ativo: {type(exc).__name__}") from exc
        finally:
            conn.close()
    raise AssetError(f"mais de {MAX_REDIRECTS} redirecionamentos")


def main(argv: list[str]) -> int:
    """Lê a especificação, baixa cada ativo para ``/staging`` e devolve 0 (todos) ou 1 (alguma falha)."""
    with open(argv[1], encoding="utf-8") as handle:
        spec = json.load(handle)
    max_bytes = int(spec["max_bytes"])
    remaining = int(spec.get("total_max_bytes", max_bytes * len(spec["assets"])))
    allow = spec.get("allow_private_hosts", [])
    failed = False
    for item in spec["assets"]:
        destino = item["destino"]
        try:
            # Teto somado por execução: cada download só pode usar o que resta do total.
            size = download(item["url"], os.path.join(STAGING_DIR, destino), min(max_bytes, remaining), allow)
            remaining -= size
            print(f"ok {destino} {size}")
        except AssetError as exc:
            failed = True
            print(f"erro {destino}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
