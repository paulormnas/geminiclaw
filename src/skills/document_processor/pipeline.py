"""Caminho único de indexação de um arquivo de insumo (v17-input-document-index, design §1-§4).

Usado pela indexação automática do ``input_snapshot/`` (``src/knowledge/input_index.py``) e pela ação
``ingest`` da skill ``document_processor`` (arquivos de ``artifacts/``): mesma deduplicação por
(``projeto_id``, ``hash_conteudo``), mesmo enriquecimento e mesmo payload. Sem LLM.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.config import INPUT_INDEX_HEADER_MAX_CHARS, INPUT_INDEX_MAX_FILE_MB
from src.knowledge.ingestion import insumo_tipo
from src.knowledge.ingestion_io import MAX_HASH_BYTES, sha256_file
from src.logger import get_logger
from src.skills.document_processor.chunker import (
    DocumentChunk,
    DocumentChunker,
    chunk_id_for,
    document_id_for,
)
from src.skills.document_processor.descriptors import (
    IMAGE_EXT,
    describe_dataset,
    describe_image,
    describe_other,
)
from src.skills.document_processor.enrichment import (
    VERSAO_ENRIQUECIMENTO,
    ProjectMeta,
    build_header,
    enriched_text,
    hash_cabecalho_projeto,
)
from src.skills.document_processor.extractors.registry import ExtractorRegistry
from src.skills.document_processor.indexer import DocumentIndexer

logger = get_logger(__name__)

SEM_PROJETO = "sem_projeto"
ORIGEM_INPUT = "input_context"
ORIGEM_ARTEFATO = "artefato"


@dataclass(frozen=True)
class IndexOutcome:
    """Resultado da indexação de um arquivo.

    Attributes:
        status: ``indexado``, ``ja_indexado`` ou ``revetorizado``.
        document_id: ID determinístico do documento.
        title: Título do documento.
        tipo_insumo: ``artigo``, ``dataset``, ``imagem`` ou ``outro``.
        vetorizacao: ``ok`` ou ``pendente``.
        pontos: Quantidade de pontos (trechos ou descritor) do documento.
        vetorizados: Pontos vetorizados nesta chamada.
    """

    status: str
    document_id: str
    title: str
    tipo_insumo: str
    vetorizacao: str
    pontos: int
    vetorizados: int = 0


def tipo_insumo_for(path: Path) -> str:
    """Tipo do insumo pela extensão: ``artigo``/``dataset``/``imagem``/``outro``.

    Segue a regra da ``v17-structural-fact-ingestion`` (``insumo_tipo``), com imagens à parte e
    ``.pptx`` tratado como texto (``artigo``), conforme o design §2.
    """
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "imagem"
    if ext == ".pptx":
        return "artigo"
    return insumo_tipo(path.name)


def _file_format(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "desconhecido"


def _chunks_from_rows(doc_id: str, rows: list[dict[str, Any]]) -> list[DocumentChunk]:
    total = len(rows)
    return [
        DocumentChunk(
            chunk_id=r["id"],
            document_id=doc_id,
            content=r["content"],
            chunk_index=r["chunk_index"],
            total_chunks=total,
            metadata=dict(r["metadata_json"]),
            token_count=r["token_count"],
        )
        for r in rows
    ]


def _enrich(
    chunks: list[DocumentChunk],
    meta: dict[str, Any],
    projeto: ProjectMeta,
    header_max_chars: int,
) -> None:
    """Preenche ``embed_text`` e ``payload_extra`` de cada chunk a partir dos metadados do documento."""
    for chunk in chunks:
        header = build_header(
            titulo=meta["titulo"],
            tipo_insumo=meta["tipo_insumo"],
            nome_arquivo=meta["nome_arquivo"],
            meta=projeto,
            secao=chunk.metadata.get("secao"),
            max_chars=header_max_chars,
        )
        chunk.embed_text = enriched_text(header, chunk.content)
        chunk.payload_extra = {
            "titulo": meta["titulo"],
            "nome_arquivo": meta["nome_arquivo"],
            "insumo_id": meta.get("insumo_id"),
            "projeto_id": projeto.projeto_id,
            "tipo_insumo": meta["tipo_insumo"],
            "tipo_ponto": chunk.metadata.get("tipo_ponto", "trecho"),
            "hash_conteudo": meta["hash_conteudo"],
            "dominios": list(projeto.dominios),
            "visibilidade": "privado",
            "origem": meta["origem"],
            "versao_enriquecimento": VERSAO_ENRIQUECIMENTO,
            "cabecalho": header,
        }


async def _vectorize_stored(
    indexer: DocumentIndexer,
    doc_id: str,
    meta: dict[str, Any],
    projeto: ProjectMeta,
    deadline: float | None,
    header_max_chars: int,
) -> tuple[list[DocumentChunk], bool]:
    """Reenriquece e revetoriza os trechos já registrados (mesmos IDs) e atualiza o estado."""
    chunks = _chunks_from_rows(doc_id, indexer.registry.get_chunks(doc_id))
    _enrich(chunks, meta, projeto, header_max_chars)
    ok = await indexer.vectorize(chunks, deadline)
    indexer.registry.update_metadata(
        doc_id,
        {
            "versao_enriquecimento": VERSAO_ENRIQUECIMENTO,
            "hash_cabecalho_projeto": hash_cabecalho_projeto(projeto),
            "insumo_id": meta.get("insumo_id"),
            "dominios": list(projeto.dominios),
            "vetorizacao": "ok" if ok else "pendente",
        },
    )
    return chunks, ok


async def recover_pending(
    indexer: DocumentIndexer,
    projeto: ProjectMeta,
    *,
    deadline: float | None = None,
    header_max_chars: int = INPUT_INDEX_HEADER_MAX_CHARS,
) -> int:
    """Completa a vetorização dos documentos ``pendente`` do projeto (sem reler os arquivos).

    Returns:
        Quantidade de documentos que passaram a ``ok``.
    """
    recovered = 0
    for row in indexer.registry.list_pending(projeto.projeto_id):
        if deadline is not None and time.monotonic() >= deadline:
            break
        _, ok = await _vectorize_stored(
            indexer, row["id"], row["metadata_json"], projeto, deadline, header_max_chars
        )
        recovered += int(ok)
    return recovered


async def index_file(
    indexer: DocumentIndexer,
    extractors: ExtractorRegistry,
    path: Path,
    *,
    root: Path,
    projeto: ProjectMeta,
    origem: str = ORIGEM_INPUT,
    insumo_id: str | None = None,
    insumo_resolver: Callable[[str], str | None] | None = None,
    deadline: float | None = None,
    max_file_mb: int = INPUT_INDEX_MAX_FILE_MB,
    header_max_chars: int = INPUT_INDEX_HEADER_MAX_CHARS,
) -> IndexOutcome:
    """Indexa um arquivo uma única vez por (``projeto_id``, ``hash_conteudo``).

    Args:
        indexer: Indexador (Qdrant + registro).
        extractors: Extratores de texto.
        path: Arquivo a indexar.
        root: Diretório que confina o arquivo (sem links simbólicos nem fuga).
        projeto: Metadados do projeto (cabeçalho e payload).
        origem: ``input_context`` ou ``artefato``.
        insumo_id: ID do nó ``Insumo`` no grafo; ``None`` se o grafo está indisponível.
        insumo_resolver: Alternativa a ``insumo_id``: obtém o ID do ``Insumo`` a partir do hash do arquivo.
        deadline: Instante limite (``time.monotonic``) para a vetorização.
        max_file_mb: Acima disso, só descritor.
        header_max_chars: Tamanho máximo do cabeçalho.

    Raises:
        IngestionFileError: Arquivo inseguro ou ilegível.
        ValueError: Falha de extração de um arquivo textual.
    """
    digest = sha256_file(path, root, max_bytes=MAX_HASH_BYTES)
    if insumo_id is None and insumo_resolver is not None:
        insumo_id = insumo_resolver(digest)
    projeto_id = projeto.projeto_id
    doc_id = document_id_for(projeto_id, digest)
    registry = indexer.registry
    existing = registry.find_by_hash(projeto_id, digest)

    if existing is not None:
        meta = dict(existing["metadata_json"])
        current = (
            meta.get("versao_enriquecimento") == VERSAO_ENRIQUECIMENTO
            and meta.get("hash_cabecalho_projeto") == hash_cabecalho_projeto(projeto)
            and meta.get("vetorizacao") == "ok"
            and (insumo_id is None or meta.get("insumo_id") == insumo_id)
        )
        if current:
            return IndexOutcome(
                "ja_indexado", existing["id"], existing["title"], meta["tipo_insumo"], "ok",
                existing["num_chunks"],
            )
        meta["insumo_id"] = insumo_id or meta.get("insumo_id")
        chunks, ok = await _vectorize_stored(
            indexer, existing["id"], meta, projeto, deadline, header_max_chars
        )
        return IndexOutcome(
            "revetorizado", existing["id"], existing["title"], meta["tipo_insumo"],
            "ok" if ok else "pendente", len(chunks), len(chunks) if ok else 0,
        )

    tipo = tipo_insumo_for(path)
    size = os.stat(path).st_size
    oversized = size > max_file_mb * 1024 * 1024
    metadata_extra: dict[str, Any] = {}
    if tipo == "artigo" and not oversized:
        extracted = await asyncio.to_thread(extractors.extract, str(path))
        if extracted.extraction_errors:
            raise ValueError(f"Erros durante extração: {', '.join(extracted.extraction_errors)}")
        title, fmt, num_pages = extracted.title, extracted.format, extracted.num_pages
        chunks = DocumentChunker().chunk(extracted, doc_id)
        for chunk in chunks:
            chunk.metadata["tipo_ponto"] = "trecho"
    else:
        if oversized:
            logger.warning(
                "Arquivo acima do limite de indexação; registrado só com descritor",
                extra={"arquivo": path.name, "bytes": size, "limite_mb": max_file_mb},
            )
            text = describe_other(path) if tipo in ("artigo", "dataset") else describe_image(path)
            text += "\nIndexado só por descritor: acima do limite de tamanho."
        elif tipo == "dataset":
            text = await asyncio.to_thread(describe_dataset, path)
        elif tipo == "imagem":
            text = await asyncio.to_thread(describe_image, path)
        else:
            text = describe_other(path)
        title, fmt, num_pages = path.name, _file_format(path), None
        chunks = [
            DocumentChunk(
                chunk_id=chunk_id_for(doc_id, 0),
                document_id=doc_id,
                content=text,
                chunk_index=0,
                total_chunks=1,
                metadata={"source_path": str(path), "format": fmt, "tipo_ponto": "descritor"},
                token_count=len(text) // 4,
            )
        ]
        metadata_extra["so_descritor"] = True

    # PostgreSQL rejeita \x00 em texto: removido do conteúdo e do título antes do registro e do embedding.
    title = title.replace("\x00", "")
    for chunk in chunks:
        chunk.content = chunk.content.replace("\x00", "")

    meta = {
        "projeto_id": projeto_id,
        "hash_conteudo": digest,
        "insumo_id": insumo_id,
        "tipo_insumo": tipo,
        "versao_enriquecimento": VERSAO_ENRIQUECIMENTO,
        "hash_cabecalho_projeto": hash_cabecalho_projeto(projeto),
        "vetorizacao": "pendente",
        "titulo": title,
        "nome_arquivo": path.name,
        "origem": origem,
        "dominios": list(projeto.dominios),
        **metadata_extra,
    }
    registry.upsert_document(
        {
            "id": doc_id,
            "source_path": str(path),
            "filename": path.name,
            "format": fmt,
            "title": title,
            "num_chunks": len(chunks),
            "num_pages": num_pages,
            "file_size_bytes": size,
            "metadata_json": meta,
        },
        [
            {
                "id": c.chunk_id,
                "chunk_index": c.chunk_index,
                "content": c.content,
                "token_count": c.token_count,
                "metadata_json": c.metadata,
            }
            for c in chunks
        ],
    )
    _enrich(chunks, meta, projeto, header_max_chars)
    ok = await indexer.vectorize(chunks, deadline)
    if ok:
        registry.update_metadata(doc_id, {"vetorizacao": "ok"})
    return IndexOutcome(
        "indexado", doc_id, title, tipo, "ok" if ok else "pendente", len(chunks), len(chunks) if ok else 0
    )
