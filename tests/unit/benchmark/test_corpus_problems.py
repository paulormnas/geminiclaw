"""Segundo problema do corpus (Wine), escolha do problema por combinação e matriz do corpus de memória."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.benchmark.run_benchmark import validate_combination, validate_matrix
from scripts.benchmark.seed_project import BENCHMARK_DRAFT, PROBLEMS, WINE_DRAFT, seeder_for
from src.knowledge import projects
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.vocabulary import seed_vocabulary

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "scripts" / "benchmark" / "matrix_corpus_memoria.json"


def seeded_store(tmp_path: Path) -> InMemoryGraphStore:
    shutil.copy(ROOT / "tests" / "fixtures" / "cnpq_areas_fixture.csv", tmp_path / "cnpq_areas.csv")
    shutil.copy(ROOT / "data" / "vocabulary" / "metrics.yaml", tmp_path / "metrics.yaml")
    store = InMemoryGraphStore()
    seed_vocabulary(store, vocabulary_dir=tmp_path)
    return store


def test_semeadura_do_wine_cria_problema_confirmado_com_as_caracteristicas_dos_dados(tmp_path: Path) -> None:
    store = seeded_store(tmp_path)
    import scripts.benchmark.seed_project as sp

    project_id = sp.seed_project("wine", store, draft=WINE_DRAFT, description=PROBLEMS["wine"][1])
    detail = projects.get_project(store, project_id)
    assert detail.problema is not None and detail.problema.properties["status"] == "confirmado"
    assert "Wine" in detail.problema.properties["titulo"]
    assert detail.problema.properties["caracteristicas_dados"]["atributos"] == "13"


def test_iris_e_wine_compartilham_as_chaves_de_caracteristicas_para_a_semelhanca_pelos_dados() -> None:
    assert set(BENCHMARK_DRAFT.caracteristicas_dados) == set(WINE_DRAFT.caracteristicas_dados)
    assert BENCHMARK_DRAFT.metrica == WINE_DRAFT.metrica and BENCHMARK_DRAFT.alvo == WINE_DRAFT.alvo


def test_seeder_de_problema_desconhecido_lista_os_registrados() -> None:
    with pytest.raises(KeyError, match="iris, wine"):
        seeder_for("penguins")


def test_matriz_recusa_problema_desconhecido() -> None:
    matrix = {"env": {"SESSION_MAX_COST_USD": "3"}, "combinations": [{"name": "x", "problem": "penguins"}]}
    with pytest.raises(ValueError, match="penguins"):
        validate_matrix(matrix)


def test_matriz_do_corpus_e_valida_tem_juiz_de_outra_familia_e_arquivos_de_tarefa() -> None:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    validate_matrix(matrix)
    names = [c["name"] for c in matrix["combinations"]]
    assert len(names) == len(set(names))
    for combo in matrix["combinations"]:
        validate_combination(combo)
        assert combo["problem"] in PROBLEMS
        if "task_file" in combo:
            assert (ROOT / combo["task_file"]).is_file()
    assert {c["problem"] for c in matrix["combinations"]} == {"iris", "wine"}
    assert "anthropic" not in json.dumps(matrix)


def test_tarefa_e_script_do_wine() -> None:
    task = (ROOT / "scripts" / "benchmark" / "task_wine.txt").read_text(encoding="utf-8").strip()
    script = (ROOT / "run_wine.sh").read_text(encoding="utf-8")
    assert "Wine" in task and "task_wine.txt" in script
