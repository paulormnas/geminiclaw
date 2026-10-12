"""Leitura tolerante do metrics.json (contrato aninhado e formato plano) em todos os consumidores."""

from __future__ import annotations

import pytest

from src.metrics_file import metrics_of
from src.report.report_model import build_results

pytestmark = pytest.mark.unit


def test_contrato_aninhado_vence_o_plano() -> None:
    assert metrics_of({"metrics": {"accuracy": 0.9}, "accuracy": 0.1}) == {"accuracy": 0.9}
    assert metrics_of({"metrics": {}}) == {}


def test_formato_plano_so_com_numeros_fora_dos_metadados() -> None:
    flat = {"accuracy": 0.96, "f1": 0.9, "seed": 42, "task_name": "t", "parameters": {"k": 1}, "ok": True,
            "nota": "x", "divergence_note": None, "unidades": {}}
    assert metrics_of(flat) == {"accuracy": 0.96, "f1": 0.9}
    assert metrics_of({"metrics": 3, "accuracy": 0.5}) == {"accuracy": 0.5}
    assert metrics_of([1]) == {} and metrics_of(None) == {}


def test_relatorio_mostra_as_metricas_de_um_arquivo_plano() -> None:
    rows = build_results({"treino": {"accuracy": 0.95, "seed": 42}})
    assert [(r.task_name, r.metric, r.value) for r in rows] == [("treino", "accuracy", 0.95)]
