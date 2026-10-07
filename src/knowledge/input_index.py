"""Indexação dos insumos de ``input_snapshot/`` no início da sessão (v17-input-document-index, design §1).

Roda logo depois do snapshot e da gravação dos ``Insumo``s no grafo, antes do planejamento, sem LLM.
Nenhuma falha (Qdrant, modelo de embedding, grafo, arquivo ruim) interrompe a sessão: o que não puder
ser vetorizado fica ``pendente`` e é completado na próxima sessão do projeto.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable

from src import config
from src.knowledge.ingestion_io import IngestionFileError, list_regular_files
from src.logger import get_logger
from src.skills.document_processor.enrichment import ProjectMeta
from src.skills.document_processor.extractors.registry import ExtractorRegistry
from src.skills.document_processor.indexer import DocumentIndexer
from src.skills.document_processor.pipeline import ORIGEM_INPUT, index_file, recover_pending

logger = get_logger(__name__)


def load_project_meta(store: Any, projeto_id: str) -> ProjectMeta:
    """Título, objetivo e domínios do projeto no grafo; só o ``projeto_id`` se o grafo falhar."""
    try:
        from src.knowledge.projects import get_project

        detail = get_project(store, projeto_id)
    except Exception as exc:  # noqa: BLE001 - o cabeçalho degrada, a indexação segue
        logger.warning("Metadados do projeto indisponíveis; cabeçalho só com o ID", extra={"error": type(exc).__name__})
        return ProjectMeta(projeto_id=projeto_id)
    return ProjectMeta(
        projeto_id=detail.projeto_id,
        titulo=detail.titulo,
        objetivo=detail.objetivo,
        dominios=tuple(d for d in detail.dominios if d),
    )


def _insumo_resolver(store: Any) -> Callable[[str], str | None]:
    """Resolve o ID do nó ``Insumo`` pelo hash; ``None`` (com ``WARNING``) se o grafo estiver indisponível."""
    warned = False

    def resolve(digest: str) -> str | None:
        nonlocal warned
        if store is None:
            if not warned:
                logger.warning("Grafo indisponível; pontos serão gravados com insumo_id nulo")
                warned = True
            return None
        try:
            nodes = store.find_nodes("Insumo", {"hash_conteudo": digest}, limit=1)
        except Exception as exc:  # noqa: BLE001
            if not warned:
                logger.warning(
                    "Grafo indisponível; pontos serão gravados com insumo_id nulo",
                    extra={"error": type(exc).__name__},
                )
                warned = True
            return None
        return nodes[0].id if nodes else None

    return resolve


async def index_input_snapshot(
    session_dir: Path,
    projeto: ProjectMeta,
    *,
    store: Any = None,
    indexer: DocumentIndexer | None = None,
    extractors: ExtractorRegistry | None = None,
    max_seconds: float | None = None,
) -> dict[str, Any]:
    """Indexa os arquivos de ``<session_dir>/input_snapshot/`` e completa vetorizações pendentes.

    Args:
        session_dir: Diretório da sessão (``outputs/<sessão>/``).
        projeto: Metadados do projeto da sessão.
        store: Grafo de conhecimento para obter o ``insumo_id``; ``None`` se indisponível.
        indexer: Indexador (padrão: ``DocumentIndexer()``).
        extractors: Extratores de texto (padrão: ``ExtractorRegistry()``).
        max_seconds: Prazo total (padrão ``INPUT_INDEX_MAX_SECONDS``); arquivos restantes ficam em ``pendentes``.

    Returns:
        Relatório para ``payload["input_index"]``: contagens, ``pendentes`` (não tratados por falta de
        tempo), ``falhas``, ``vetorizacao_pendente`` e ``segundos``.
    """
    started = time.monotonic()
    limit = config.INPUT_INDEX_MAX_SECONDS if max_seconds is None else max_seconds
    deadline = started + limit
    report: dict[str, Any] = {
        "indexados": 0,
        "ja_indexados": 0,
        "revetorizados": 0,
        "recuperados": 0,
        "pontos_vetorizados": 0,
        "vetorizacao_pendente": 0,
        "pendentes": [],
        "falhas": [],
        "segundos": 0.0,
    }
    indexer = indexer or await asyncio.to_thread(DocumentIndexer)
    extractors = extractors or ExtractorRegistry()
    resolver = _insumo_resolver(store)
    status_key = {"indexado": "indexados", "ja_indexado": "ja_indexados", "revetorizado": "revetorizados"}

    for path in list_regular_files(session_dir / "input_snapshot", session_dir):
        if time.monotonic() >= deadline:
            report["pendentes"].append(path.name)
            continue
        try:
            outcome = await index_file(
                indexer, extractors, path, root=session_dir, projeto=projeto, origem=ORIGEM_INPUT,
                insumo_resolver=resolver, deadline=deadline,
            )
        except (IngestionFileError, ValueError, OSError) as exc:
            logger.warning(
                "Insumo não indexado",
                extra={"arquivo": path.name, "error": type(exc).__name__, "motivo": str(exc)[:200]},
            )
            report["falhas"].append(path.name)
            continue
        report[status_key[outcome.status]] += 1
        report["pontos_vetorizados"] += outcome.vetorizados
        if outcome.vetorizacao == "pendente":
            report["vetorizacao_pendente"] += 1

    if time.monotonic() < deadline:
        try:
            report["recuperados"] = await recover_pending(indexer, projeto, deadline=deadline)
        except Exception as exc:  # noqa: BLE001 - recuperação é oportunista
            logger.warning("Recuperação de vetorizações pendentes falhou", extra={"error": type(exc).__name__})
    report["segundos"] = round(time.monotonic() - started, 3)
    return report
