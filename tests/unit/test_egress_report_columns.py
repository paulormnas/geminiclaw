"""Egresso limitado separado do total no relatório (v18.7-benchmark-fixes, achado 6 da bateria V18.6)."""

from __future__ import annotations

from typing import Any

import pytest

from scripts.benchmark.report import render_operation
from src.report import operation_metrics
from src.report.operation_metrics import EgressMetricsReader, render_operation_metrics_section

pytestmark = pytest.mark.unit


def _group(**values: Any) -> dict[str, Any]:
    return {"estado": "disponivel", **values}


def _result(bytes_total=3942301, bytes_limitados=412000, limite=2000000, chain=None, **egress_extra) -> dict:
    egress = _group(
        bytes_total=bytes_total, por_destino=[], por_origem={}, intervencoes_filtro={}, consultas_busca=0,
        chamadas_visao=0, envios_recusados=0, limite_bytes=limite, **egress_extra,
    )
    if bytes_limitados is not None:
        egress["bytes_limitados"] = bytes_limitados
    metrics = {
        "egresso": egress,
        "proveniencia": _group(cadeia=chain or {"resultado": "integra", "orfas": 0, "pendentes": 0, "ponta": None}),
        "verificacao": _group(),
        "custo_recursos": _group(no={}),
    }
    return {"name": "c1", "operation_metrics": metrics}


def test_total_acima_do_limite_sem_violacao():
    """Scenario: Total acima do limite sem violação (o limite fica ao lado das saídas novas, nunca do total)."""
    metrics = {"egresso": _group(
        bytes_total=3942301, bytes_limitados=412000, limite_bytes=2000000, por_destino=[], por_origem={},
        intervencoes_filtro={}, consultas_busca=0, chamadas_visao=0, envios_recusados=0),
        "proveniencia": {"estado": "indisponivel", "produtor": "x", "motivo": "m"},
        "verificacao": {"estado": "indisponivel", "produtor": "x", "motivo": "m"},
        "custo_recursos": {"estado": "indisponivel", "produtor": "x", "motivo": "m"},
        "intervencoes_humanas": {"estado": "indisponivel", "produtor": "x", "motivo": "m"},
        "versao": 1, "parcial": False, "gerado_em": "t", "modo_sem_limite": {"ativo": False},
    }
    section = render_operation_metrics_section(metrics)
    assert "3.942.301 bytes enviados fora do nó" in section
    assert "saídas de execução novas (sujeitas ao limite): 412.000 de 2.000.000 bytes" in section
    assert section.index("3.942.301") < section.index("412.000") < section.index("2.000.000")


def test_leitor_de_egresso_traz_bytes_limitados_igual_ao_contador_do_limite(monkeypatch):
    """Scenario: Igualdade com o contador do limite (a mesma função do ``UsageTracker``)."""
    from src.egress import log as egress_log

    class Cursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=()):
            if "SUM(bytes_enviados)" in sql:
                return Cursor([{"provedor": "google", "modelo": "m", "trust": "third_party",
                                "localidade": "fora_do_no", "bytes": 3942301, "chamadas": 4}])
            if "COUNT(*) AS n FROM egress_log WHERE session_id = %s AND recusado" in sql:
                return Cursor([{"n": 0}])
            return Cursor([])

    monkeypatch.setattr("src.db.get_connection", lambda: Conn())
    monkeypatch.setattr(egress_log, "egress_bytes_for_session", lambda session_id: 412000)
    data = EgressMetricsReader(lambda session_id: {"max_egress_bytes": 2000000}).read("s1")
    assert data["bytes_total"] == 3942301 and data["bytes_limitados"] == 412000 and data["limite_bytes"] == 2000000
    assert data["bytes_limitados"] == egress_log.egress_bytes_for_session("s1")
    assert operation_metrics is not None


def test_colunas_de_egresso():
    """Scenario: Colunas de egresso."""
    assert "| 3942301 | 412000 | 2000000 |" in render_operation([_result()])


def test_resultado_antigo_sem_bytes_limitados():
    """Scenario: Resultado antigo."""
    table = render_operation([_result(bytes_limitados=None)])
    assert "Saídas novas (bytes)" in table and "| 3942301 | - | 2000000 |" in table


def test_modo_sem_limite():
    """Scenario: Modo sem limite."""
    assert "| 3942301 | 412000 | sem limite |" in render_operation([_result(limite=None)])


def test_causa_da_cadeia_divergente():
    """Scenario: Causa da cadeia divergente."""
    chain = {"resultado": "divergente", "orfas": 0, "pendentes": 0, "ponta": None,
             "motivos": {"cadeia": 0, "pares": 0, "arquivos_alterados": 2, "checkpoints_divergentes": 0,
                         "conflitos_pendencia": 0}}
    assert "divergente (arquivos_alterados)" in render_operation([_result(chain=chain)])


def test_secao_markdown_mostra_as_causas_da_cadeia():
    metrics = {
        "egresso": {"estado": "indisponivel", "produtor": "x", "motivo": "m"},
        "proveniencia": _group(
            numeros_por_origem=None,
            cadeia={"resultado": "divergente", "orfas": 0, "pendentes": 0,
                    "motivos": {"cadeia": 0, "arquivos_alterados": 2}},
        ),
        "verificacao": {"estado": "indisponivel", "produtor": "x", "motivo": "m"},
        "custo_recursos": {"estado": "indisponivel", "produtor": "x", "motivo": "m"},
        "intervencoes_humanas": {"estado": "indisponivel", "produtor": "x", "motivo": "m"},
        "versao": 1, "parcial": False, "gerado_em": "t", "modo_sem_limite": {"ativo": False},
    }
    assert "causas: arquivos_alterados=2" in render_operation_metrics_section(metrics)
