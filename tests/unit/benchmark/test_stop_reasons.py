"""``v18.6-auto-metrics-and-stop-reasons``: classificação dos motivos de parada e motivos de reprovação no benchmark."""

from __future__ import annotations

import pytest

from scripts.benchmark.interactions import summarize_events
from scripts.benchmark.report import render_interactions, render_untested_stops
from scripts.benchmark.run_benchmark import anomalies, stop_class
from tests.unit.benchmark.test_footprint_and_seed import _ok_result

pytestmark = pytest.mark.unit


def test_parada_por_hipotese_nao_testada_nao_e_anomalia() -> None:
    """Scenario: Parada por hipótese não testada não é anomalia."""
    assert anomalies(_ok_result(stop_reason="hipoteses_nao_testadas")) == []
    assert anomalies(_ok_result(stop_reason="limite_tokens"))  # os limites continuam sendo anomalia
    assert anomalies(_ok_result(stop_reason="erro"))


def test_classificacao_dos_motivos_de_parada() -> None:
    """Scenario: Classificação."""
    assert [stop_class(s) for s in (
        "limite_tokens", "erro", "interrompida_pesquisador", "solucao_encontrada", "hipoteses_nao_testadas", None,
    )] == ["limite", "erro", "interrupcao", "criterio_pesquisa", "hipoteses_nao_testadas", None]


def test_relatorio_lista_a_parada_por_hipoteses_nao_testadas() -> None:
    """Scenario: Relatório lista a parada."""
    results = [
        {"name": "c1", "repeticao": 1, "stop_reason": "solucao_encontrada"},
        {"name": "c1", "repeticao": 2, "stop_reason": "hipoteses_nao_testadas"},
    ]
    text = render_untested_stops(results)
    assert "c1 (repetição 2)" in text and "repetição 1" not in text


def test_resumo_de_interacoes_conta_os_motivos_de_reprovacao() -> None:
    """Scenario: Reprovação sem hipótese no resumo."""
    events = [
        {"event_type": "subtask_review",
         "payload": {"approved": False, "issues": ["acuracia"], "motivos": ["sem_hipotese"]}},
        {"event_type": "subtask_review", "payload": {"approved": True, "motivos": []}},
    ]
    summary = summarize_events(events)
    assert summary["subtask_reviews"]["motivos"] == {"sem_hipotese": 1}
    result = {"name": "c1", "db": {"interactions": {
        **summary, "tokens_by_agent": [], "ask_researcher": [],
    }}}
    assert "sem_hipotese: 1" in render_interactions([result])
