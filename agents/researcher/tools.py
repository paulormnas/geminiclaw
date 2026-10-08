"""Ferramentas do agente researcher.

Implementa a ferramenta de busca técnica usada pelo Researcher, delegando à
skill ``search_quick`` (Roadmap V16/ADR 014, Design §4). Historicamente esta
função executava o binário ``gemini`` como subprocesso — removido porque
nenhuma ferramenta do host deve criar processos externos a partir de código
ou parâmetros derivados do LLM (Requirement "Busca do Researcher sem
subprocesso de fornecedor").
"""

from typing import Optional

from agents.researcher.cache import SearchCache
from src.logger import get_logger
from src.skills.search_quick.skill import QuickSearchSkill

logger = get_logger(__name__)

# Cache global compartilhado pela sessão do agente
_search_cache = SearchCache()

# Instância compartilhada da skill de busca rápida (sem estado sensível por tarefa).
_quick_search_skill: Optional[QuickSearchSkill] = None


def _get_quick_search_skill() -> QuickSearchSkill:
    """Retorna a instância (lazy) de ``QuickSearchSkill`` usada por ``search``."""
    global _quick_search_skill
    if _quick_search_skill is None:
        _quick_search_skill = QuickSearchSkill()
    return _quick_search_skill


def _format_results(results: list[dict]) -> str:
    """Formata os resultados de ``QuickSearchSkill`` como texto legível.

    Args:
        results: Lista de dicionários com campos de ``SearchResult``
            (``title``, ``url``, ``snippet``, tipicamente).

    Returns:
        Texto formatado com os resultados, um bloco por resultado.
    """
    blocks = []
    for r in results:
        title = r.get("title", "") or "(sem título)"
        url = r.get("url", "")
        snippet = r.get("snippet", "") or r.get("description", "")
        blocks.append(f"- {title}\n  {url}\n  {snippet}".rstrip())
    return "\n\n".join(blocks)


async def search(query: str) -> str:
    """Busca informações técnicas usando a skill ``search_quick``.

    Consulta o cache antes de executar a busca. Se o resultado estiver
    cacheado e dentro do TTL, retorna imediatamente.

    Args:
        query: Termo ou pergunta de busca.

    Returns:
        Texto com o resultado da busca, ou mensagem de erro.
    """
    if not query or not query.strip():
        return "Erro: query de busca vazia."

    # 1. Verifica cache
    cached = _search_cache.get(query)
    if cached is not None:
        logger.info(
            "Resultado retornado do cache",
            extra={"query": query[:100]},
        )
        return cached

    # 2. Executa busca via skill search_quick (sem subprocesso)
    logger.info(
        "Executando busca técnica via search_quick",
        extra={"query": query[:100]},
    )

    try:
        skill_result = await _get_quick_search_skill().run(query=query)

        if not skill_result.success:
            logger.warning(
                "search_quick retornou erro",
                extra={"query": query[:100], "error": skill_result.error},
            )
            return f"Erro na busca: {skill_result.error}"

        results = skill_result.output or []
        if not results:
            logger.warning(
                "search_quick retornou resultado vazio",
                extra={"query": query[:100]},
            )
            return "Nenhum resultado encontrado para a busca."

        result = _format_results(results)

        # 3. Armazena no cache
        _search_cache.set(query, result)

        # 4. Salva o artefato de pesquisa (Etapa 1)
        #
        # Roadmap V16/ADR 014 — reaproveita a mesma resolução confinada de
        # `agents.base.tools` (``ctx.output_dir / "artifacts"`` no runtime em
        # processo via AgentContext; ``/outputs/artifacts`` no modo container
        # legado) em vez de ler ``os.environ`` diretamente, que não é isolado
        # por tarefa quando várias execuções rodam concorrentemente no mesmo
        # processo.
        try:
            from agents.base.tools import _resolve_artifacts_dir

            art_dir = _resolve_artifacts_dir()

            if art_dir is not None:
                art_dir.mkdir(parents=True, exist_ok=True)
                research_file = art_dir / "research_results.md"
                with open(research_file, "a", encoding="utf-8") as f:
                    f.write(f"\n## Pesquisa: {query}\n\n{result}\n")
        except Exception as e:
            logger.warning("Falha ao salvar artefato de pesquisa", extra={"error": str(e)})

        logger.info(
            "Busca concluída com sucesso",
            extra={"query": query[:100], "result_length": len(result)},
        )
        return result

    except Exception as e:
        logger.error(
            "Erro inesperado durante busca",
            extra={"query": query[:100], "error": str(e)},
        )
        return f"Erro inesperado durante a busca: {e}"


def get_search_cache() -> SearchCache:
    """Retorna a instância global do cache de busca.

    Útil para testes e inspeção.

    Returns:
        Instância do SearchCache em uso.
    """
    return _search_cache


def reset_search_cache(ttl_seconds: int | None = None) -> None:
    """Reseta o cache de busca global.

    Usado principalmente em testes para garantir isolamento.

    Args:
        ttl_seconds: Novo TTL em segundos. Se None, usa o padrão.
    """
    global _search_cache
    _search_cache = SearchCache(ttl_seconds=ttl_seconds)
