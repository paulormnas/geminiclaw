"""Fixtures da indexação dos insumos: Qdrant em memória, registro em memória, embedding falso que registra entradas."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.skills.document_processor.enrichment import ProjectMeta
from src.skills.document_processor.extractors.registry import ExtractorRegistry
from src.skills.document_processor.indexer import DocumentIndexer
from src.skills.document_processor.registry_store import InMemoryDocumentRegistry
from tests.support.fake_embedding_provider import FakeEmbeddingProvider


class RecordingProvider(FakeEmbeddingProvider):
    """Provedor falso que registra cada texto enviado ao embedding de documentos."""

    def __init__(self) -> None:
        super().__init__(dimension=16)
        self.inputs: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.inputs.extend(texts)
        return super().embed_documents(texts)


class StubNode:
    def __init__(self, node_id: str) -> None:
        self.id = node_id


class StubStore:
    """Grafo mínimo: ``find_nodes('Insumo', {'hash_conteudo': h})`` devolve um nó de ID derivado do hash."""

    def find_nodes(self, label: str, filters: dict, limit: int = 50) -> list[StubNode]:
        return [StubNode("insumo-" + filters["hash_conteudo"][:8])]


class DownStore:
    def find_nodes(self, *args, **kwargs):
        raise RuntimeError("grafo fora do ar")


PROJ_A = ProjectMeta(
    projeto_id="proj-a", titulo="Classificação de flores", objetivo="Classificar espécies", dominios=("botânica",)
)
PROJ_B = ProjectMeta(projeto_id="proj-b", titulo="Outro projeto", objetivo="Outro objetivo", dominios=())


@pytest.fixture
def provider() -> RecordingProvider:
    return RecordingProvider()


@pytest.fixture
def indexer(provider: RecordingProvider) -> DocumentIndexer:
    return DocumentIndexer(url=":memory:", embedding_provider=provider, registry=InMemoryDocumentRegistry())


@pytest.fixture
def extractors() -> ExtractorRegistry:
    return ExtractorRegistry()


def make_session(tmp_path: Path, files: dict[str, str | bytes], name: str = "sess") -> Path:
    """Cria ``outputs/<name>/input_snapshot/`` com os arquivos dados e devolve o diretório da sessão."""
    session = tmp_path / name
    snap = session / "input_snapshot"
    snap.mkdir(parents=True)
    for fname, content in files.items():
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        (snap / fname).write_bytes(data)
    return session


def all_points(indexer: DocumentIndexer) -> list:
    points, _ = indexer.qdrant.scroll(
        collection_name=DocumentIndexer.COLLECTION_NAME, with_payload=True, limit=1000
    )
    return points
