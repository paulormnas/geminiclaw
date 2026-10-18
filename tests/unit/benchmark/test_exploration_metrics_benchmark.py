"""Benchmark com as métricas da exploração (``v18.7-exploration-metrics``, spec ``benchmark``)."""

from __future__ import annotations

import pytest

from scripts.benchmark.interactions import summarize_events
from scripts.benchmark.report import render_contract, render_exploration

pytestmark = pytest.mark.unit


def _result(name, rep, *, proportion=None, abandoned=0, tokens=None, divergences=0, stop="solucao_encontrada"):
    exploration = None
    if proportion is not None or tokens is not None:
        exploration = {"estado": "disponivel"}
        if proportion is not None:
            exploration["ligacao"] = {
                "estado": "disponivel", "experimentos_por_papel": {"teste": 4, "preparacao": 2, "referencia": 1},
                "proporcao_testes_sistema": proportion, "ligacoes_prepara_derivadas": 3,
                "hipoteses_sistema_abandonadas": abandoned,
            }
        if tokens is not None:
            exploration["contrato"] = {
                "estado": "disponivel", "tentativas": 10, "tokens_estimados_total": tokens, "fracao_entrada": 0.07,
                "divergencias": divergences,
            }
    return {"name": name, "repeticao": rep, "status": "exit 0", "stop_reason": stop,
            "outcome": {"subtasks_ok": 5}, "operation_metrics": {"exploracao": exploration} if exploration else {}}


def test_motivos_genericos_no_resumo():
    """Scenario: Motivos genéricos no resumo."""
    events = [
        {"event_type": "subtask_review", "payload": {"approved": False, "motivos": ["direcao_restrita"]}},
        {"event_type": "subtask_review", "payload": {"approved": False, "motivos": ["hipotese_do_sistema"]}},
    ]
    assert summarize_events(events)["subtask_reviews"]["motivos"] == {"direcao_restrita": 1, "hipotese_do_sistema": 1}


def test_resumo_das_tentativas_e_da_divergencia():
    events = [
        {"event_type": "subtask_attempt", "payload": {"contrato_sha256": "a", "contrato_tokens_estimados": 1000}},
        {"event_type": "subtask_attempt", "payload": {"contrato_sha256": None, "contrato_tokens_estimados": None}},
        {"event_type": "contrato_divergente", "payload": {}},
    ]
    summary = summarize_events(events)
    assert summary["subtask_attempts"] == {"total": 2, "com_hash": 1, "tokens_contrato_total": 1000}
    assert summary["contrato_divergente"] == 1


def test_tabela_de_exploracao_media_por_execucao():
    """Scenario: Tabela de exploração."""
    table = render_exploration([_result("c1", 1, proportion=0.5, abandoned=1), _result("c1", 2, proportion=0.25)])
    row = next(line for line in table.splitlines() if line.startswith("| c1 "))
    assert "| 0.375 |" in row and "| 0.5 |" in row  # proporção média e 0.5 hipótese abandonada por execução


def test_resultado_antigo_mostra_nd_sem_erro():
    """Scenario: Resultado antigo."""
    table = render_exploration([_result("c1", 1)])
    row = next(line for line in table.splitlines() if line.startswith("| c1 "))
    assert "n/d" in row
    assert "n/d" in render_contract([_result("c1", 1)])


def test_tokens_do_contrato_por_execucao():
    """Scenario: Média por execução."""
    results = [_result("c1", i + 1, tokens=t) for i, t in enumerate((20_000, 22_000, 24_000))]
    row = next(line for line in render_contract(results).splitlines() if line.startswith("| c1 "))
    assert "22000.000" in row and "[20000.0, 24000.0]" in row or "22000" in row


def test_divergencia_vira_aviso_de_placar_e_nao_anomalia():
    """Scenario: Divergência não interrompe."""
    from scripts.benchmark.run_benchmark import anomalies

    result = {"status": "exit 0", "stop_reason": "solucao_encontrada", "session": "s", "outcome": {"subtasks": 3},
              "operation_metrics": {"exploracao": {"estado": "disponivel"}}, "routing_check": {"ok": True},
              "db": {"interactions": {"contrato_divergente": 1}}, "anomalias_placar": ["contrato_divergente"]}
    assert not any("contrato" in problem for problem in anomalies(result))
