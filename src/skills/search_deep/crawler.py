import asyncio
import httpx
import json
import os
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from src.logger import get_logger

logger = get_logger(__name__)

@dataclass
class CrawledPage:
    url: str
    title: str
    content: str
    crawled_at: str
    domain: str
    content_type: str = "text"
    published_at: Optional[str] = None
    mime_type: str = "text/html"

class DomainCrawler:
    """Crawler para coletar e processar páginas de domínios específicos."""

    def __init__(self, state_file: str = "store/crawl_state.json"):
        self.state_file = Path(state_file)
        self.state = self._load_state()
        self.client = httpx.AsyncClient(
            headers={"User-Agent": "GeminiClaw/0.1.0"},
            follow_redirects=True,
            timeout=10.0
        )

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Erro ao carregar estado do crawl: {e}")
        return {}

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    async def crawl(self, domains: List[str], max_pages_per_domain: int = 50) -> List[CrawledPage]:
        """Executa o crawl nos domínios fornecidos."""
        all_pages = []
        for domain in domains:
            pages = await self._crawl_domain(domain, max_pages_per_domain)
            all_pages.extend(pages)
        
        self._save_state()
        return all_pages

    async def _crawl_domain(self, domain: str, max_pages: int) -> List[CrawledPage]:
        logger.info(f"Iniciando crawl do domínio: {domain}")
        pages = []
        visited = set()
        queue = [f"https://{domain}" if not domain.startswith("http") else domain]
        
        # Simples crawler BFS com limite de páginas
        while queue and len(pages) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            
            visited.add(url)
            
            # Rate limiting: 1 segundo entre requisições (simplificado)
            await asyncio.sleep(1.0)
            
            try:
                # Verificação de Last-Modified para crawl incremental
                headers = {}
                if url in self.state and "last_modified" in self.state[url]:
                    headers["If-Modified-Since"] = self.state[url]["last_modified"]

                response = await self.client.get(url, headers=headers)
                
                if response.status_code == 304:
                    logger.info(f"Página não modificada: {url}")
                    continue
                
                if response.status_code != 200:
                    continue

                # Parse HTML
                soup = BeautifulSoup(response.text, "lxml")
                
                # Extrair metadados
                title = str(soup.title.string).strip() if soup.title and soup.title.string else url
                
                blocks = []
                
                # Extrair blocos de código
                for pre in soup.find_all("pre"):
                    code_text = pre.get_text(separator="\n").strip()
                    if code_text:
                        blocks.append(("code", code_text))
                    pre.decompose()
                
                # Extrair tabelas
                for table in soup.find_all("table"):
                    table_text = table.get_text(separator="\n").strip()
                    if table_text:
                        blocks.append(("table", table_text))
                    table.decompose()
                
                # Extrair o restante como texto
                content = self._extract_text(soup)
                if content:
                    blocks.append(("text", content))
                
                crawled_at = datetime.utcnow().isoformat()
                for ctype, text_content in blocks:
                    page = CrawledPage(
                        url=url,
                        title=title,
                        content=text_content,
                        crawled_at=crawled_at,
                        domain=domain,
                        content_type=ctype
                    )
                    pages.append(page)
                
                # Atualiza estado para crawl incremental
                self.state[url] = {
                    "last_modified": response.headers.get("Last-Modified"),
                    "crawled_at": crawled_at
                }

                # Encontrar novos links (apenas do mesmo domínio)
                if len(pages) < max_pages:
                    for link in soup.find_all("a", href=True):
                        href = link["href"]
                        # Resolve URL relativa
                        full_url = httpx.URL(url).join(href)
                        if full_url.host == httpx.URL(url).host:
                            queue.append(str(full_url))

            except Exception as e:
                logger.warning(f"Erro ao crawlar {url}: {e}")
        
        return pages

    def _extract_text(self, soup: BeautifulSoup) -> str:
        """Extrai texto limpo do HTML."""
        # Remove scripts e estilos
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Pega o texto
        text = soup.get_text(separator="\n")
        
        # Limpa espaços extras
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        return "\n".join(chunk for chunk in chunks if chunk)

    async def close(self):
        await self.client.aclose()
