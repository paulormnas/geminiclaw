"""Testes da avaliação do modelo de embedding (v17-domain-search §8), sem modelo e sem rede."""

import json
from pathlib import Path

import pytest

from scripts.eval_domain_search import DEFAULT_QUERIES, compute_metrics, format_report, load_queries

QUERIES = [
    {"consulta": "p1", "esperados": ["A"], "idioma": "pt"},
    {"consulta": "p2", "esperados": ["B"], "idioma": "pt"},
    {"consulta": "e1", "esperados": ["C"], "idioma": "en"},
    {"consulta": "e2", "esperados": ["D"], "idioma": "en"},
]


@pytest.mark.unit
class TestAvaliacao:
    def test_metricas_por_idioma(self):
        """Scenario: Métricas por idioma"""
        ranking = {
            "p1": ["A", "X", "Y"],  # acerta no topo
            "p2": ["X", "Y", "Z", "B"],  # acerto só na 4ª posição
            "e1": ["X", "Y", "Z", "C"],
            "e2": ["X", "Y", "Z", "W"],
        }
        metrics = compute_metrics(QUERIES, lambda q: ranking[q])
        assert metrics["pt"].hit_at_1 == 0.5 and metrics["pt"].hit_at_3 == 0.5
        assert metrics["en"].hit_at_1 == 0.0 and metrics["en"].hit_at_3 == 0.0
        assert metrics["pt"].mean_first_rank == pytest.approx(2.5)
        assert "hit@1=0.50" in format_report(metrics, model="m")

    def test_codigo_aceito_em_qualquer_nivel(self):
        """Scenario: Código aceito em qualquer nível"""
        queries = [{"consulta": "q", "esperados": ["AREA", "SUBAREA"], "idioma": "pt"}]
        for result in (["SUBAREA"], ["AREA"]):
            metrics = compute_metrics(queries, lambda q, r=result: r)
            assert metrics["pt"].hit_at_1 == 1.0

    def test_sem_acertos_nao_tem_posicao_media(self):
        metrics = compute_metrics(QUERIES[:1], lambda q: ["X"])
        assert metrics["pt"].mean_first_rank is None


@pytest.mark.unit
class TestConjuntoRotulado:
    def test_fixture_valida_e_com_codigos_oficiais(self):
        queries = load_queries(DEFAULT_QUERIES)
        assert 35 <= len(queries) <= 45
        assert {q["idioma"] for q in queries} == {"pt", "en"}
        root = Path(__file__).resolve().parents[2]
        table = (root / "data/vocabulary/cnpq_areas.csv").read_text("utf-8").splitlines()
        codes = {line.split(",")[0] for line in table}
        assert all(set(q["esperados"]) <= codes for q in queries)

    def test_linha_invalida_falha_cedo(self, tmp_path):
        bad = tmp_path / "q.jsonl"
        bad.write_text(json.dumps({"consulta": "x", "idioma": "pt", "esperados": []}) + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_queries(bad)
