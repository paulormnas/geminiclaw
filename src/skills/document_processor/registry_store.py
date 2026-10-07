"""Registro relacional dos documentos indexados (tabelas ``documents`` e ``document_chunks``).

O registro guarda o que é recalculável (texto do trecho, metadados) e o estado de vetorização
(``vetorizacao``); o Qdrant guarda os vetores. Os campos novos da v17-input-document-index ficam em
``metadata_json`` (JSONB), sem alteração de schema. ``InMemoryDocumentRegistry`` é o duplo usado
nos testes e quando não há PostgreSQL.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

ConnectionFactory = Callable[[], AbstractContextManager[Any]]


class DocumentRegistry(Protocol):
    """Contrato do registro de documentos e trechos."""

    def find_by_hash(self, projeto_id: str, hash_conteudo: str) -> dict[str, Any] | None: ...

    def get(self, document_id: str) -> dict[str, Any] | None: ...

    def upsert_document(self, doc: dict[str, Any], chunks: list[dict[str, Any]]) -> None: ...

    def update_metadata(self, document_id: str, changes: dict[str, Any]) -> None: ...

    def get_chunks(self, document_id: str) -> list[dict[str, Any]]: ...

    def list_documents(self, limit: int, projeto_id: str | None = None) -> list[dict[str, Any]]: ...

    def list_pending(self, projeto_id: str, limit: int = 100) -> list[dict[str, Any]]: ...


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata_json")
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw or {})


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["metadata_json"] = _meta(row)
    return out


class PostgresDocumentRegistry:
    """Registro em PostgreSQL (``documents``/``document_chunks``); upserts idempotentes por ID."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._conn = connection_factory

    def find_by_hash(self, projeto_id: str, hash_conteudo: str) -> dict[str, Any] | None:
        query = (
            "SELECT * FROM documents WHERE metadata_json->>'projeto_id' = %s "
            "AND metadata_json->>'hash_conteudo' = %s LIMIT 1"
        )
        with self._conn() as conn:
            row = conn.execute(query, (projeto_id, hash_conteudo)).fetchone()
        return _normalize(row) if row else None

    def get(self, document_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = %s", (document_id,)).fetchone()
        return _normalize(row) if row else None

    def upsert_document(self, doc: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
        doc_query = """
            INSERT INTO documents (
                id, source_path, filename, format, title, num_chunks, num_pages, file_size_bytes,
                ingested_at, metadata_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                source_path = EXCLUDED.source_path, filename = EXCLUDED.filename,
                format = EXCLUDED.format, title = EXCLUDED.title, num_chunks = EXCLUDED.num_chunks,
                num_pages = EXCLUDED.num_pages, file_size_bytes = EXCLUDED.file_size_bytes,
                metadata_json = EXCLUDED.metadata_json
        """
        chunk_query = """
            INSERT INTO document_chunks (id, document_id, chunk_index, content, token_count, metadata_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content, token_count = EXCLUDED.token_count,
                metadata_json = EXCLUDED.metadata_json
        """
        with self._conn() as conn:
            with conn.transaction():
                conn.execute(
                    doc_query,
                    (
                        doc["id"], doc["source_path"], doc["filename"], doc["format"], doc["title"],
                        doc["num_chunks"], doc.get("num_pages"), doc.get("file_size_bytes", 0),
                        doc.get("ingested_at") or datetime.now(timezone.utc),
                        json.dumps(doc["metadata_json"]),
                    ),
                )
                conn.execute(
                    "DELETE FROM document_chunks WHERE document_id = %s AND chunk_index >= %s",
                    (doc["id"], len(chunks)),
                )
                for chunk in chunks:
                    conn.execute(
                        chunk_query,
                        (
                            chunk["id"], doc["id"], chunk["chunk_index"], chunk["content"],
                            chunk["token_count"], json.dumps(chunk["metadata_json"]),
                        ),
                    )

    def update_metadata(self, document_id: str, changes: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE documents SET metadata_json = COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb "
                "WHERE id = %s",
                (json.dumps(changes), document_id),
            )

    def get_chunks(self, document_id: str) -> list[dict[str, Any]]:
        query = (
            "SELECT id, chunk_index, content, token_count, metadata_json FROM document_chunks "
            "WHERE document_id = %s ORDER BY chunk_index"
        )
        with self._conn() as conn:
            rows = conn.execute(query, (document_id,)).fetchall()
        return [_normalize(r) for r in rows]

    def list_documents(self, limit: int, projeto_id: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if projeto_id is None:
                rows = conn.execute("SELECT * FROM documents ORDER BY ingested_at DESC LIMIT %s", (limit,))
            else:
                rows = conn.execute(
                    "SELECT * FROM documents WHERE metadata_json->>'projeto_id' = %s "
                    "ORDER BY ingested_at DESC LIMIT %s",
                    (projeto_id, limit),
                )
            return [_normalize(r) for r in rows.fetchall()]

    def list_pending(self, projeto_id: str, limit: int = 100) -> list[dict[str, Any]]:
        query = (
            "SELECT * FROM documents WHERE metadata_json->>'projeto_id' = %s "
            "AND metadata_json->>'vetorizacao' = 'pendente' ORDER BY ingested_at LIMIT %s"
        )
        with self._conn() as conn:
            return [_normalize(r) for r in conn.execute(query, (projeto_id, limit)).fetchall()]


class InMemoryDocumentRegistry:
    """Registro em memória com a mesma semântica do PostgreSQL (testes)."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.chunks: dict[str, list[dict[str, Any]]] = {}

    def find_by_hash(self, projeto_id: str, hash_conteudo: str) -> dict[str, Any] | None:
        for row in self.documents.values():
            meta = row["metadata_json"]
            if meta.get("projeto_id") == projeto_id and meta.get("hash_conteudo") == hash_conteudo:
                return _normalize(row)
        return None

    def get(self, document_id: str) -> dict[str, Any] | None:
        row = self.documents.get(document_id)
        return _normalize(row) if row else None

    def upsert_document(self, doc: dict[str, Any], chunks: list[dict[str, Any]]) -> None:
        row = {**doc, "metadata_json": dict(doc["metadata_json"])}
        row.setdefault("ingested_at", datetime.now(timezone.utc))
        self.documents[doc["id"]] = row
        self.chunks[doc["id"]] = [
            {**c, "document_id": doc["id"], "metadata_json": dict(c["metadata_json"])} for c in chunks
        ]

    def update_metadata(self, document_id: str, changes: dict[str, Any]) -> None:
        if document_id in self.documents:
            self.documents[document_id]["metadata_json"].update(changes)

    def get_chunks(self, document_id: str) -> list[dict[str, Any]]:
        rows = sorted(self.chunks.get(document_id, []), key=lambda c: c["chunk_index"])
        return [_normalize(r) for r in rows]

    def list_documents(self, limit: int, projeto_id: str | None = None) -> list[dict[str, Any]]:
        rows = [
            r for r in self.documents.values()
            if projeto_id is None or r["metadata_json"].get("projeto_id") == projeto_id
        ]
        rows.sort(key=lambda r: r["ingested_at"], reverse=True)
        return [_normalize(r) for r in rows[:limit]]

    def list_pending(self, projeto_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = [
            r for r in self.documents.values()
            if r["metadata_json"].get("projeto_id") == projeto_id
            and r["metadata_json"].get("vetorizacao") == "pendente"
        ]
        rows.sort(key=lambda r: r["ingested_at"])
        return [_normalize(r) for r in rows[:limit]]
