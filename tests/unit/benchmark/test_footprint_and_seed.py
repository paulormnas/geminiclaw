"""Pegada de conhecimento, semeadura do projeto, anomalias e relatórios do benchmark."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from scripts.benchmark import footprint, report
from scripts.benchmark.run_benchmark import anomalies
from scripts.benchmark.seed_project import BENCHMARK_DRAFT, seed_project
from src.knowledge import projects
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.vocabulary import seed_vocabulary

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]


def seeded_store(tmp_path: Path) -> InMemoryGraphStore:
    """Grafo em memória com o vocabulário real de métricas e a tabela CNPq fictícia dos testes."""
    shutil.copy(ROOT / "tests" / "fixtures" / "cnpq_areas_fixture.csv", tmp_path / "cnpq_areas.csv")
    shutil.copy(ROOT / "data" / "vocabulary" / "metrics.yaml", tmp_path / "metrics.yaml")
    store = InMemoryGraphStore()
    seed_vocabulary(store, vocabulary_dir=tmp_path)
    return store


def test_delta_so_lista_o_que_mudou_e_ausente_conta_zero() -> None:
    before = {"qdrant": {"a": 10, "b": 5}, "tabelas": {"token_usage": 3}, "grafo": {"nos": 8, "arestas": 2}}
    after = {"qdrant": {"a": 14, "b": 5, "c": 2}, "tabelas": {"token_usage": 3, "egress_log": 4},
             "grafo": {"nos": 20, "arestas": 9}}
    assert footprint.delta(before, after) == {
        "qdrant": {"a": 4, "c": 2}, "tabelas": {"egress_log": 4}, "grafo": {"nos": 12, "arestas": 7},
    }


def test_delta_propaga_erros_de_medicao() -> None:
    out = footprint.delta({"qdrant_erro": "x"}, {"postgres_erro": "y"})
    assert out["qdrant_erro"] == "x" or out["postgres_erro"] == "y"


def test_project_graph_conta_nos_por_rotulo_e_arestas_por_tipo(tmp_path: Path) -> None:
    store = seeded_store(tmp_path)
    project_id = seed_project("combo-a", store)
    graph = footprint.project_graph(project_id, store)
    assert graph["total_nos"] >= 2 and graph["nos_por_rotulo"].get("Problema") == 1
    assert "erro" not in graph and graph["total_arestas"] == sum(graph["arestas_por_tipo"].values())


def test_semeadura_cria_projeto_com_problema_confirmado_e_um_por_combinacao(tmp_path: Path) -> None:
    store = seeded_store(tmp_path)
    first, second = seed_project("luna", store), seed_project("terra", store)
    assert first != second
    detail = projects.get_project(store, first)
    assert detail.titulo == "Benchmark luna" and detail.problema is not None
    assert detail.problema.properties["status"] == "confirmado"
    assert detail.problema.properties["criterio_sucesso"]["delta_min"] == BENCHMARK_DRAFT.delta_min


def test_tarefa_do_benchmark_e_a_do_run_sh() -> None:
    task = (ROOT / "scripts" / "benchmark" / "task_iris.txt").read_text(encoding="utf-8").strip()
    run_sh = (ROOT / "run.sh").read_text(encoding="utf-8")
    assert task in run_sh and "Iris" in task


def _ok_result(**over) -> dict:
    base = {"name": "x", "status": "exit 0", "log_tail": "", "session": "sess", "routing_check": {"ok": True,
            "divergences": []}, "operation_metrics": {"egresso": {"estado": "disponivel"},
                                                      "custo_recursos": {"estado": "indisponivel"}}}
    base.update(over)
    return base


def test_anomalias_so_para_defeitos_de_infraestrutura() -> None:
    assert anomalies(_ok_result()) == []
    assert anomalies({"name": "x", "status": "skipped"}) == []
    assert any("exit 1" in p for p in anomalies(_ok_result(status="exit 1")))
    assert any("timeout" in p for p in anomalies(_ok_result(status="timeout")))
    assert any("traceback" in p for p in anomalies(_ok_result(log_tail="Traceback (most recent call last):\n")))
    assert any("nenhuma sessão" in p for p in anomalies(_ok_result(session=None)))
    assert any("roteamento" in p for p in anomalies(_ok_result(routing_check={"ok": False, "divergences": ["x"]})))
    assert any("operation_metrics ausente" in p for p in anomalies(_ok_result(operation_metrics=None)))
    bad = _ok_result(operation_metrics={"egresso": {"estado": "erro", "mensagem": "banco caiu"}})
    assert any("egresso" in p and "banco caiu" in p for p in anomalies(bad))
    assert any("semeadura" in p for p in anomalies(_ok_result(seed_error="X: y")))


def test_relatorios_de_conhecimento_e_operacao() -> None:
    result = _ok_result(
        footprint_delta={"qdrant": {"knowledge": 12, "docs": 3}, "tabelas": {"execution_records": 8, "egress_log": 5,
                                                                              "knowledge_audit": 14},
                         "grafo": {"nos": 20, "arestas": 9}},
        project_graph={"total_nos": 20, "total_arestas": 9, "nos_por_rotulo": {"Hipotese": 4, "Problema": 1}},
        operation_metrics={
            "egresso": {"estado": "disponivel", "bytes_total": 2048, "consultas_busca": 3},
            "proveniencia": {"estado": "disponivel", "numeros_por_origem": {"res": 5, "calc": 1, "src": 0},
                             "numeros_nao_verificados": 2, "cadeia": {"resultado": "integra"}},
            "verificacao": {"estado": "disponivel", "afirmacoes_por_status": {"suportada": 3, "parcial": 1},
                            "ciclos_rejeicao_plano": 2},
            "custo_recursos": {"estado": "disponivel", "custo_usd_total": 0.42, "no": {"cpu_pct_medio": 33.1}},
        },
    )
    knowledge = report.render_knowledge([result])
    assert "15 (knowledge: +12, docs: +3)" in knowledge and "Hipotese 4, Problema 1" in knowledge
    assert "| 8 | 5 | 14 |" in knowledge
    operation = report.render_operation([result])
    assert "| 2048 | 3 | integra | 5/1/0 | 2 | 3/4 | 2 | 0.42 | 33.1 |" in operation


def test_matriz_do_benchmark_v18_6_e_valida() -> None:
    matrix = json.loads((ROOT / "scripts" / "benchmark" / "matrix_modelos_v18_6.json").read_text(encoding="utf-8"))
    names = [c["name"] for c in matrix["combinations"]]
    assert len(names) == len(set(names)) >= 4
    assert not re.search(r"gemini-3\.7|flash-3\.7", json.dumps(matrix))
    from src.llm.catalog import load_catalog

    catalog = load_catalog()
    for combo in matrix["combinations"]:
        for spec in combo["roles"].values():
            assert spec in catalog.modelos, f"{combo['name']}: {spec} fora do catálogo"


def test_sessao_fechada_por_limite_e_anomalia_mas_conclusao_normal_nao() -> None:
    assert any("limite_tokens" in p for p in anomalies(_ok_result(stop_reason="limite_tokens")))
    assert any("erro" in p for p in anomalies(_ok_result(stop_reason="erro")))
    for normal in ("solucao_encontrada", "sem_caminhos_promissores", None):
        assert not any("antes de concluir" in p for p in anomalies(_ok_result(stop_reason=normal)))


def test_zero_subtarefas_executadas_e_anomalia() -> None:
    assert any("nenhuma subtarefa executada" in p for p in anomalies(_ok_result(outcome={"subtasks": 0})))
    assert not any("nenhuma subtarefa" in p for p in anomalies(_ok_result(outcome={"subtasks": 4})))
