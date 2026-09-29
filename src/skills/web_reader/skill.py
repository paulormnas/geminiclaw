import asyncio
import ipaddress
import socket
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.logger import get_logger
from src.skills.base import BaseSkill, SkillResult
from src.skills.search_quick.cache import SearchCache

logger = get_logger(__name__)

# Roadmap V16/ADR 014 (Design §4) — ferramentas web no host nunca podem alcançar
# rede interna: bloqueia loopback, faixas privadas (RFC 1918), link-local e o
# serviço de metadados de nuvem (169.254.169.254), independentemente de o alvo
# ter sido informado como IP literal ou como um nome que resolve para um deles.
_CLOUD_METADATA_HOST = "169.254.169.254"


async def _resolve_host(hostname: str) -> tuple[str | None, str | None]:
    """Resolve ``hostname`` uma única vez e classifica o resultado.

    Existe uma única chamada de resolução aqui de propósito: o achado do
    review do PR #65 é que checar o host e depois deixar o ``httpx`` resolver
    de novo por conta própria na requisição real abre uma janela de
    TOCTOU/DNS rebinding (um domínio controlado por atacante pode responder
    com um IP público nesta checagem e um IP interno na conexão real,
    minutos ou segundos depois). A correção é resolver uma vez e usar o
    mesmo IP para conectar (``resolve_and_pin_host``), nunca re-resolver.

    Args:
        hostname: Nome de host ou endereço IP literal a verificar.

    Returns:
        Tupla ``(safe_ip, block_reason)``. Quando a resolução funciona e é
        segura, ``safe_ip`` traz o primeiro endereço IP resolvido e
        ``block_reason`` é ``None``. Quando algum endereço resolvido é
        interno/reservado, ``safe_ip`` é ``None`` e ``block_reason`` explica
        o motivo. Quando a resolução falha, ambos são ``None`` (falha
        aberta — a própria requisição HTTP falhará da mesma forma; isso
        evita falsos positivos em ambientes de teste/CI sem rede, sem
        enfraquecer a proteção real, já que endereços internos literais
        continuam bloqueados sem depender de DNS).
    """
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
    except socket.gaierror:
        logger.debug("resolve_and_check_host: falha ao resolver host, prosseguindo", extra={"hostname": hostname})
        return None, None

    safe_ip: str | None = None
    for info in infos:
        raw_addr = info[4][0]
        try:
            addr = ipaddress.ip_address(raw_addr.split("%")[0])
        except ValueError:
            continue
        if (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or str(addr) == _CLOUD_METADATA_HOST
        ):
            return None, (
                f"o host '{hostname}' resolve para o endereço interno/reservado "
                f"'{addr}', bloqueado para acesso via ferramentas web."
            )
        if safe_ip is None:
            safe_ip = str(addr)
    return safe_ip, None


async def resolve_and_check_host(hostname: str) -> str | None:
    """Resolve ``hostname`` e verifica se algum endereço resultante é bloqueado.

    Args:
        hostname: Nome de host ou endereço IP literal a verificar.

    Returns:
        ``None`` se o host é seguro para acessar; caso contrário, uma mensagem
        explicando por que o acesso foi bloqueado.
    """
    _ip, reason = await _resolve_host(hostname)
    return reason


async def resolve_and_pin_host(hostname: str) -> tuple[str | None, str | None]:
    """Resolve e valida ``hostname``, devolvendo o IP a usar para conectar.

    Chame isto uma única vez por URL e reutilize o ``safe_ip`` retornado em
    todas as requisições HTTP subsequentes para esse host (via
    ``pinned_get``), em vez de deixar o ``httpx`` resolver de novo.

    Args:
        hostname: Nome de host ou endereço IP literal a verificar.

    Returns:
        Tupla ``(safe_ip, block_reason)`` — ver ``_resolve_host``.
    """
    return await _resolve_host(hostname)


def _pin_url_to_ip(url: str, ip: str) -> str:
    """Substitui o host de ``url`` pelo ``ip`` resolvido, preservando o resto.

    Args:
        url: URL original (com hostname).
        ip: Endereço IP validado por ``resolve_and_pin_host`` a usar na conexão.

    Returns:
        URL equivalente com o host trocado pelo IP literal.
    """
    parsed = urlparse(url)
    host_for_netloc = f"[{ip}]" if ":" in ip else ip
    netloc = f"{host_for_netloc}:{parsed.port}" if parsed.port else host_for_netloc
    return parsed._replace(netloc=netloc).geturl()


async def pinned_get(
    client: httpx.AsyncClient,
    url: str,
    hostname: str,
    ip: str,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Executa um GET conectando diretamente ao ``ip`` já validado.

    O ``httpx`` nunca resolve ``hostname`` de novo: a URL efetivamente usada
    na conexão já é o IP literal. Preserva o cabeçalho ``Host`` e a SNI TLS
    com o ``hostname`` original, para que virtual hosting e verificação de
    certificado continuem corretos.

    Args:
        client: Cliente ``httpx.AsyncClient`` a usar.
        url: URL original (com hostname), usada para path/query/porta.
        hostname: Hostname original, preservado via ``Host``/SNI.
        ip: Endereço IP validado ao qual conectar de fato.
        headers: Cabeçalhos adicionais da requisição.

    Returns:
        A resposta HTTP.
    """
    pinned_url = _pin_url_to_ip(url, ip)
    request_headers = dict(headers or {})
    request_headers["Host"] = hostname
    return await client.get(
        pinned_url,
        headers=request_headers,
        extensions={"sni_hostname": hostname},
    )


class WebReaderBlockedError(Exception):
    """Levantada quando um host — inicial ou alcançado via redirecionamento — é bloqueado."""


_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


async def guarded_get(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str] | None = None,
    max_redirects: int = _MAX_REDIRECTS,
) -> httpx.Response:
    """GET com o guard de SSRF (resolve+valida+pin) reaplicado a cada hop.

    Não basta fixar o IP só na primeira conexão: com ``follow_redirects=True``
    o ``httpx`` resolveria e conectaria a cada hop de redirecionamento por
    conta própria, e um servidor malicioso poderia simplesmente responder
    3xx apontando para um IP interno para contornar o guard inteiro. Por
    isso os redirecionamentos são seguidos manualmente aqui, reaplicando
    ``resolve_and_pin_host``/``pinned_get`` a cada hop.

    Args:
        client: Cliente ``httpx.AsyncClient`` a usar (criado com
            ``follow_redirects=False``, ou o parâmetro é ignorado aqui).
        url: URL inicial a buscar.
        headers: Cabeçalhos adicionais da requisição.
        max_redirects: Número máximo de redirecionamentos a seguir.

    Returns:
        A resposta HTTP final (não-redirecionamento).

    Raises:
        WebReaderBlockedError: quando a URL inicial ou algum hop de
            redirecionamento resolve para um host interno/reservado, ou
            quando o número máximo de redirecionamentos é excedido.
    """
    current_url = url
    for _ in range(max_redirects + 1):
        hostname = urlparse(current_url).hostname
        if not hostname:
            raise WebReaderBlockedError(f"URL '{current_url}' sem host válido.")

        safe_ip, block_reason = await resolve_and_pin_host(hostname)
        if block_reason is not None:
            raise WebReaderBlockedError(block_reason)

        if safe_ip is not None:
            response = await pinned_get(client, current_url, hostname, safe_ip, headers=headers)
        else:
            # Falha aberta na resolução (ver _resolve_host) — deixa o httpx
            # tentar normalmente; a requisição falhará do mesmo jeito.
            response = await client.get(current_url, headers=headers)

        if response.status_code in _REDIRECT_STATUS_CODES and "location" in response.headers:
            current_url = urljoin(current_url, response.headers["location"])
            continue
        return response

    raise WebReaderBlockedError(f"Número máximo de redirecionamentos ({max_redirects}) excedido para '{url}'.")


class WebReaderSkill(BaseSkill):
    """Lê o conteúdo completo de uma URL e extrai o texto limpo.
    
    Implementa validação de robots.txt e cache de resultados.
    """
    
    name = "web_reader"
    description = "Use para ler o conteúdo completo de uma URL. Retorna texto extraído da página."
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "A URL completa da página a ser lida."
            },
            "max_chars": {
                "type": "integer",
                "description": "Número máximo de caracteres a retornar (padrão: 5000).",
                "default": 5000
            }
        },
        "required": ["url"]
    }
    
    def __init__(self, cache: SearchCache[str] | None = None):
        """Inicializa a skill de WebReader.
        
        Args:
            cache: Instância de SearchCache para armazenar textos (reusa a mesma classe do search_quick).
        """
        self.cache = cache or SearchCache[str]()
        # Mantém um dicionário local de instâncias de RobotFileParser
        self._robots_parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def _can_fetch(self, url: str) -> bool:
        """Verifica se o robots.txt permite o acesso à URL.
        
        Trata HTTP 404 no robots.txt como permissão concedida, conforme RFC 9309 §2.3.1:
        'If the robots.txt resource is not found, that is if its HTTP response status code
        is 404 (Not Found), crawlers MUST treat this as if the entire site is allowed.'
        """
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{base_url}/robots.txt"
        
        if base_url not in self._robots_parsers:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await guarded_get(client, robots_url)
                    # V12.4.2 — RFC 9309: robots.txt 404 = todo o site liberado
                    if resp.status_code == 404:
                        logger.debug(
                            "robots.txt ausente (404) — assumindo acesso liberado (RFC 9309)",
                            extra={"robots_url": robots_url},
                        )
                        # Armazena um parser vazio que libera tudo
                        self._robots_parsers[base_url] = rp
                        return True
                    if resp.status_code == 200:
                        rp.parse(resp.text.splitlines())
            except WebReaderBlockedError as e:
                # V16/ADR 014 — robots.txt redirecionando para host bloqueado
                # (ex.: rede interna) não deve ser tratado como "permissão
                # concedida por falha"; trata como bloqueado explicitamente.
                logger.warning(
                    "Acesso ao robots.txt bloqueado (host interno/reservado)",
                    extra={"url": robots_url, "reason": str(e)},
                )
                self._robots_parsers[base_url] = rp
                return False
            except Exception as e:
                logger.warning(
                    "Falha ao ler robots.txt, assumindo permissão",
                    extra={"url": robots_url, "error": str(e)}
                )

            self._robots_parsers[base_url] = rp
            
        rp = self._robots_parsers[base_url]
        return rp.can_fetch("*", url)

    async def run(self, url: str, max_chars: int = 5000, **kwargs) -> SkillResult:
        """Executa a leitura de uma URL."""
        if not url:
            return SkillResult(success=False, output="", error="URL não fornecida.")

        # V12.4.1 — Validação de schema: apenas http:// e https:// são suportados.
        # Rejeita schemas como file://, ftp://, data: com mensagem clara e acionável.
        from urllib.parse import urlparse as _parse
        parsed_schema = _parse(url).scheme.lower()
        if parsed_schema not in ("http", "https"):
            logger.warning(
                "WebReader: schema de URL não suportado",
                extra={"url": url, "schema": parsed_schema},
            )
            return SkillResult(
                success=False,
                output="",
                error=(
                    f"Erro: URL com schema '{parsed_schema}' não é suportada pelo web_reader. "
                    "Apenas URLs http:// e https:// são aceitas. "
                    "Para ler arquivos locais, use a ferramenta 'python_interpreter' com open()."
                ),
            )

        # Verifica cache
        cached = self.cache.get(url)
        if cached is not None:
            logger.info("WebReader: Cache hit", extra={"url": url})
            return SkillResult(success=True, output=cached)

        # V16/ADR 014 — Bloqueia acesso a rede interna (loopback, RFC 1918,
        # link-local, metadados de nuvem) antes de qualquer requisição de rede,
        # inclusive o robots.txt.
        hostname = urlparse(url).hostname
        if not hostname:
            return SkillResult(success=False, output="", error="URL sem host válido.")
        block_reason = await resolve_and_check_host(hostname)
        if block_reason is not None:
            logger.warning("WebReader: acesso bloqueado a rede interna", extra={"url": url, "reason": block_reason})
            return SkillResult(success=False, output="", error=f"Acesso bloqueado: {block_reason}")

        # Verifica robots.txt
        can_fetch = await self._can_fetch(url)
        if not can_fetch:
            logger.warning("WebReader: Bloqueado pelo robots.txt", extra={"url": url})
            return SkillResult(success=False, output="", error="Acesso bloqueado pelo robots.txt do site.")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"User-Agent": "GeminiClaw Bot/1.0"}
                response = await guarded_get(client, url, headers=headers)
                response.raise_for_status()

            # Extração de texto usando BeautifulSoup
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Remove scripts, styles, e navegação comum que não são conteúdo principal
            for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                element.decompose()
                
            # Extrai o texto, separando blocos com espaços
            text = soup.get_text(separator=" ", strip=True)
            
            # Trunca se necessário
            if len(text) > max_chars:
                text = text[:max_chars] + "... [CONTEÚDO TRUNCADO]"
                
            self.cache.set(url, text)
            return SkillResult(success=True, output=text)
            
        except httpx.HTTPStatusError as e:
            logger.error("WebReader: Erro HTTP", extra={"url": url, "status": e.response.status_code})
            return SkillResult(success=False, output="", error=f"Erro HTTP {e.response.status_code} ao acessar a URL.")
        except WebReaderBlockedError as e:
            logger.warning(
                "WebReader: acesso bloqueado a rede interna (redirecionamento)",
                extra={"url": url, "reason": str(e)},
            )
            return SkillResult(success=False, output="", error=f"Acesso bloqueado: {e}")
        except Exception as e:
            logger.error("WebReader: Erro na leitura", extra={"url": url, "error": str(e)})
            return SkillResult(success=False, output="", error=f"Falha ao ler a página: {str(e)}")
