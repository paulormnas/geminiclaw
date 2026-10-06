"""Ambiente de teste da busca de domínio (v17-domain-search): grafo, Qdrant e embeddings em memória.

O provedor é determinístico e nunca usa rede: o vetor de cada termo e de cada consulta é definido
pelo teste (cosseno exato com a consulta), e qualquer outro texto cai em um eixo ortogonal (escore 0).
"""

from __future__ import annotations

import math

from qdrant_client import QdrantClient

from src.knowledge.domain_search import DomainSearch
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.indexed_store import IndexedGraphStore
from src.knowledge.provenance import Actor
from src.knowledge.semantic_index import SemanticIndex
from tests.support.controlled_embedding_provider import ControlledEmbeddingProvider

ORQ = Actor(kind="orquestrador")
DIM = 64
_FALLBACK_AXIS = DIM - 1


class FallbackProvider(ControlledEmbeddingProvider):
    """Provedor controlado: texto sem marcador vira um vetor em eixo próprio (ortogonal ao das consultas)."""

    def __init__(self) -> None:
        super().__init__(dimension=DIM)
        self.queries: list[str] = []

    def _fallback(self, text: str, axis: int) -> list[float]:
        for marker, vector in self.vectors.items():
            if marker in text:
                return list(vector)
        fallback = [0.0] * DIM
        fallback[axis] = 1.0
        return fallback

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embedded_texts.extend(texts)
        return [self._fallback(t, _FALLBACK_AXIS) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        # Consulta sem marcador: eixo diferente do dos documentos sem marcador (escore 0).
        return self._fallback(text, _FALLBACK_AXIS - 1)


class DomainEnv:
    """Grafo em memória + Qdrant em memória + ``DomainSearch``."""

    def __init__(self) -> None:
        self.raw = InMemoryGraphStore()
        self.provider = FallbackProvider()
        self.client = QdrantClient(location=":memory:")
        self.index = SemanticIndex(self.raw, self.client, provider=self.provider)
        self.store = IndexedGraphStore(self.raw, self.index)
        self.search = DomainSearch(self.raw, self.index)
        self._axis = 1

    def dom(
        self,
        termo: str,
        nivel: str,
        parent: str | None = None,
        *,
        codigo: str | None = None,
        status: str = "aprovado",
        sinonimos: list[str] | None = None,
    ) -> str:
        """Cria um ``Dominio`` (e a aresta ``SUBAREA_DE``) direto no grafo cru, sem indexar."""
        props: dict = {
            "termo": termo, "nivel": nivel, "status": status, "projeto_id": "__global__",
            "sessao_id": "s1", "visibilidade": "compartilhavel", "sinonimos": sinonimos or [],
        }
        if codigo:
            props["codigo_cnpq"] = codigo
        node_id = self.raw.create_node("Dominio", props, actor=ORQ)
        if parent:
            self.raw.create_edge(node_id, "SUBAREA_DE", parent, {}, actor=ORQ)
        return node_id

    def vec(self, termo: str, cosine: float) -> None:
        """Define o vetor do termo com o cosseno dado em relação às consultas (todas em ``e0``)."""
        vector = [0.0] * DIM
        vector[0] = cosine
        vector[self._axis] = math.sqrt(1.0 - cosine**2)
        self._axis += 1
        self.provider.vectors[f"Domínio: {termo}\n"] = vector

    def query(self, text: str) -> None:
        """Define a consulta ``text`` como o vetor ``e0``."""
        vector = [0.0] * DIM
        vector[0] = 1.0
        self.provider.vectors[f"Domínio: {text}"] = vector

    def build_cs(self) -> dict[str, str]:
        """Hierarquia de teste: Exatas > Computação > IA > (Aprendizado, Visão) e Exatas > Matemática."""
        ids: dict[str, str] = {}
        ids["ga"] = self.dom("Ciências Exatas e da Terra", "grande_area", codigo="T0")
        ids["cs"] = self.dom("Ciência da Computação", "area", ids["ga"], codigo="T1")
        ids["ia"] = self.dom("Inteligência Artificial", "subarea", ids["cs"], codigo="T11")
        ids["ml"] = self.dom("Aprendizado Supervisionado", "especialidade", ids["ia"], codigo="T111")
        ids["mat"] = self.dom("Matemática", "area", ids["ga"], codigo="T2")
        ids["alg"] = self.dom("Álgebra", "subarea", ids["mat"], codigo="T21")
        return ids

    def reconcile(self):
        return self.index.reconcile()
