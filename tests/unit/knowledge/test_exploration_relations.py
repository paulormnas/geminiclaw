"""Relações de exploração no grafo (v18.7-graph-exploration-relations): cada teste cita o cenário da spec.

Tudo em ``InMemoryGraphStore``; nenhum teste chama provedor LLM, rede ou banco.
"""

from __future__ import annotations

import pytest

from src.knowledge.change_proposals import CONFIRM_WORD, apply_plan, issue_confirmation, parse_ops, plan_changes
from src.knowledge.errors import (
    DisallowedRelationError,
    HumanConfirmationRequiredError,
    ImmutableFieldError,
    InvalidEnumValueError,
    InvalidPropertyValueError,
    MissingRequiredPropertyError,
    SelfRelationNotAllowedError,
)
from src.knowledge.exploration_reads import abandoned_by, experiment_role, structured_key
from src.knowledge.ingestion import ACTOR_ORQUESTRADOR
from src.knowledge.provenance import Actor
from src.knowledge.service import KnowledgeService
from tests.support import exploration_graph as eg
from tests.support.graph_cli_world import PID, World
from tests.support.hypothesis_world import AGENTE, ORQ, PESQUISADOR, HypothesisWorld

pytestmark = pytest.mark.unit

CURATOR = Actor(kind="agente", role="curator")
CHAVE = "prb_1|abd_2|met_3"


@pytest.fixture
def world() -> HypothesisWorld:
    return HypothesisWorld()


def _system_hypothesis_props(world: HypothesisWorld, **over):
    props = world.base(
        enunciado="H do sistema", justificativa="J", status="proposta", origem="sistema",
        chave_estruturada=CHAVE, referencia_fixada=eg.referencia_fixada(metrica_id="met_3"),
    )
    props.update(over)
    return props


# --- Papel do experimento ---------------------------------------------------------------------------------------


def test_papel_valido(world):
    """Scenario: Papel válido."""
    node = world.store.get_node(eg.experimento(world, papel="preparacao"))
    assert experiment_role(node) == "preparacao"


def test_papel_invalido(world):
    """Scenario: Papel inválido."""
    with pytest.raises(InvalidEnumValueError) as error:
        eg.experimento(world, papel="exploracao")
    for value in ("teste", "preparacao", "referencia"):
        assert value in str(error.value)


def test_experimento_antigo_sem_papel(world):
    """Scenario: Experimento antigo sem papel (o nó não é reescrito)."""
    node = world.store.get_node(eg.experimento(world))
    assert experiment_role(node) == "teste"
    assert "papel" not in world.store.get_node(node.id).properties


# --- Hipótese do sistema ----------------------------------------------------------------------------------------


def test_hipotese_do_sistema_completa(world):
    """Scenario: Hipótese do sistema completa (e a busca exata pela chave)."""
    props = _system_hypothesis_props(world)
    props["referencia_fixada"] = {
        "valor": 0.62, "origem_referencia": "referencia_medida", "metrica_id": "met_3", "resultado_id": "res_9",
        "fixada_em": "2026-10-20T12:00:00+00:00",
    }
    hid = world.store.create_node("Hipotese", props, actor=ORQ)
    found = world.store.find_nodes("Hipotese", {"chave_estruturada": CHAVE})
    assert [n.id for n in found] == [hid]


def test_hipotese_do_sistema_sem_chave(world):
    """Scenario: Hipótese do sistema sem chave (o campo é indicado)."""
    props = _system_hypothesis_props(world)
    del props["chave_estruturada"]
    with pytest.raises(MissingRequiredPropertyError) as error:
        world.store.create_node("Hipotese", props, actor=ORQ)
    assert error.value.prop == "chave_estruturada"


def test_hipotese_do_sistema_sem_referencia(world):
    props = _system_hypothesis_props(world)
    del props["referencia_fixada"]
    with pytest.raises(MissingRequiredPropertyError) as error:
        world.store.create_node("Hipotese", props, actor=ORQ)
    assert error.value.prop == "referencia_fixada"


@pytest.mark.parametrize("chave", ["prb_1|abd 2; MATCH (n)|met_3", "a|b", "a|b|c|d", "a||c", "a|b|" + "x" * 129])
def test_chave_com_componente_invalido(world, chave):
    """Scenario: Chave com componente inválido."""
    with pytest.raises(InvalidPropertyValueError) as error:
        world.store.create_node("Hipotese", _system_hypothesis_props(world, chave_estruturada=chave), actor=ORQ)
    assert error.value.prop == "chave_estruturada"


def test_referencia_mal_formada(world):
    """Scenario: Referência mal formada (o campo ``referencia_fixada.valor`` é indicado)."""
    bad = {"valor": "alto", "origem_referencia": "referencia_medida", "metrica_id": "met_3",
           "fixada_em": "2026-10-20T12:00:00+00:00"}
    with pytest.raises(InvalidPropertyValueError) as error:
        world.store.create_node("Hipotese", _system_hypothesis_props(world, referencia_fixada=bad), actor=ORQ)
    assert error.value.prop == "referencia_fixada.valor"


@pytest.mark.parametrize(
    "mapa",
    [
        {"valor": float("nan"), "origem_referencia": "criterio_problema", "metrica_id": "m", "fixada_em": "t"},
        {"valor": True, "origem_referencia": "criterio_problema", "metrica_id": "m", "fixada_em": "t"},
        {"valor": 1, "origem_referencia": "outra", "metrica_id": "m", "fixada_em": "t"},
        {"valor": 1, "origem_referencia": "criterio_problema", "metrica_id": "m", "fixada_em": "t", "extra": 1},
        {"valor": 1, "origem_referencia": "criterio_problema", "metrica_id": "m", "fixada_em": "t", "resultado_id": "r"},
        {"valor": 1, "origem_referencia": "referencia_medida", "metrica_id": "m", "fixada_em": "t"},
        {"valor": None, "origem_referencia": "criterio_problema", "metrica_id": "m", "fixada_em": "t"},
        {"valor": 1, "origem_referencia": "criterio_problema", "fixada_em": "t"},
        "texto",
    ],
)
def test_referencia_fora_da_forma_e_recusada(world, mapa):
    with pytest.raises(Exception) as error:
        world.store.create_node("Hipotese", _system_hypothesis_props(world, referencia_fixada=mapa), actor=ORQ)
    assert type(error.value).__name__ in {
        "InvalidPropertyValueError", "InvalidEnumValueError", "MissingRequiredPropertyError",
    }


def test_referencia_indisponivel_com_valor_nulo(world):
    mapa = eg.referencia_fixada(valor=None, origem="indisponivel", metrica_id="met_3")
    hid = world.store.create_node("Hipotese", _system_hypothesis_props(world, referencia_fixada=mapa), actor=ORQ)
    assert world.store.get_node(hid).properties["referencia_fixada"]["valor"] is None


def test_referencia_nao_muda(world):
    """Scenario: Referência não muda."""
    hid = eg.hipotese(world, origem="sistema")
    novo = eg.referencia_fixada(valor=0.70)
    with pytest.raises(ImmutableFieldError):
        world.store.update_node(hid, {"referencia_fixada": novo}, actor=ORQ)


def test_chave_nao_muda(world):
    hid = eg.hipotese(world, origem="sistema")
    with pytest.raises(ImmutableFieldError):
        world.store.update_node(hid, {"chave_estruturada": CHAVE}, actor=ORQ)


def test_chave_nao_pode_ser_acrescentada_depois(world):
    """Scenario: Chave não pode ser acrescentada depois."""
    hid = eg.hipotese(world, origem="researcher")
    with pytest.raises(ImmutableFieldError):
        world.store.update_node(hid, {"chave_estruturada": CHAVE}, actor=ORQ)


def test_chave_so_nasce_em_hipotese_do_sistema(world):
    props = world.base(enunciado="H", justificativa="J", status="proposta", origem="pesquisador",
                       chave_estruturada=CHAVE)
    with pytest.raises(InvalidPropertyValueError):
        world.store.create_node("Hipotese", props, actor=PESQUISADOR)


def test_chave_estruturada_pelo_construtor(world):
    assert structured_key("prb_1", "abd_2", "met_3") == CHAVE
    with pytest.raises(ValueError):
        structured_key("prb 1", "abd_2", "met_3")


def test_motivo_do_abandono_tem_limite(world):
    hid = eg.hipotese(world, origem="sistema")
    with pytest.raises(InvalidPropertyValueError):
        world.store.update_node(hid, {"motivo_abandono": "x" * 501}, actor=ORQ)


# --- Autor do abandono ------------------------------------------------------------------------------------------


def test_orquestrador_nao_grava_abandono_do_pesquisador(world):
    """Scenario: Orquestrador não grava abandono do pesquisador."""
    hid = eg.hipotese(world)
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(hid, {"status": "abandonada", "abandonada_por": "pesquisador"}, actor=ORQ)


def test_orquestrador_nao_reabre_hipotese_abandonada_pelo_pesquisador(world):
    """Scenario: Orquestrador não reabre hipótese abandonada pelo pesquisador."""
    hid = eg.hipotese(world, status="abandonada", abandonada_por="pesquisador")
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(hid, {"status": "em_teste"}, actor=ORQ)
    assert world.store.get_node(hid).properties["status"] == "abandonada"


def test_abandono_pelo_sistema(world):
    """Scenario: Abandono pelo sistema (a auditoria guarda a mudança)."""
    hid = eg.hipotese(world, origem="sistema")
    changes = {"status": "abandonada", "abandonada_por": "sistema", "motivo_abandono": "subtarefa_retirada"}
    world.store.update_node(hid, changes, actor=ORQ)
    assert world.store.get_node(hid).properties["abandonada_por"] == "sistema"
    assert any(e["node_id"] == hid and e["changes"].get("motivo_abandono") == "subtarefa_retirada"
               for e in world.store.audit_log)


def test_abandono_antigo_com_rejeicao_do_pesquisador(world):
    """Scenario: Hipótese abandonada antiga com rejeição do pesquisador (o nó não é reescrito)."""
    hid = eg.hipotese(world, status="abandonada")
    world.store.record_audit_note(hid, PESQUISADOR, {"decisao": "rejeitada", "motivo": "fora do escopo"})
    node = world.store.get_node(hid)
    assert abandoned_by(node, world.store.audit_history(hid)) == "pesquisador"
    assert "abandonada_por" not in world.store.get_node(hid).properties


def test_abandono_antigo_sem_nota_de_rejeicao(world):
    """Scenario: Hipótese abandonada antiga sem nota de rejeição (alternativa descartada pelo Researcher)."""
    hid = eg.hipotese(world, status="abandonada")
    node = world.store.get_node(hid)
    assert abandoned_by(node, world.store.audit_history(hid)) == "agente"
    assert "abandonada_por" not in world.store.get_node(hid).properties


def test_abandono_pelo_agente_nao_bloqueia(world):
    """Scenario: Abandono pelo agente não bloqueia."""
    hid = eg.hipotese(world, status="abandonada", abandonada_por="agente")
    world.store.update_node(hid, {"status": "proposta"}, actor=ORQ)
    assert world.store.get_node(hid).properties["status"] == "proposta"


def test_autor_do_abandono_de_hipotese_nao_abandonada(world):
    hid = eg.hipotese(world)
    assert abandoned_by(world.store.get_node(hid), []) is None


def test_valor_gravado_vale_e_inconsistencia_vai_ao_log(world, caplog):
    hid = eg.hipotese(world, status="abandonada", abandonada_por="agente")
    world.store.record_audit_note(hid, PESQUISADOR, {"decisao": "rejeitada"})
    with caplog.at_level("WARNING"):
        autor = abandoned_by(world.store.get_node(hid), world.store.audit_history(hid))
    assert autor == "agente"
    assert any("abandonada_por diferente" in r.getMessage() for r in caplog.records)


def test_pesquisador_sem_nota_e_valido(world, caplog):
    hid = eg.hipotese(world, status="abandonada", abandonada_por="pesquisador")
    with caplog.at_level("WARNING"):
        assert abandoned_by(world.store.get_node(hid), []) == "pesquisador"
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


# --- Autoridade em todos os caminhos de escrita ---------------------------------------------------------------


@pytest.fixture
def abandonada_pelo_pesquisador(world):
    return eg.hipotese(world, status="abandonada", abandonada_por="pesquisador")


def test_ferramenta_do_curator(world, abandonada_pelo_pesquisador):
    """Scenario: Ferramenta do Curator (ator de agente)."""
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(abandonada_pelo_pesquisador, {"status": "proposta"}, actor=CURATOR)
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(abandonada_pelo_pesquisador, {"abandonada_por": "agente"}, actor=CURATOR)


def test_ingestao(world, abandonada_pelo_pesquisador):
    """Scenario: Ingestão (o ator da ingestão é o orquestrador)."""
    assert ACTOR_ORQUESTRADOR.kind == "orquestrador"
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(abandonada_pelo_pesquisador, {"status": "em_teste"}, actor=ACTOR_ORQUESTRADOR)


def test_knowledge_service(world, abandonada_pelo_pesquisador):
    """Scenario: KnowledgeService (o ator do serviço é o orquestrador)."""
    service = KnowledgeService(world.store)
    hid = eg.hipotese(world)
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(hid, {"abandonada_por": "pesquisador"}, actor=service._actor)  # noqa: SLF001


def test_ator_declarado_pelo_llm_e_ignorado(world, abandonada_pelo_pesquisador):
    """Scenario: Ator declarado pelo LLM é ignorado (o formato da proposta nem aceita o campo ``actor``)."""
    from src.knowledge.change_proposals import ProposalError

    with pytest.raises(ProposalError):
        parse_ops([{"op": "update_node", "id": abandonada_pelo_pesquisador, "changes": {"status": "proposta"},
                    "motivo": "m", "actor": "pesquisador"}])
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(
            abandonada_pelo_pesquisador, {"abandonada_por": "pesquisador", "status": "abandonada"}, actor=AGENTE
        )


def test_edicao_confirmada_pelo_pesquisador():
    """Scenario: Edição confirmada pelo pesquisador (``graph edit``; a auditoria registra o pesquisador)."""
    w = World()
    hid = w.ids["hipotese"]
    w.store.update_node(hid, {"status": "abandonada", "abandonada_por": "pesquisador"}, actor=PESQUISADOR)
    ops = parse_ops([{"op": "update_node", "id": hid, "changes": {"status": "proposta"}, "motivo": "reaberta"}])
    plan = plan_changes(w.store, ops, project_id=PID)
    assert plan.ok, plan.errors
    confirmation = issue_confirmation(plan, CONFIRM_WORD, tty=True)
    apply_plan(w.store, plan, request="reabrir a hipótese", confirmation=confirmation)
    assert w.store.get_node(hid).properties["status"] == "proposta"
    assert any(e["node_id"] == hid and e["actor"] == "pesquisador" and e["changes"].get("status") == "proposta"
               for e in w.store.audit_log)


# --- Relações ---------------------------------------------------------------------------------------------------


def test_preparacao_de_hipotese(world):
    """Scenario: Preparação de hipótese."""
    hid = eg.hipotese(world)
    eid = eg.experimento(world, papel="preparacao", prepara=(hid,))
    edges = [e for e in world.store._edges if e.rel_type == "PREPARA"]  # noqa: SLF001
    assert [(e.src_id, e.dst_id, e.properties["origem"]) for e in edges] == [(eid, hid, "derivado")]


def test_preparacao_sem_hipotese(world):
    """Scenario: Preparação sem hipótese."""
    eid = eg.experimento(world, papel="preparacao", prepara=(world.problem.id,))
    assert any(e.src_id == eid and e.dst_id == world.problem.id and e.rel_type == "PREPARA"
               for e in world.store._edges)  # noqa: SLF001


def test_prepara_origem_errada(world):
    """Scenario: Origem errada (``PREPARA`` só parte de ``Experimento``)."""
    hid = eg.hipotese(world)
    rid = eg.resultado(world, eg.experimento(world))
    with pytest.raises(DisallowedRelationError):
        world.store.create_edge(rid, "PREPARA", hid, {"origem": "derivado"}, actor=ORQ)


def test_referencia_do_problema(world):
    """Scenario: Referência do problema."""
    _, rid = eg.referencia(world)
    assert any(e.src_id == rid and e.rel_type == "REFERENCIA_DE" and e.dst_id == world.problem.id
               and e.properties["origem"] == "afirmado" for e in world.store._edges)  # noqa: SLF001


def test_referencia_destino_errado(world):
    """Scenario: Destino errado."""
    hid = eg.hipotese(world)
    rid = eg.resultado(world, eg.experimento(world))
    with pytest.raises(DisallowedRelationError):
        world.store.create_edge(rid, "REFERENCIA_DE", hid, {"origem": "afirmado"}, actor=ORQ)


def test_referencia_nao_entra_no_veredito(world):
    """Scenario: Referência não entra no veredito (``collect_attempts`` devolve só a tentativa ligada por ``TESTA``)."""
    hid = eg.hipotese(world, status="em_teste")
    eid = eg.experimento(world, papel="teste", testa=hid)
    eg.resultado(world, eid, 0.85)
    eg.referencia(world, 0.62)
    service = KnowledgeService(world.store)
    hipotese = world.store.get_node(hid)
    problema = service.problem_for(hipotese)
    _, metric = service.criterion_for(problema)
    collected = service.collect_attempts(hipotese, metric)
    assert len(collected) == 1


def test_refinamento(world):
    """Scenario: Refinamento (``DERIVADA_DE`` entre hipóteses)."""
    h1, h2 = eg.hipotese(world, enunciado="h1"), eg.hipotese(world, enunciado="h2")
    world.store.create_edge(h2, "DERIVADA_DE", h1, {"origem": "afirmado"}, actor=ORQ)
    assert any(e.src_id == h2 and e.rel_type == "DERIVADA_DE" and e.dst_id == h1 for e in world.store._edges)  # noqa: SLF001


def test_laco_em_derivada_de(world):
    """Scenario: Laço."""
    h1 = eg.hipotese(world)
    with pytest.raises(SelfRelationNotAllowedError):
        world.store.create_edge(h1, "DERIVADA_DE", h1, {"origem": "afirmado"}, actor=ORQ)


# --- Construtores compartilhados --------------------------------------------------------------------------------


def test_construtor_problema_por_tipo(world):
    assert "tipo" not in eg.problema(world, None).properties["criterio_sucesso"]
    assert eg.problema(world, "limiar").properties["criterio_sucesso"]["tipo"] == "limiar"
    discr = eg.problema(world, "discriminacao").properties["criterio_sucesso"]
    assert "alvo" not in discr and len(discr["hipoteses_concorrentes"]) == 2
    cob = eg.problema(world, "cobertura").properties["criterio_sucesso"]
    assert "alvo" not in cob and "delta_min" not in cob
    with pytest.raises(ValueError):
        eg.problema(world, "fronteira")


def test_construtor_hipotese_do_sistema(world):
    node = world.store.get_node(eg.hipotese(world, origem="sistema"))
    assert node.properties["chave_estruturada"].count("|") == 2
    assert node.properties["referencia_fixada"]["origem_referencia"] == "referencia_medida"
    assert node.properties["criado_por"] == "orquestrador"


def test_construtor_hipotese_abandonada_usa_o_ator_do_caminho_real(world):
    node = world.store.get_node(eg.hipotese(world, status="abandonada", abandonada_por="pesquisador"))
    assert node.properties["abandonada_por"] == "pesquisador"
    assert any(e["actor"] == "pesquisador" for e in world.store.audit_log if e["node_id"] == node.id)


def test_construtores_de_experimento_resultado_e_referencia(world):
    hid = eg.hipotese(world)
    eid = eg.experimento(world, papel="preparacao", testa=hid, prepara=(world.problem.id,))
    rid = eg.resultado(world, eid, 0.9, validado=False)
    assert world.store.get_node(rid).properties["status_validacao"] == "nao_validado"
    ref_exp, ref_res = eg.referencia(world, 0.5)
    assert world.store.get_node(ref_exp).properties["papel"] == "referencia"
    assert world.store.get_node(ref_res).properties["valor"] == 0.5
