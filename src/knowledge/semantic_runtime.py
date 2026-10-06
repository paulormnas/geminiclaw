"""Montagem do índice semântico de produção e comandos ``geminiclaw knowledge`` (V17).

Fica separado de ``src/cli.py`` para manter o ponto de integração mínimo:
``cli.py`` só despacha ``geminiclaw knowledge <ação>`` para
``run_knowledge_command``.

Ações:
    - ``stats``: tamanho da fila, taxa de confirmação por tipo e faixa e sugestões
      de ajuste de limiar (não altera nenhuma configuração).
    - ``reindex [--yes]``: reconcilia o índice com o grafo; se a dimensão do modelo
      mudou, recria a coleção (a partir do grafo) somente com confirmação.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from src import config
from src.knowledge.calibration import suggest_adjustments
from src.knowledge.candidates import CandidateGenerator
from src.knowledge.graph_store import GraphStore
from src.knowledge.indexed_store import IndexedGraphStore
from src.knowledge.semantic_index import IndexDimensionError, ReconcileReport, SemanticIndex
from src.knowledge.similarity_queue import PostgresSimilarityQueue, SimilarityQueue
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SemanticRuntime:
    """Componentes do índice semântico montados para uso em produção.

    Attributes:
        store: ``GraphStore`` com gancho de indexação (use este para escrever).
        raw_store: ``GraphStore`` cru (sem gancho).
        index: Índice semântico.
        queue: Fila de similaridade.
    """

    store: GraphStore
    raw_store: GraphStore
    index: SemanticIndex
    queue: SimilarityQueue


def build_runtime(
    raw_store: GraphStore, *, qdrant_client: Any | None = None, queue: SimilarityQueue | None = None
) -> SemanticRuntime:
    """Liga índice, fila, gerador de candidatos e gancho a um ``GraphStore``.

    Args:
        raw_store: Grafo sem o gancho de indexação.
        qdrant_client: Cliente Qdrant (padrão: ``QDRANT_URL``).
        queue: Fila (padrão: ``PostgresSimilarityQueue``).
    """
    if qdrant_client is None:
        from src.embeddings.reindex import _make_client

        qdrant_client = _make_client(config.QDRANT_URL)
    index = SemanticIndex(raw_store, qdrant_client)
    queue = queue or PostgresSimilarityQueue()
    CandidateGenerator(raw_store, index, queue).attach()
    return SemanticRuntime(
        store=IndexedGraphStore(raw_store, index), raw_store=raw_store, index=index, queue=queue
    )


def open_runtime() -> SemanticRuntime:
    """Abre o grafo cru (``factory.open_raw_graph_store``) e monta o runtime do índice.

    Raises:
        RuntimeError: Se ``KNOWLEDGE_READER_DATABASE_URL`` não está configurada.
    """
    from src.knowledge.factory import open_raw_graph_store

    return build_runtime(open_raw_graph_store())


def reconcile_on_session_start(runtime: SemanticRuntime) -> ReconcileReport | None:
    """Reconciliação do índice no início de cada sessão (rápida quando não há pendências).

    Falhas (ex.: Qdrant fora do ar) são registradas e não impedem a sessão: o grafo
    é a fonte da verdade e a próxima reconciliação corrige.

    Returns:
        O relatório, ou ``None`` se a reconciliação falhou.
    """
    try:
        return runtime.index.reconcile()
    except Exception as exc:  # noqa: BLE001 - a sessão não depende do índice para iniciar
        logger.warning("Reconciliação do índice semântico falhou", extra={"extra": {"error": str(exc)}})
        return None


def format_stats(queue: SimilarityQueue, window_days: int) -> str:
    """Texto do ``geminiclaw knowledge stats``."""
    rates = queue.confirmation_rate(window_days)
    lines = [
        f"Fila de similaridade: {queue.pending_count()} par(es) pendente(s).",
        f"Taxa de confirmação (últimos {window_days} dias):",
    ]
    if not rates:
        lines.append("  nenhum par revisado na janela.")
    for rate in rates:
        taxa = "n/d" if rate.taxa is None else f"{rate.taxa:.0%}"
        nota = " [amostra insuficiente]" if rate.avaliados < config.SIM_CALIBRATION_MIN_SAMPLES else ""
        lines.append(
            f"  {rate.tipo:<11} faixa {rate.faixa:<11} {taxa:>5} "
            f"({rate.confirmados} confirmado(s), {rate.descartados} descartado(s)){nota}"
        )
    suggestions = suggest_adjustments(rates)
    if suggestions:
        lines.append("Sugestões (nenhuma configuração foi alterada):")
        lines.extend(f"  - {s}" for s in suggestions)
    else:
        lines.append("Nenhum ajuste de limiar sugerido.")
    return "\n".join(lines)


def _run_sync(store: GraphStore, session_id: str | None) -> int:
    """``geminiclaw knowledge sync``: reaplica os eventos de ``knowledge_pending.jsonl`` (idempotente)."""
    from pathlib import Path

    from src.knowledge.ingestion import IngestionDataError, sync_pending

    try:
        report = sync_pending(store, Path(config.OUTPUT_BASE_DIR), session_id)
    except IngestionDataError as exc:
        print(f"\n  ❌ {exc}\n")
        return 1
    print(
        f"Fatos pendentes: {report.applied} aplicado(s), {report.pending} ainda pendente(s), "
        f"{report.dead} movido(s) para knowledge_pending.dead.jsonl, {report.ignored_lines} linha(s) ignorada(s) "
        f"em {report.sessions} sessão(ões)."
    )
    return 1 if report.pending or report.dead else 0


def run_knowledge_command(argv: list[str], runtime: SemanticRuntime | None = None) -> int:
    """Trata ``geminiclaw knowledge stats|reindex|sync``.

    Args:
        argv: Argumentos após ``knowledge``.
        runtime: Runtime já montado (injetável em testes); padrão: ``open_runtime()``.

    Returns:
        Código de saída (0 em sucesso).
    """
    parser = argparse.ArgumentParser(
        prog="geminiclaw knowledge", description="Índice semântico e fila de similaridade do grafo."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("stats", help="Taxa de confirmação da fila e sugestões de limiar.")
    reindex_p = sub.add_parser("reindex", help="Reconcilia o índice semântico com o grafo.")
    reindex_p.add_argument("--yes", action="store_true", help="Confirma a recriação da coleção se a dimensão mudou.")
    sync_p = sub.add_parser("sync", help="Reaplica os fatos pendentes (knowledge_pending.jsonl) ao grafo.")
    sync_p.add_argument("--session", default=None, help="Id da sessão; sem ele, todas as sessões com pendências.")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)

    try:
        if runtime is None:
            runtime = open_runtime()
        if args.action == "sync":
            return _run_sync(runtime.store, args.session)
        if args.action == "stats":
            print(format_stats(runtime.queue, config.SIM_CALIBRATION_WINDOW_DAYS))
            return 0
        try:
            report = runtime.index.reconcile()
        except IndexDimensionError as e:
            if not args.yes:
                name = runtime.index.collection
                try:
                    answer = input(
                        f"{e}\nIsto APAGA e recria a coleção '{name}' a partir do grafo. "
                        f"Digite o nome da coleção para confirmar: "
                    ).strip()
                except EOFError:
                    print("Sem terminal para confirmar; rode `geminiclaw knowledge reindex --yes` para confirmar.")
                    return 1
                if answer != name:
                    print("Operação cancelada.")
                    return 1
            report = runtime.index.reconcile(allow_recreate=True)
        print(
            f"Índice semântico: {report.checked} nó(s) examinado(s), {report.reindexed} revetorizado(s), "
            f"{report.payload_refreshed} payload(s) atualizado(s), "
            f"{report.failed} falha(s) ({report.elapsed_seconds:.1f}s)."
        )
        return 1 if report.failed else 0
    except RuntimeError as e:
        print(f"\n  ❌ {e}\n")
        return 1
