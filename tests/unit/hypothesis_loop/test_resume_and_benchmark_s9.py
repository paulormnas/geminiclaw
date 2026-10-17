"""Seção 9 de v18.7-exploration-limits: retomada, benchmark e revisão do objetivo. Sem LLM."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.benchmark.report import render_rejected_plans_stops
from scripts.benchmark.run_benchmark import anomalies, build_env, stop_class, validate_matrix
from src.orchestration.exploration import ExplorationSession
from src.session.continuity import RESUME_CONFIRM, RESUME_OK, Checkpoint, evaluate_resumability
from tests.support.fake_gate import FakeGate
from tests.support.hypothesis_world import HypothesisWorld
from tests.unit.benchmark.test_footprint_and_seed import _ok_result

pytestmark = pytest.mark.unit


# --- 9.1 retomada -----------------------------------------------------------------------------------------------------


def checkpoint(motivo):
    cp = MagicMock(spec=Checkpoint)
    cp.motivo_parada = motivo
    return cp


@pytest.mark.parametrize("motivo", ["limite_custo", "limite_ciclos", "limite_execucoes", "limite_cota_provedor"])
def test_limites_sao_retomaveis_sem_perguntar(motivo):
    """Scenarios: Limite de custo; Sessão antiga com teto de ciclos; limite_cota_provedor preservado."""
    assert evaluate_resumability("closed", checkpoint(motivo), motivo).decision == RESUME_OK


def test_saturacao_pede_confirmacao():
    """Scenario: Saturação pede confirmação."""
    result = evaluate_resumability("closed", checkpoint("saturacao"), "saturacao")
    assert result.decision == RESUME_CONFIRM and "saturacao" in result.message
    assert "erro da medida" in result.message


# --- 9.3 benchmark ----------------------------------------------------------------------------------------------------


def test_classificacao_dos_motivos_da_v18_7():
    """Scenario: Classificação (inclui ``planos_rejeitados`` com classe própria e ``versao_modelo`` → limite)."""
    stops = ("limite_tokens", "limite_custo", "limite_cota_provedor", "limite_ciclos", "erro",
             "interrompida_pesquisador", "solucao_encontrada", "saturacao", "hipoteses_nao_testadas",
             "versao_modelo", "planos_rejeitados")
    assert [stop_class(s) for s in stops] == [
        "limite", "limite", "limite", "limite", "erro", "interrupcao", "criterio_pesquisa", "criterio_pesquisa",
        "hipoteses_nao_testadas", "limite", "planos_rejeitados",
    ]


def test_saturacao_e_planos_rejeitados_nao_sao_anomalia():
    """Scenarios: Saturação não é anomalia; Planos rejeitados não é anomalia; Limite de custo é anomalia."""
    assert anomalies(_ok_result(stop_reason="saturacao")) == []
    assert anomalies(_ok_result(stop_reason="planos_rejeitados", status="exit 3")) == []
    assert any("limite_custo" in p for p in anomalies(_ok_result(stop_reason="limite_custo")))


def test_relatorio_lista_planos_rejeitados():
    results = [
        {"name": "c1", "repeticao": 1, "stop_reason": "solucao_encontrada"},
        {"name": "c1", "repeticao": 2, "stop_reason": "planos_rejeitados"},
    ]
    text = render_rejected_plans_stops(results)
    assert "c1 (repetição 2)" in text and "repetição 1" not in text


def test_bateria_usa_a_politica_parar():
    """Scenario: Bateria usa a política parar para planos rejeitados (sem alterar o ambiente base)."""
    base = {"ON_PLAN_REJECTIONS": "explorar"}
    env = build_env(base, {"*": "google/gemini-4-argon"})
    assert env["ON_PLAN_REJECTIONS"] == "parar" and base["ON_PLAN_REJECTIONS"] == "explorar"


def matrix():
    return json.loads(Path("scripts/benchmark/matrix_modelos_v18_6.json").read_text(encoding="utf-8"))


def test_matriz_sem_teto_de_custo_e_recusada():
    """Scenario: Matriz sem teto de custo."""
    broken = copy.deepcopy(matrix())
    broken["env"].pop("SESSION_MAX_COST_USD")
    with pytest.raises(ValueError, match="SESSION_MAX_COST_USD"):
        validate_matrix(broken)
    for bad in ("0", "-1", "abc", ""):
        broken["env"]["SESSION_MAX_COST_USD"] = bad
        with pytest.raises(ValueError, match="SESSION_MAX_COST_USD"):
            validate_matrix(broken)


def test_matriz_com_teto_passa_e_chega_ao_subprocesso():
    """Scenario: Matriz com teto."""
    declared = matrix()
    validate_matrix(declared)
    env = build_env({}, {"*": "google/gemini-4-argon"}, declared["env"])
    assert float(env["SESSION_MAX_COST_USD"]) > 0


# --- revisão do objetivo (5.2 → 9) ------------------------------------------------------------------------------------


def revision_session(world):
    session = ExplorationSession(lambda: world.store, world.ctx, MagicMock(), mode="semi")
    gate = FakeGate()
    ref = f"{world.problem.id}:objetivo:cobertura"
    request = gate.request("confirmar_problema", ref, "p", ("autorizar", "negar"), motivo="revisao_objetivo",
                           session_id=world.sid)
    return session, gate, ref, request


def test_autorizar_aplica_a_revisao_com_o_pedido_consumido():
    world = HypothesisWorld()
    session, gate, ref, request = revision_session(world)
    session.remember_revision(ref, "cobertura")
    gate.respond(request.id, resposta={"acao": "autorizar"})
    with patch("src.gate.persistent_gate.session_gate", return_value=gate):
        session.apply_objective_revisions()
    criterion = world.raw.get_node(world.problem.id).properties["criterio_sucesso"]
    assert criterion["tipo"] == "cobertura" and criterion["definido_por"] == "pesquisador"
    assert "alvo" not in criterion and gate.get(request.id).consumido


def test_negar_consome_sem_mudar_o_objetivo():
    world = HypothesisWorld()
    session, gate, ref, request = revision_session(world)
    session.remember_revision(ref, "cobertura")
    gate.respond(request.id, resposta={"acao": "negar"})
    with patch("src.gate.persistent_gate.session_gate", return_value=gate):
        session.apply_objective_revisions()
    assert world.raw.get_node(world.problem.id).properties["criterio_sucesso"]["tipo"] == "limiar"
    assert gate.get(request.id).consumido


def test_discriminacao_ou_proposta_ausente_nao_e_aplicada():
    world = HypothesisWorld()
    session, gate, ref, request = revision_session(world)
    session.remember_revision(ref, "discriminacao")
    gate.respond(request.id, resposta={"acao": "autorizar"})
    with patch("src.gate.persistent_gate.session_gate", return_value=gate):
        session.apply_objective_revisions()
    assert world.raw.get_node(world.problem.id).properties["criterio_sucesso"]["tipo"] == "limiar"
    assert not gate.get(request.id).consumido
