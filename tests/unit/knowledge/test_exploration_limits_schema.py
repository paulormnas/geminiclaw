"""Schema do grafo de v18.7-exploration-limits (seção 2; ``specs/knowledge-graph``). Tudo em memória."""

from __future__ import annotations

import pytest

from src.knowledge.errors import (
    HumanConfirmationRequiredError,
    InvalidEnumValueError,
    InvalidPropertyValueError,
    MissingRequiredPropertyError,
    UnknownLabelError,
)
from src.knowledge.provenance import Actor
from src.knowledge.schema import NODE_SCHEMAS, find_relation_schema
from tests.support import exploration_graph as eg
from tests.support.hypothesis_world import AGENTE, ORQ, PESQUISADOR, HypothesisWorld

pytestmark = pytest.mark.unit

CURATOR = Actor(kind="agente", role="curator")


@pytest.fixture
def world() -> HypothesisWorld:
    return HypothesisWorld()


def _set_criterion(world, criterio, actor=PESQUISADOR):
    world.store.update_node(world.problem.id, {"criterio_sucesso": criterio}, actor=actor)


def _criterion(world):
    return world.store.get_node(world.problem.id).properties["criterio_sucesso"]


# --- Schema único e declarativo -----------------------------------------------------------------------------------


def test_rotulo_desconhecido(world):
    """Scenario: Rótulo desconhecido."""
    with pytest.raises(UnknownLabelError):
        world.store.create_node("Pessoa", world.base(), actor=PESQUISADOR)


def test_tipo_de_objetivo_invalido(world):
    """Scenario: Tipo de objetivo inválido (a mensagem lista os tipos)."""
    with pytest.raises(InvalidEnumValueError) as error:
        _set_criterion(world, {"tipo": "maximo"})
    for kind in ("limiar", "discriminacao", "cobertura", "fronteira"):
        assert kind in str(error.value)


def test_campo_proibido_pelo_tipo(world):
    """Scenario: Campo proibido pelo tipo."""
    rivals = [{"hipotese_id": "a", "predicao": "x"}, {"hipotese_id": "b", "predicao": "y"}]
    with pytest.raises(InvalidPropertyValueError, match="alvo"):
        _set_criterion(world, {"tipo": "discriminacao", "alvo": 0.9, "hipoteses_concorrentes": rivals})


def test_politica_invalida(world):
    """Scenario: Política inválida (lista as três válidas)."""
    with pytest.raises(InvalidEnumValueError) as error:
        _set_criterion(world, {"tipo": "cobertura", "ao_atingir_objetivo": "talvez"})
    for policy in ("parar", "perguntar", "continuar"):
        assert policy in str(error.value)


def test_problema_antigo_continua_valido(world):
    """Scenario: Problema antigo continua válido."""
    eg.problema(world, None)
    assert "tipo" not in _criterion(world)
    world.store.update_node(world.problem.id, {"resumo": "outro resumo"}, actor=PESQUISADOR)


def test_obrigatorios_por_tipo(world):
    with pytest.raises(MissingRequiredPropertyError, match="delta_min"):
        _set_criterion(world, {"tipo": "limiar", "metrica": "acc", "sentido": "maior_melhor"})
    with pytest.raises(InvalidPropertyValueError, match="ao menos 2"):
        _set_criterion(world, {"tipo": "discriminacao", "hipoteses_concorrentes": [{"predicao": "x"}]})
    with pytest.raises(InvalidPropertyValueError, match="predicao"):
        _set_criterion(world, {"tipo": "discriminacao", "hipoteses_concorrentes": [{"predicao": "x"}, {"predicao": " "}]})
    with pytest.raises(InvalidPropertyValueError, match="hipoteses_concorrentes"):
        _set_criterion(world, {"tipo": "limiar", "metrica": "a", "sentido": "maior_melhor", "delta_min": 0.1,
                               "hipoteses_concorrentes": []})
    _set_criterion(world, {"tipo": "cobertura"})
    _set_criterion(world, {"tipo": "fronteira"})  # aceito pelo schema; recusado na confirmação (V19)


# --- Campos do pesquisador no objetivo ----------------------------------------------------------------------------


def test_orquestrador_grava_a_politica(world):
    """Scenario: Orquestrador grava a política."""
    with pytest.raises(HumanConfirmationRequiredError):
        _set_criterion(world, {"tipo": "cobertura", "ao_atingir_objetivo": "continuar"}, actor=ORQ)


def test_agente_se_declara_pesquisador(world):
    """Scenario: Agente se declara pesquisador."""
    with pytest.raises(HumanConfirmationRequiredError):
        _set_criterion(world, {"tipo": "cobertura", "definido_por": "pesquisador"}, actor=AGENTE)


def test_orquestrador_substitui_o_objetivo_do_pesquisador(world):
    """Scenario: Orquestrador substitui o objetivo do pesquisador."""
    mine = {"tipo": "cobertura", "definido_por": "pesquisador"}
    _set_criterion(world, mine)
    with pytest.raises(HumanConfirmationRequiredError):
        _set_criterion(world, {"tipo": "cobertura", "definido_por": "agente"}, actor=ORQ)
    assert _criterion(world) == mine


def test_objetivo_do_agente_no_auto(world):
    """Scenario: Objetivo do agente no auto (Problema confirmado sem objetivo do pesquisador)."""
    _set_criterion(world, {"metrica": "R2"})
    _set_criterion(world, {"tipo": "cobertura", "definido_por": "agente"}, actor=ORQ)
    assert _criterion(world)["definido_por"] == "agente"


def test_pesquisador_define_a_politica(world):
    """Scenario: Pesquisador define a política (a trilha registra o pesquisador)."""
    _set_criterion(world, {"tipo": "cobertura", "ao_atingir_objetivo": "continuar", "definido_por": "pesquisador"})
    assert _criterion(world)["ao_atingir_objetivo"] == "continuar"
    assert world.store.audit_log[-1]["actor"] == "pesquisador"


def test_orquestrador_mantem_a_politica_do_pesquisador_ao_atualizar_outro_campo(world):
    mine = {"tipo": "cobertura", "ao_atingir_objetivo": "parar", "definido_por": "pesquisador"}
    _set_criterion(world, mine)
    world.store.update_node(world.problem.id, {"resumo": "novo"}, actor=ORQ)


# --- Motivos de parada, marco, predições --------------------------------------------------------------------------


@pytest.mark.parametrize("motivo", ["saturacao", "limite_custo", "limite_ciclos", "limite_execucoes", "limite_cota_provedor"])
def test_motivos_de_parada(motivo):
    """Scenario: Novos valores (e os antigos continuam aceitos)."""
    assert motivo in NODE_SCHEMAS["Sessao"].properties["motivo_parada"].enum


def test_segundo_marco(world):
    """Scenario: Segundo marco."""
    first = {"em": "2026-10-16", "sessao_id": "s1", "tipo": "limiar", "desfecho": None, "resultado_id": "r1",
             "hipotese_id": None, "valor": 0.9}
    second = {**first, "sessao_id": "s2"}
    world.store.update_node(world.problem.id, {"objetivo_atingido": [first]}, actor=ORQ)
    marks = world.store.get_node(world.problem.id).properties["objetivo_atingido"]
    world.store.update_node(world.problem.id, {"objetivo_atingido": [*marks, second]}, actor=ORQ)
    assert [m["sessao_id"] for m in world.store.get_node(world.problem.id).properties["objetivo_atingido"]] == ["s1", "s2"]


def test_agente_nao_escreve_objetivo_atingido(world):
    """Scenario: Agente tenta escrever."""
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.update_node(world.problem.id, {"objetivo_atingido": []}, actor=AGENTE)


def test_conferencia_de_predicoes_invalida(world):
    """Scenario: Conferência inválida (lista os três valores)."""
    with pytest.raises(InvalidEnumValueError) as error:
        eg.experimento(world, conferencia_predicoes={"h1": "talvez"})
    for value in ("confirma", "contraria", "inconclusiva"):
        assert value in str(error.value)
    node = world.store.get_node(eg.experimento(world, conferencia_predicoes={"h1": "confirma"}))
    assert node.properties["conferencia_predicoes"] == {"h1": "confirma"}


def test_hipotese_concorrente_e_predicao(world):
    node = world.store.get_node(eg.hipotese(world, concorrente=True, predicao="a acurácia sobe"))
    assert node.properties["concorrente"] is True and node.properties["predicao"] == "a acurácia sobe"
    with pytest.raises(InvalidPropertyValueError, match="concorrente"):
        eg.hipotese(world, concorrente="sim")
    with pytest.raises(InvalidPropertyValueError, match="predicao"):
        eg.hipotese(world, predicao="x" * 5000)


# --- Restrição de direção -----------------------------------------------------------------------------------------


def _restriction(world, **over):
    props = world.base(direcao="uso de reagente perigoso", categoria="seguranca", status="ativa",
                       decidida_por="pesquisador", decidida_em="2026-10-16T12:00:00+00:00", abordagens=["a1"])
    props.update(over)
    return props


def test_pesquisador_cria_e_revoga_sem_apagar(world):
    """Scenarios: Criação pelo pesquisador / Revogação não apaga (nó e relação RESTRINGE)."""
    rid = world.store.create_node("Restricao", _restriction(world), actor=PESQUISADOR)
    world.store.create_edge(rid, "RESTRINGE", world.problem.id, {}, actor=PESQUISADOR)
    world.store.update_node(rid, {"status": "revogada"}, actor=PESQUISADOR)
    assert world.store.get_node(rid).properties["status"] == "revogada"
    assert find_relation_schema("Restricao", "RESTRINGE", "Projeto") is not None


@pytest.mark.parametrize("actor", [CURATOR, AGENTE, ORQ])
def test_somente_o_pesquisador_cria_restricao_ate_o_pedido_consumido(world, actor):
    """Scenarios: Agente não cria restrição / Orquestrador sem pedido autorizado é recusado."""
    extra = {"justificativa_criacao": "teste", "nos_consultados": []} if actor.kind == "agente" else {}
    with pytest.raises(HumanConfirmationRequiredError):
        world.store.create_node("Restricao", _restriction(world, **extra), actor=actor)
    assert world.store.find_nodes("Restricao", {}) == []


def test_categoria_e_status_invalidos(world):
    with pytest.raises(InvalidEnumValueError):
        world.store.create_node("Restricao", _restriction(world, categoria="gosto"), actor=PESQUISADOR)
    with pytest.raises(InvalidEnumValueError):
        world.store.create_node("Restricao", _restriction(world, status="apagada"), actor=PESQUISADOR)
    with pytest.raises(MissingRequiredPropertyError, match="direcao"):
        props = _restriction(world)
        del props["direcao"]
        world.store.create_node("Restricao", props, actor=PESQUISADOR)
