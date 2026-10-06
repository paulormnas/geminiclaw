"""Fixtures do índice semântico (v17-knowledge-semantic-index): sem rede, sem banco, sem Qdrant externo."""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from src.knowledge.candidates import CandidateGenerator, SimilarityThresholds
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.indexed_store import IndexedGraphStore
from src.knowledge.provenance import Actor
from src.knowledge.semantic_index import SemanticIndex
from src.knowledge.similarity_queue import InMemorySimilarityQueue
from tests.support.controlled_embedding_provider import ControlledEmbeddingProvider

ORQ = Actor(kind="orquestrador")
DIM = 64

_REQUIRED = {
    "Projeto": {"titulo": "T", "objetivo": "O", "status": "ativo"},
    "Problema": {"titulo": "T", "resumo": "R", "status": "confirmado"},
    "Abordagem": {"nome": "N", "tipo": "algoritmo", "descricao": "D"},
    "Descoberta": {"tipo": "funciona", "enunciado": "E", "n_evidencias": 1, "status": "ativa"},
    "Decisao": {"contexto": "C", "justificativa": "J"},
    "Oportunidade": {"enunciado": "E", "justificativa": "J", "status": "documentada"},
    "Dominio": {"termo": "T", "nivel": "area", "status": "aprovado"},
    "Experimento": {
        "subtarefa_id": "s", "status": "sucesso", "caminho_artefatos": "/x", "no_execucao": "n",
    },
    "Resultado": {
        "nome_original": "acc", "valor": 0.9, "status_validacao": "validado", "caminho_metrics": "/m",
    },
}


class Env:
    """Ambiente de teste: grafo em memória + Qdrant em memória + fila em memória."""

    def __init__(self) -> None:
        self.raw = InMemoryGraphStore()
        self.provider = ControlledEmbeddingProvider(dimension=DIM)
        self.client = QdrantClient(location=":memory:")
        self.index = SemanticIndex(self.raw, self.client, provider=self.provider)
        self.queue = InMemorySimilarityQueue()
        self.generator = CandidateGenerator(self.raw, self.index, self.queue, thresholds=SimilarityThresholds(
            duplicate_min=0.90, related_same_domain=0.70, related_cross=0.60,
            cross_project_min_confidence=0.30, cross_domain_boost=1.5,
        ))
        self.generator.attach()
        self.store = IndexedGraphStore(self.raw, self.index)

    def make(self, label: str, projeto_id: str = "proj1", **props) -> str:
        """Cria um nó pelo store com gancho (preenche os campos obrigatórios do rótulo)."""
        data = {**_REQUIRED[label], "projeto_id": projeto_id, "sessao_id": "s1", **props}
        return self.store.create_node(label, data, actor=ORQ)

    def node(self, node_id: str):
        return self.raw.get_node(node_id)

    def point(self, node_id: str):
        if not self.client.collection_exists(self.index.collection):
            return None
        found = self.client.retrieve(self.index.collection, ids=[node_id], with_payload=True, with_vectors=True)
        return found[0] if found else None


@pytest.fixture
def env() -> Env:
    return Env()
