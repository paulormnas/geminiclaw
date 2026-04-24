import urllib.robotparser
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup

from src.skills.base import BaseSkill, SkillResult
from src.logger import get_logger
from src.skills.search_quick.cache import SearchCache

logger = get_logger(__name__)

class WebReaderSkill(BaseSkill):
    """Lê o conteúdo completo de uma URL e extrai o texto limpo.
    
    Implementa validação de robots.txt e cache de resultados.
    """
    
    name = "web_reader"
    description = "Use para ler o conteúdo completo de uma URL. Retorna texto extraído da página."
    
    def __init__(self, cache: SearchCache[str] | None = None):
        """Inicializa a skill de WebReader.
        
        Args:
            cache: Instância de SearchCache para armazenar textos (reusa a mesma classe do search_quick).
        """
        self.cache = cache or SearchCache[str]()
        # Mantém um dicionário local de instâncias de RobotFileParser
        self._robots_parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def _can_fetch(self, url: str) -> bool:
        """Verifica se o robots.txt permite o acesso à URL."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{base_url}/robots.txt"
        
        if base_url not in self._robots_parsers:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            try:
                # O read() é bloqueante mas razoavelmente rápido, 
                # seria melhor fazer async, mas urllib.robotparser não suporta.
                # Como é uma skill, a latência de ler o robots.txt é tolerável, 
                # ou podemos usar httpx para baixar e fazer parse.
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(robots_url, follow_redirects=True)
                    if resp.status_code == 200:
                        rp.parse(resp.text.splitlines())
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
            
        # Verifica cache
        cached = self.cache.get(url)
        if cached is not None:
            logger.info("WebReader: Cache hit", extra={"url": url})
            return SkillResult(success=True, output=cached)
            
        # Verifica robots.txt
        can_fetch = await self._can_fetch(url)
        if not can_fetch:
            logger.warning("WebReader: Bloqueado pelo robots.txt", extra={"url": url})
            return SkillResult(success=False, output="", error="Acesso bloqueado pelo robots.txt do site.")

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                headers = {"User-Agent": "GeminiClaw Bot/1.0"}
                response = await client.get(url, headers=headers)
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
        except Exception as e:
            logger.error("WebReader: Erro na leitura", extra={"url": url, "error": str(e)})
            return SkillResult(success=False, output="", error=f"Falha ao ler a página: {str(e)}")
