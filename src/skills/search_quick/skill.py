import os
from typing import Optional

from src.egress.fragments import ContentOrigin
from src.egress.gate import EgressRefused, caller_tainted, external_destination, get_gate
from src.logger import get_logger

from ..base import BaseSkill, SkillResult
from .brave import BraveSearchClient
from .cache import SearchCache
from .ddg_lite import DuckDuckGoLiteScraper
from .scraper import DuckDuckGoScraper

logger = get_logger(__name__)

class QuickSearchSkill(BaseSkill):
    """Skill de busca rápida que utiliza múltiplos backends com fallback."""
    
    name = "quick_search"
    
    egress_origin = ContentOrigin.DOCUMENTO
    description = (
        "Use esta skill para buscar informações atuais na internet de forma rápida. "
        "Forneça uma query específica. Retorna títulos, URLs e resumos dos primeiros resultados."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "O termo de busca a ser pesquisado na internet."
            },
            "max_results": {
                "type": "integer",
                "description": "Número máximo de resultados (padrão: 5).",
                "default": 5
            }
        },
        "required": ["query"]
    }

    def __init__(self, timeout: Optional[int] = None, ttl: Optional[int] = None):
        search_timeout = timeout or int(os.getenv("QUICK_SEARCH_TIMEOUT_SECONDS", "10"))
        cache_ttl = ttl or int(os.getenv("QUICK_SEARCH_CACHE_TTL_SECONDS", "3600"))
        
        self.strategy = os.getenv("QUICK_SEARCH_STRATEGY", "ddg,ddg_lite,brave").split(",")
        self.backends = {}
        
        if "ddg" in self.strategy:
            self.backends["ddg"] = DuckDuckGoScraper(timeout=search_timeout)
        if "ddg_lite" in self.strategy:
            self.backends["ddg_lite"] = DuckDuckGoLiteScraper(timeout=search_timeout)
        if "brave" in self.strategy:
            self.backends["brave"] = BraveSearchClient(timeout=search_timeout)
            
        self.cache = SearchCache(ttl=cache_ttl)

    def _primary_backend(self) -> str:
        """Primeiro backend da estratégia que existe (o primeiro a receber a consulta)."""
        for name in self.strategy:
            if name.strip() in self.backends:
                return name.strip()
        return "desconhecido"

    async def run(self, query: str, max_results: int = 5, **kwargs) -> SkillResult:
        """Executa a busca, verificando o cache e tentando os backends em cascata.

        Args:
            query: Termo de busca.
            max_results: Número máximo de resultados (default 5).

        Returns:
            SkillResult: Sucesso, lista de resultados ou erro.
        """
        if not query:
            return SkillResult(success=False, output=[], error="A query de busca não pode estar vazia.")

        try:
            # 1. Tentar recuperar do cache
            cached_results = self.cache.get(query)
            if cached_results:
                return SkillResult(
                    success=True, 
                    output=[r.__dict__ for r in cached_results[:max_results]],
                    metadata={"source": "cache"}
                )

            # v18.5-egress-gate — a consulta sai do nó (ADR 019 §3.5): números de papel contaminado viram marcadores e
            # o envio é registrado; consulta sem termos é recusada. O cache local acima não é egresso.
            gate = get_gate()
            try:
                outgoing = gate.check_query(
                    query, caller_tainted(), external_destination("busca", self._primary_backend())
                )
            except EgressRefused as exc:
                return SkillResult(success=False, output=[], error=str(exc))

            # 2. Tentar backends em ordem (fallback)
            results = []
            errors = []
            successful_backend = None
            
            for backend_name in self.strategy:
                backend = self.backends.get(backend_name.strip())
                if not backend:
                    continue
                    
                try:
                    logger.info(f"Tentando busca rápida com backend: {backend_name}")
                    if backend_name.strip() != self._primary_backend():
                        # Cada tentativa em outro backend é um envio: também registrada.
                        gate.check_query(outgoing, False, external_destination("busca", backend_name.strip()))
                    results = await backend.search(outgoing, max_results=max_results)
                    if results:
                        successful_backend = backend_name
                        break
                    else:
                        errors.append(f"{backend_name} retornou 0 resultados.")
                except Exception as e:
                    logger.warning(f"Backend {backend_name} falhou: {e}")
                    errors.append(f"{backend_name} error: {str(e)}")
            
            if not results:
                return SkillResult(
                    success=False, 
                    output=[], 
                    error=f"Todos os backends falharam ou retornaram vazio. Erros: {errors}"
                )
                
            # 3. Armazenar no cache
            self.cache.set(query, results)
            gate.note_search_urls(getattr(r, "url", "") for r in results)
            
            return SkillResult(
                success=True,
                output=[r.__dict__ for r in results],
                metadata={"source": successful_backend}
            )
        except Exception as e:
            return SkillResult(success=False, output=[], error=str(e))
