"""Integração da indexação dos insumos com PostgreSQL real (v17-input-document-index).

Requer PostgreSQL acessível por DATABASE_URL com `scripts/init_db.sql` aplicado (tabelas `documents` e
`document_chunks`); o Qdrant é em memória e o embedding é falso e determinístico. Skippado sem banco.
Valida o SQL JSONB do `PostgresDocumentRegistry` (que os testes unitários cobrem só em memória).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from src.knowledge.input_index import index_input_snapshot
from src.skills.document_processor.enrichment import ProjectMeta
from src.skills.document_processor.extractors.registry import ExtractorRegistry
from src.skills.document_processor.indexer import DocumentIndexer
from src.skills.document_processor.registry_store import PostgresDocumentRegistry
from tests.support.fake_embedding_provider import FakeEmbeddingProvider


def _postgres_available() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql://"):
        return False
    try:
        import psycopg

        psycopg.connect(url, connect_timeout=3).close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_available(), reason="PostgreSQL não disponível"),
]


@pytest.fixture
def registry() -> PostgresDocumentRegistry:
    import src.db as db

    return PostgresDocumentRegistry(lambda: db.get_connection())


@pytest.fixture
def projeto() -> ProjectMeta:
    return ProjectMeta(
        projeto_id=f"it-{uuid.uuid4()}", titulo="Projeto de integração", objetivo="Objetivo", dominios=("d",)
    )


@pytest.fixture(autouse=True)
def _cleanup(registry, projeto):
    yield
    with registry._conn() as conn:
        conn.execute("DELETE FROM documents WHERE metadata_json->>'projeto_id' = %s", (projeto.projeto_id,))


def _session(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    snap = tmp_path / name / "input_snapshot"
    snap.mkdir(parents=True)
    for fname, content in files.items():
        (snap / fname).write_text(content)
    return tmp_path / name


@pytest.mark.asyncio
async def test_pg_primeira_sessao_repetida_e_descritor(tmp_path, registry, projeto):
    indexer = DocumentIndexer(
        url=":memory:", embedding_provider=FakeEmbeddingProvider(dimension=16), registry=registry
    )
    files = {"artigo.txt": "Trecho um.\n\nTrecho dois.", "dados.csv": "id,massa_g\n1,2.5\n2,3.5\n"}

    first = await index_input_snapshot(
        _session(tmp_path, "s1", files), projeto, indexer=indexer, extractors=ExtractorRegistry()
    )
    second = await index_input_snapshot(
        _session(tmp_path, "s2", files), projeto, indexer=indexer, extractors=ExtractorRegistry()
    )

    assert first["indexados"] == 2 and second["ja_indexados"] == 2 and second["indexados"] == 0
    docs = registry.list_documents(10, projeto.projeto_id)
    assert {d["metadata_json"]["tipo_insumo"] for d in docs} == {"artigo", "dataset"}
    assert registry.list_pending(projeto.projeto_id) == []
    csv_doc = next(d for d in docs if d["metadata_json"]["tipo_insumo"] == "dataset")
    (chunk,) = registry.get_chunks(csv_doc["id"])
    assert "2 linhas" in chunk["content"] and "2.5" not in chunk["content"]


@pytest.mark.asyncio
async def test_pg_vetorizacao_pendente_e_recuperacao(tmp_path, registry, projeto, monkeypatch):
    indexer = DocumentIndexer(
        url=":memory:", embedding_provider=FakeEmbeddingProvider(dimension=16), registry=registry
    )
    real_upsert = indexer.qdrant.upsert

    def down(*args, **kwargs):
        raise ConnectionError("qdrant fora do ar")

    monkeypatch.setattr(indexer.qdrant, "upsert", down)
    await index_input_snapshot(
        _session(tmp_path, "s1", {"a.txt": "texto"}), projeto, indexer=indexer, extractors=ExtractorRegistry()
    )
    assert len(registry.list_pending(projeto.projeto_id)) == 1

    monkeypatch.setattr(indexer.qdrant, "upsert", real_upsert)
    report = await index_input_snapshot(
        _session(tmp_path, "s2", {}), projeto, indexer=indexer, extractors=ExtractorRegistry()
    )

    assert report["recuperados"] == 1 and registry.list_pending(projeto.projeto_id) == []
