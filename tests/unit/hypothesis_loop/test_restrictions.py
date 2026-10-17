"""Restrições de direção (v18.7-exploration-limits, seção 7; specs ``hypothesis-loop``, ``knowledge-graph`` e
``researcher-consult``). Sem LLM, grafo em memória."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.validator.agent import ValidatorAgent
from src.cli.project import handle_project_command
from src.gate.types import GateAuthorizationRefused
from src.knowledge import restrictions as rs
from src.knowledge.errors import HumanConfirmationRequiredError
from src.knowledge.provenance import Actor
from src.orchestration.exploration import ExplorationSession
from tests.support import exploration_graph as eg
from tests.support.exploration_world import LoopHarness, hyp, plan, task
from tests.support.fake_gate import FakeGate
from tests.support.hypothesis_world import AGENTE, ORQ, PESQUISADOR, HypothesisWorld

pytestmark = pytest.mark.unit

CURATOR = Actor(kind="agente", role="curator")


@pytest.fixture
def world() -> HypothesisWorld:
    return HypothesisWorld()


def restrict(world, **kw):
    kw.setdefault("direcao", "uso de reagente perigoso")
    kw.setdefault("categoria", "seguranca")
    return rs.create_restriction(world.store, world.pid, **kw)


def with_approach(world, name="sintese_com_reagente_x", enunciado="H"):
    hid = eg.hipotese(world, enunciado=enunciado)
    approach = world.graph.abordagem(nome=name)
    world.store.create_edge(hid, "PROPOE", approach, {}, actor=AGENTE)
    return hid


# --- 7.1 registro e leitura -------------------------------------------------------------------------------------------


def test_criacao_pelo_pesquisador_liga_ao_projeto(world):
    """Scenario: Criação pelo pesquisador."""
    rid = restrict(world, abordagens=["Sintese_Com_Reagente_X"])
    node = world.raw.get_node(rid)
    assert node.properties["status"] == "ativa" and node.properties["decidida_por"] == "pesquisador"
    (item,) = rs.list_restrictions(world.store, world.pid)
    assert item.escopo == "projeto" and item.abordagens == ("sintese_com_reagente_x",)
    assert any(a["actor"] == "pesquisador" for a in world.raw.audit_log) or node.properties["criado_por"] == "pesquisador"


def test_restricao_do_problema(world):
    restrict(world, problema=True)
    assert rs.list_restrictions(world.store, world.pid)[0].escopo == "problema"


def test_categoria_invalida_e_direcao_vazia(world):
    with pytest.raises(rs.RestrictionError):
        restrict(world, categoria="gosto")
    with pytest.raises(rs.RestrictionError):
        restrict(world, direcao="   ")


def test_revogacao_nao_apaga(world):
    """Scenario: Revogação não apaga."""
    rid = restrict(world)
    rs.revoke_restriction(world.store, rid)
    assert world.raw.get_node(rid).properties["status"] == "revogada"
    assert rs.active_restrictions(world.store, world.pid) == []


@pytest.mark.parametrize("actor", [CURATOR, AGENTE, ORQ])
def test_agente_e_orquestrador_nao_criam_restricao(world, actor):
    """Scenarios: Agente não cria restrição; Orquestrador sem pedido autorizado é recusado."""
    props = world.base(direcao="d", categoria="etica", status="ativa", decidida_por="pesquisador", decidida_em="x")
    if actor.kind == "agente":
        props.update(justificativa_criacao="t", nos_consultados=[])
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.create_node("Restricao", props, actor=actor)
    assert world.raw.find_nodes("Restricao", {}) == []


# --- 7.5 autoridade da sessão -----------------------------------------------------------------------------------------


def gate_with_request(world, answer="restringir", consume=False):
    gate = FakeGate()
    request = gate.request("restringir_direcao", "t3", "p", ("restringir", "liberar"), motivo="restricao_duvidosa",
                           session_id=world.sid)
    gate.respond(request.id, resposta={"acao": answer})
    return gate, request


def test_sessao_cria_restricao_com_o_pedido_consumido(world):
    """Scenario: Resposta do pesquisador cria a restrição (pedido_id igual ao id do pedido)."""
    gate, request = gate_with_request(world)
    rid = rs.create_from_request(world.store, gate, [world.sid], "t3", world.pid, direcao="d", categoria="recurso")
    assert world.raw.get_node(rid).properties["pedido_id"] == request.id and gate.get(request.id).consumido
    assert rs.list_restrictions(world.store, world.pid)[0].escopo == "problema"


def test_pedido_ja_consumido_nao_cria_segunda_restricao(world):
    """Scenario: Pedido já consumido não cria segunda restrição."""
    gate, _ = gate_with_request(world)
    rs.create_from_request(world.store, gate, [world.sid], "t3", world.pid, direcao="d", categoria="recurso")
    with pytest.raises(GateAuthorizationRefused):
        rs.create_from_request(world.store, gate, [world.sid], "t3", world.pid, direcao="d2", categoria="recurso")
    assert len(world.raw.find_nodes("Restricao", {})) == 1


def test_liberar_nao_cria_restricao(world):
    """Scenario: Liberar não cria restrição."""
    gate, _ = gate_with_request(world, answer="liberar")
    with pytest.raises(rs.RestrictionError):
        rs.create_from_request(world.store, gate, [world.sid], "t3", world.pid, direcao="d", categoria="recurso")
    assert world.raw.find_nodes("Restricao", {}) == []


def test_sessao_sem_pedido_id_e_recusada(world):
    """Scenario: Sessão sem pedido_id."""
    props = world.base(direcao="d", categoria="etica", status="ativa", decidida_por="pesquisador", decidida_em="x")
    with pytest.raises(HumanConfirmationRequiredError, match="pedido_id"):
        world.store.create_node("Restricao", props, actor=Actor.under_request(7))
    props["pedido_id"] = 8  # outro pedido
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.create_node("Restricao", props, actor=Actor.under_request(7))


def test_pedido_de_sessao_sem_autorizacao_nao_cria(world):
    gate = FakeGate()
    gate.request("restringir_direcao", "t3", "p", ("restringir", "liberar"), motivo="restricao_duvidosa",
                 session_id=world.sid)
    with pytest.raises(GateAuthorizationRefused):
        rs.create_from_request(world.store, gate, [world.sid], "t3", world.pid, direcao="d", categoria="recurso")


def test_abandono_com_restricao_ativa(world):
    """Scenario: Retirada com restrição ativa — aceita e a trilha cita a restrição."""
    rid = restrict(world)
    hid = eg.hipotese(world)
    rs.withdraw_hypothesis(world.store, hid, rid)
    props = world.raw.get_node(hid).properties
    assert props["abandonada_por"] == "pesquisador" and props["motivo_abandono"] == f"direcao_restrita:{rid}"
    assert any(f"direcao_restrita:{rid}" in str(a["changes"]) for a in world.raw.audit_log)


def test_restricao_revogada_ou_inexistente_nao_autoriza(world):
    """Scenarios: Restrição revogada não autoriza; Restrição inexistente."""
    rid = restrict(world)
    rs.revoke_restriction(world.store, rid)
    hid = eg.hipotese(world)
    with pytest.raises(HumanConfirmationRequiredError):
        rs.withdraw_hypothesis(world.store, hid, rid)
    with pytest.raises(HumanConfirmationRequiredError):
        rs.withdraw_hypothesis(world.store, hid, "r_inexistente")
    assert world.raw.get_node(hid).properties["status"] == "proposta"


def test_derivacao_nao_vale_para_outras_escritas(world):
    """A derivação da restrição só cobre a retirada: nada de reabrir, mudar enunciado ou outro rótulo."""
    rid = restrict(world)
    hid = eg.hipotese(world)
    actor = Actor.under_restriction(rid)
    for changes in ({"status": "validada"}, {"enunciado": "outro"}, {"status": "abandonada"}):
        with pytest.raises(HumanConfirmationRequiredError):
            world.store.update_node(hid, changes, actor=actor)
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(world.problem.id, {"resumo": "x"}, actor=actor)


# --- 7.1 casamento ----------------------------------------------------------------------------------------------------


def test_casamento_por_abordagem(world):
    rid = restrict(world, abordagens=["sintese_com_reagente_x"])
    hid = with_approach(world)
    from src.knowledge.service import KnowledgeService

    found = rs.match_hypothesis(
        world.store, KnowledgeService(world.store), None, world.raw.get_node(hid), rs.active_restrictions(world.store, world.pid)
    )
    assert found is not None and found.restricao_id == rid and found.criterio == "abordagem"


def test_casamento_por_similaridade_usa_o_limiar():
    world = HypothesisWorld(index=True)
    restrict(world, direcao="uso de reagente perigoso")
    hid = eg.hipotese(world, enunciado="H2")
    node = world.raw.get_node(hid)
    active = rs.active_restrictions(world.store, world.pid)
    with patch.object(world.index, "text_similarity", return_value=0.86):
        found = rs.match_hypothesis(world.store, None, world.index, node, active)
    assert found.criterio == "similaridade" and found.similaridade == 0.86
    with patch.object(world.index, "text_similarity", return_value=0.5):
        assert rs.match_hypothesis(world.store, None, world.index, node, active) is None


# --- 7.2 comandos -----------------------------------------------------------------------------------------------------


def test_comandos_restrict_restrictions_unrestrict(world):
    """Scenario: Criação pelo pesquisador / Revogação não apaga (pela CLI)."""
    out: list[str] = []
    code = handle_project_command(
        ["restrict", world.pid, "--direcao", "uso de reagente perigoso", "--categoria", "seguranca",
         "--abordagem", "sintese_com_reagente_x"], world.store, output_fn=out.append,
    )
    assert code == 0 and out[0].startswith("Restrição criada: ")
    rid = out[0].split(": ")[1]
    out.clear()
    handle_project_command(["restrictions", world.pid], world.store, output_fn=out.append)
    assert rid in out[0] and "ativa" in out[0] and "uso de reagente perigoso" in out[1]
    out.clear()
    handle_project_command(["unrestrict", rid], world.store, output_fn=out.append)
    assert world.raw.get_node(rid).properties["status"] == "revogada"
    out.clear()
    assert handle_project_command(["restrict", world.pid, "--direcao", "x", "--categoria", "etica", "--problema"],
                                  world.store, output_fn=out.append) == 0


# --- 7.3 Validator ----------------------------------------------------------------------------------------------------


def llm(text):
    provider = MagicMock()
    provider.generate = AsyncMock(return_value=MagicMock(text=text, usage=None, model="m", tokens_in=0, tokens_out=0))
    return provider


PLAN = [{"agent_id": "developer", "task_name": "t3", "prompt": "p", "validation_criteria": ["c"]}]


@pytest.mark.asyncio
async def test_validator_do_plano_devolve_casos_duvidosos_validos():
    reply = ('{"status": "approved", "reason": "ok", "issues": [], "restricoes_duvidosas": ['
             '{"task_name": "t3", "restricao_id": "r1", "motivo": "parece"},'
             '{"task_name": "inexistente", "restricao_id": "r1"}, {"task_name": "t3", "restricao_id": "r9"}]}')
    agent = ValidatorAgent(provider=llm(reply))
    result = await agent.validate_plan(PLAN, "p", restrictions=[{"id": "r1", "direcao": "d"}])
    assert result.is_valid and result.restricoes_duvidosas == [
        {"task_name": "t3", "restricao_id": "r1", "motivo": "parece"}
    ]
    prompt = agent.provider.generate.await_args.kwargs
    assert "RESTRIÇÕES DE DIREÇÃO ATIVAS" in str(prompt["messages"][0]) and "restricoes_duvidosas" in prompt["system"]


@pytest.mark.asyncio
async def test_validator_sem_restricoes_nao_pede_o_campo():
    agent = ValidatorAgent(provider=llm('{"status": "approved", "reason": "ok", "issues": []}'))
    result = await agent.validate_plan(PLAN, "p")
    assert result.restricoes_duvidosas == [] and "restricoes_duvidosas" not in agent.provider.generate.await_args.kwargs["system"]


@pytest.mark.asyncio
async def test_revisao_com_violacao_nao_valida_e_registra_o_motivo(tmp_path):
    """Scenario: Violação na revisão — não validado, motivo ``direcao_restrita``, tentativa não refeita."""
    agent = ValidatorAgent(provider=llm('{"status": "pass", "feedback": "ok", "issues": [], "viola_restricao": "r1"}'))
    task_ = MagicMock(
        task_name="t3", expected_artifacts=[], validation_criteria=["o modelo foi treinado"], depends_on=[],
        hypothesis_id=None, hypothesis_origin=None, agent_id="developer",
        restricoes_contexto=[{"id": "r1", "direcao": "d"}], concorrentes_contexto=[], discrimina=[],
    )
    result = await agent.review_result(task_, "feito", output_dir=tmp_path)
    assert result.is_approved and result.verified is False
    assert result.viola_restricao == "r1" and "direcao_restrita" in result.motivos


@pytest.mark.asyncio
async def test_revisao_ignora_restricao_que_nao_foi_entregue(tmp_path):
    agent = ValidatorAgent(provider=llm('{"status": "pass", "feedback": "ok", "issues": [], "viola_restricao": "r9"}'))
    task_ = MagicMock(
        task_name="t3", expected_artifacts=[], validation_criteria=["c"], depends_on=[], hypothesis_id=None,
        hypothesis_origin=None, agent_id="developer", restricoes_contexto=[{"id": "r1"}], concorrentes_contexto=[],
        discrimina=[],
    )
    result = await agent.review_result(task_, "feito", output_dir=tmp_path)
    assert result.viola_restricao is None and result.verified


# --- 7.2/7.3 aplicação no laço ----------------------------------------------------------------------------------------


def make_harness(tmp_path, *, abordagem=True, index=False):
    h = LoopHarness(tmp_path, plans=[plan([task("t1", "h1")], [hyp("h1")])], world_kw={"index": index})
    return h


@pytest.mark.asyncio
async def test_laco_retira_hipotese_por_abordagem(tmp_path):
    """Scenario: Retirada por abordagem — hipótese abandonada pelo pesquisador, subtarefa não executa."""
    plans = [plan([task("t1", "h1")], [hyp("h1")])]
    h = LoopHarness(tmp_path, plans=plans)
    events: list[tuple[str, dict]] = []
    restrict(h.w, abordagens=["abordagem_x"])
    declared = plan([task("t1", "h1")], [hyp("h1")])
    h.plans = [declared]
    with patch.object(ExplorationSession, "_emit", autospec=True, side_effect=lambda s, k, p: events.append((k, p))), \
            patch("src.knowledge.restrictions.hypothesis_approaches", return_value=["abordagem_x"]), \
            patch("src.gate.persistent_gate.session_gate", return_value=FakeGate()):
        await h.run()
    assert h.ran == []
    (event,) = [p for k, p in events if k == "restricao_retirada"]
    assert event["criterio"] == "abordagem"
    abandoned = [n for n in h.hypotheses() if n.properties.get("status") == "abandonada"]
    assert abandoned and abandoned[0].properties["abandonada_por"] == "pesquisador"
    assert abandoned[0].properties["motivo_abandono"].startswith("direcao_restrita:")


@pytest.mark.asyncio
async def test_laco_com_restricao_revogada_nao_retira(tmp_path):
    """Scenario: Restrição revogada."""
    h = LoopHarness(tmp_path, plans=[plan([task("t1", "h1")], [hyp("h1")])])
    rs.revoke_restriction(h.w.store, restrict(h.w, abordagens=["abordagem_x"]))
    with patch("src.knowledge.restrictions.hypothesis_approaches", return_value=["abordagem_x"]), \
            patch("src.gate.persistent_gate.session_gate", return_value=FakeGate()):
        await h.run()
    assert h.ran == ["t1"]


@pytest.mark.asyncio
async def test_laco_caso_duvidoso_vira_pedido_e_retira_a_subtarefa(tmp_path):
    """Scenario: Caso duvidoso — ``hipotese_aguarda_decisao_restricao`` e pedido ``restricao_duvidosa``."""
    h = LoopHarness(tmp_path, plans=[plan([task("t1", "h1")], [hyp("h1")])])
    rid = restrict(h.w)
    gate = FakeGate()
    seen: dict[str, str] = {}
    original = ExplorationSession.apply_restrictions

    def spy(self, live, dropped):
        self.note_plan_doubts([{"task_name": "t1", "restricao_id": rid, "motivo": "parece"}])
        original(self, live, dropped)
        seen.update(dropped)

    with patch.object(ExplorationSession, "apply_restrictions", spy), \
            patch("src.gate.persistent_gate.session_gate", return_value=gate):
        await h.run()
    assert seen["t1"] == "hipotese_aguarda_decisao_restricao"
    (request,) = [r for r in gate.requests if r.decisao == "restringir_direcao"]
    assert request.motivo == "restricao_duvidosa" and request.referencia == f"{rid}:t1"


def test_resposta_restringir_cria_restricao_e_liberar_libera(world):
    """Scenarios: Resposta do pesquisador cria a restrição / Liberar não cria restrição (pela sessão)."""
    ctx = world.ctx
    session = ExplorationSession(lambda: world.store, ctx, MagicMock(), mode="auto")
    gate = FakeGate()
    ask = lambda ref: gate.request("restringir_direcao", ref, "p", ("restringir", "liberar"),  # noqa: E731
                                   motivo="restricao_duvidosa", session_id=world.sid)
    first, second = ask("r1:t3"), ask("r1:t4")
    gate.respond(first.id, resposta={"acao": "restringir"})
    gate.respond(second.id, resposta={"acao": "liberar"})
    session._doubt_context = {"r1:t3": {"direcao": "linha do reagente X", "categoria": "seguranca", "abordagens": []}}
    with patch("src.gate.persistent_gate.session_gate", return_value=gate):
        session._apply_answers()
    (created,) = rs.list_restrictions(world.store, world.pid)
    assert created.direcao == "linha do reagente X" and created.pedido_id == first.id
    assert "r1:t4" in session._released and gate.get(second.id).consumido
    assert not [r for r in world.raw.find_nodes("Restricao", {}) if r.id != created.id]


def test_reabertura_pelo_pesquisador_de_hipotese_retirada(world):
    """Design §8.2: só o pesquisador (graph edit) reabre a hipótese retirada por restrição."""
    rid = restrict(world)
    hid = eg.hipotese(world)
    rs.withdraw_hypothesis(world.store, hid, rid)
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(hid, {"status": "proposta"}, actor=ORQ)
    rs.revoke_restriction(world.store, rid)
    assert world.raw.get_node(hid).properties["status"] == "abandonada"  # revogar não reabre
    world.store.update_node(hid, {"status": "proposta", "abandonada_por": None, "motivo_abandono": None},
                            actor=PESQUISADOR)
    assert world.raw.get_node(hid).properties["status"] == "proposta"
