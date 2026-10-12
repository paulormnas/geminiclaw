"""ClaimRuntime: descobertas no grafo, pendentes no checkpoint e retomada (specs: efeitos, retomada, grafo)."""


import pytest

from src.claims.runtime import ClaimRuntime
from src.claims.store import ClaimStore
from src.claims.verifier import ClaimVerifierError
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.provenance import Actor
from tests.support.curator_graph import ORQ, CuratorGraph
from tests.unit.claims.helpers import FakeVerifier, supported

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class Tracker:
    def __init__(self, hard=False, time=False):
        self.hard, self.time = hard, time

    def tokens_hard_exhausted(self):
        return self.hard

    def check(self):
        return type("S", (), {"time_exhausted": self.time})()


def world(tmp_path, verifier, tracker=None):
    graph = InMemoryGraphStore()
    cg = CuratorGraph(graph).setup_project()
    hip = cg.hipotese()
    abordagem = cg.abordagem()
    exp, res = cg.tentativa(hip, abordagem, valor=0.8, baseline=0.7)
    did = graph.create_node(
        "Descoberta",
        {**cg.base(), "tipo": "funciona", "enunciado": "O método funciona", "n_evidencias": 1, "status": "ativa",
         "justificativa_criacao": "j", "nos_consultados": []},
        actor=Actor(kind="agente", role="curator"),
    )
    graph.create_edge(did, "BASEADA_EM", res, {}, actor=ORQ)
    runtime = ClaimRuntime(
        tmp_path, graph_getter=lambda: graph, tracker_getter=lambda sid: tracker, validator=verifier,
        project_getter=lambda sid: cg.projeto_id,
    )
    return runtime, graph, did, res


def edges_snapshot(graph):
    return sorted((e.src_id, e.rel_type, e.dst_id) for e in graph._edges)  # noqa: SLF001


async def test_descoberta_gera_no_afirmacao_sem_mexer_em_evidencia(tmp_path):
    fake = FakeVerifier(lambda f, i: [supported("O método funciona", 1, ["ev2"])])
    runtime, graph, did, res = world(tmp_path, fake)
    before_res = graph.get_node(res).properties
    before_status = graph.get_node(did).properties["status"]
    claims = await runtime.verify_discoveries("s1", [did])
    assert len(claims) == 1 and claims[0].no_grafo
    node = graph.get_node(claims[0].no_grafo)
    assert node.label == "Afirmacao" and node.properties["status_afirmacao"] == "suportada"
    rels = [(e.rel_type, e.dst_id) for e in graph._edges if e.src_id == node.id]  # noqa: SLF001
    assert ("EXTRAIDA_DE", did) in rels and ("CONFERIDA_CONTRA", res) in rels
    assert graph.get_node(res).properties == before_res          # Resultado intacto
    assert graph.get_node(did).properties["status"] == before_status  # Descoberta.status intacto
    assert not any(e.rel_type in ("SUSTENTA", "REFUTA") and e.src_id == node.id for e in graph._edges)  # noqa: SLF001


async def test_contestada_nao_altera_arestas_nem_status(tmp_path):
    fake = FakeVerifier(lambda f, i: [{"texto": "x", "frase": 1, "status": "refutada", "evidencias": ["ev2"]}])
    runtime, graph, did, res = world(tmp_path, fake)
    before = edges_snapshot(graph)
    claims = await runtime.verify_discoveries("s1", [did])
    assert claims[0].status_afirmacao == "contestada"
    assert graph.get_node(did).properties["status"] == "ativa"
    after = [t for t in edges_snapshot(graph) if t[0] not in {c.no_grafo for c in claims}]
    assert after == before


async def test_orcamento_esgotado_deixa_pendente_e_nao_levanta(tmp_path):
    fake = FakeVerifier(lambda f, i: [supported("x", 1)])
    runtime, graph, did, _ = world(tmp_path, fake, tracker=Tracker(hard=True))
    claims = await runtime.verify_discoveries("s1", [did])
    assert claims[0].status_afirmacao == "pendente" and claims[0].motivo_pendencia == "orcamento_esgotado"
    assert fake.calls == []


async def test_pendentes_vao_para_o_checkpoint_e_sao_reverificadas(tmp_path):
    fail = FakeVerifier(lambda f, i: ClaimVerifierError("x"))
    runtime, graph, did, res = world(tmp_path, fail)
    claims = await runtime.verify_discoveries("s1", [did])
    assert claims[0].status_afirmacao == "pendente"
    pending = runtime.pending_for_checkpoint("s1")
    assert pending == [{"afirmacao_id": claims[0].afirmacao_id, "session_id": "s1", "conclusao_id": f"desc:{did}"}]

    ok = FakeVerifier(lambda f, i: [supported("O método funciona", 1, ["ev2"])])
    runtime2 = ClaimRuntime(
        tmp_path, graph_getter=lambda: graph, tracker_getter=lambda sid: None, validator=ok,
        project_getter=lambda sid: "proj1",
    )
    done = await runtime2.verify_previous_pending("s2", pending)
    assert len(done) == 1 and done[0].status_afirmacao == "suportada"
    reloaded = ClaimStore.load(tmp_path / "s1", "s1")
    claim = reloaded.get(claims[0].afirmacao_id)
    assert [h["status"] for h in claim.historico] == ["pendente", "suportada"]
    assert claim.historico[-1]["session_id"] == "s2"           # a sessão nova aparece no histórico
    assert graph.get_node(claim.no_grafo).properties["status_afirmacao"] == "suportada"
    assert runtime2.pending_for_checkpoint("s1") == []


async def test_sem_grafo_nao_verifica_descobertas(tmp_path):
    runtime = ClaimRuntime(tmp_path, graph_getter=lambda: (_ for _ in ()).throw(RuntimeError("sem banco")),
                           tracker_getter=lambda s: None, validator=FakeVerifier())
    assert await runtime.verify_discoveries("s1", ["x"]) == []


async def test_desligado_por_configuracao(tmp_path, monkeypatch):
    from src import config

    monkeypatch.setattr(config, "CLAIM_VERIFY_ENABLED", False)
    runtime, graph, did, _ = world(tmp_path, FakeVerifier())
    assert await runtime.verify_discoveries("s1", [did]) == []
