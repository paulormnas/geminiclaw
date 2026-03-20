"""Ferramentas do agente researcher.

Implementa a ferramenta de busca que executa o Gemini CLI como
subprocesso assíncrono, com integração ao cache de resultados.
"""

import asyncio
import asyncio.subprocess
from pathlib import Path

from src.logger import get_logger
from src.config import AGENT_TIMEOUT_SECONDS
from agents.researcher.cache import SearchCache

logger = get_logger(__name__)

# Cache global compartilhado pela sessão do agente
_search_cache = SearchCache()


async def search(query: str) -> str:
    """Busca informações usando o Gemini CLI como subprocesso.

    Consulta o cache antes de executar o subprocesso. Se o resultado
    estiver cacheado e dentro do TTL, retorna imediatamente.

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

    # 2. Executa Gemini CLI como subprocesso
    logger.info(
        "Executando busca via Gemini CLI",
        extra={"query": query[:100]},
    )

    try:
        process = await asyncio.create_subprocess_exec(
            "gemini",
            "-p",
            query,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=AGENT_TIMEOUT_SECONDS,
        )

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            logger.error(
                "Gemini CLI retornou erro",
                extra={
                    "query": query[:100],
                    "returncode": process.returncode,
                    "stderr": error_msg[:500],
                },
            )
            return f"Erro na busca (código {process.returncode}): {error_msg}"

        result = stdout.decode("utf-8", errors="replace").strip()

        if not result:
            logger.warning(
                "Gemini CLI retornou resultado vazio",
                extra={"query": query[:100]},
            )
            return "Nenhum resultado encontrado para a busca."

        # 3. Armazena no cache
        _search_cache.set(query, result)

        # 4. Salva o artefato de pesquisa (Etapa 1)
        try:
            import os
            agent_id = os.environ.get("AGENT_ID", "researcher")
            # O Orquestrador cria outputs/<session_id>/<agent_id>/artifacts
            # No container, /outputs mapeia para outputs/<session_id>/
            art_dir = Path("/outputs") / agent_id / "artifacts"
            
            if art_dir.exists() or Path("/outputs").exists():
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

    except asyncio.TimeoutError:
        logger.error(
            "Timeout ao executar busca",
            extra={
                "query": query[:100],
                "timeout": AGENT_TIMEOUT_SECONDS,
            },
        )
        # Tenta encerrar o processo se ainda estiver rodando
        try:
            process.kill()  # type: ignore[possibly-unbound] — process é definido antes do timeout
        except (ProcessLookupError, OSError):
            pass
        return f"Erro: busca excedeu o timeout de {AGENT_TIMEOUT_SECONDS}s."

    except FileNotFoundError:
        logger.error(
            "Gemini CLI não encontrado no PATH",
            extra={"query": query[:100]},
        )
        return "Erro: Gemini CLI ('gemini') não encontrado. Verifique a instalação."

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
