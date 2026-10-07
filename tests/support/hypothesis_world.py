"""Mundo de teste do ciclo de hipóteses (v18-hypothesis-loop): projeto com Problema confirmado no grafo em memória.

Sem rede, sem LLM, sem banco. ``index=True`` liga um ``SemanticIndex`` com ``ControlledEmbeddingProvider``
(similaridades exatas definidas pelo teste).
"""

from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient

from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.indexed_store import IndexedGraphStore
from src.knowledge.ingestion import SessionContext, ingest_session_start
from src.knowledge.projects import confirm_problem, create_project, get_active_problem
from src.knowledge.provenance import Actor
from src.knowledge.semantic_index import SemanticIndex
from tests.support.controlled_embedding_provider import ControlledEmbeddingProvider
from tests.support.curator_graph import CuratorGraph
from tests.unit.research_project.test_projects import make_draft

ORQ = Actor(kind="orquestrador")
PESQUISADOR = Actor(kind="pesquisador")
AGENTE = Actor(kind="agente", role="researcher")
CURATOR = Actor(kind="agente", role="curator")
DIM = 64


class HypothesisWorld:
    """Projeto, Problema confirmado (alvo 0,8; delta_min 0,05), sessão e atalhos para montar nós."""

    def __init__(self, *, mode: str = "auto", index: bool = False, alvo: float | None = 0.8,
                 delta_min: float = 0.05, session_id: str = "sessao-h") -> None:
        self.raw = InMemoryGraphStore()
        self.provider: ControlledEmbeddingProvider | None = None
        self.index: SemanticIndex | None = None
        if index:
            self.provider = ControlledEmbeddingProvider(dimension=DIM)
            self.index = SemanticIndex(self.raw, QdrantClient(location=":memory:"), provider=self.provider)
            self.store: Any = IndexedGraphStore(self.raw, self.index)
        else:
            self.store = self.raw
        self.pid = create_project(self.store, "Projeto X", "Objetivo X", [])
        confirm_problem(
            self.store, self.pid, make_draft(alvo=alvo, delta_min=delta_min), sentido_metrica="maior_melhor"
        )
        self.problem = get_active_problem(self.store, self.pid)
        assert self.problem is not None
        self.sid = session_id
        self.ctx = SessionContext(self.pid, self.sid, mode, "2026-10-07T00:00:00+00:00", "no")
        self.session_node = ingest_session_start(self.store, self.ctx)
        self.graph = CuratorGraph(self.store, self.pid, self.sid)
        self.graph.projeto = self.store.find_nodes("Projeto", {"projeto_id": self.pid}, limit=1)[0].id
        self.graph.problema = self.problem.id
        self.graph.metrica = self.store.find_nodes("Metrica", {}, limit=5)[0].id

    def base(self, **extra: Any) -> dict[str, Any]:
        return {"projeto_id": self.pid, "sessao_id": self.sid, **extra}

    def hypothesis(
        self, enunciado: str = "H1", *, status: str = "proposta", origem: str = "researcher", sobre: bool = True,
        actor: Actor | None = None,
    ) -> str:
        """Hipótese do projeto (por padrão do Researcher, ``proposta``, ``SOBRE`` o Problema)."""
        by = actor or (PESQUISADOR if origem == "pesquisador" else AGENTE)
        props = self.base(enunciado=enunciado, justificativa="J", status=status, origem=origem)
        if by.kind == "agente":
            props.update(justificativa_criacao="teste", nos_consultados=[])
        hid = self.store.create_node("Hipotese", props, actor=by)
        if sobre:
            self.store.create_edge(hid, "SOBRE", self.problem.id, {}, actor=ORQ)
        return hid

    def opportunity(self, enunciado: str = "Testar X", status: str = "documentada") -> str:
        """Oportunidade (``documentada`` pelo Curator; outros estados só pelo pesquisador)."""
        if status == "documentada":
            return self.store.create_node(
                "Oportunidade",
                self.base(enunciado=enunciado, justificativa="J", status=status,
                          justificativa_criacao="teste", nos_consultados=[]),
                actor=CURATOR,
            )
        return self.store.create_node(
            "Oportunidade", self.base(enunciado=enunciado, justificativa="J", status=status), actor=PESQUISADOR
        )

    def discovery(self, tipo: str = "caminho_sem_conclusao", **extra: Any) -> str:
        props = self.base(**{"tipo": tipo, "enunciado": "E", "n_evidencias": 1, "status": "ativa", **extra})
        props.update(justificativa_criacao="teste", nos_consultados=[])
        return self.store.create_node("Descoberta", props, actor=CURATOR)

    def attempt(self, hypothesis_id: str, valor: float = 0.85, baseline: float | None = 0.7, **kw: Any) -> str | None:
        """Tentativa validada (Experimento + Resultado) ligada à hipótese; devolve o ``Resultado``."""
        _, res = self.graph.tentativa(hypothesis_id, None, valor=valor, baseline=baseline, **kw)
        return res
