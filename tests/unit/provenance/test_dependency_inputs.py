"""Dependências montadas na proveniência da execução (v18.7-dependency-artifacts §4, spec execution-provenance)."""

from pathlib import Path

import pytest

from src.provenance.records import collect_inputs, inicio_body
from src.utils.agent_context import DependencyMount

pytestmark = pytest.mark.unit


def _setup(tmp_path: Path):
    root = tmp_path / "outputs"
    dep = root / "s" / "dividir_dados"
    dep.mkdir(parents=True)
    (dep / "y_train.csv").write_text("0\n1\n", encoding="utf-8")
    (root / "s" / "treinar").mkdir()
    return root, DependencyMount("dividir_dados", dep, "s")


def _collect(root, mounts):
    return collect_inputs(output_root=root, session_id="s", task_name="treinar", prior_dirs=[], cache=None,
                          dependency_dirs=mounts)


def test_entradas_da_dependencia_na_proveniencia(tmp_path):
    root, mount = _setup(tmp_path)
    entries = _collect(root, [mount])
    found = [e for e in entries if e["caminho"].endswith("dividir_dados/y_train.csv")]
    assert len(found) == 1 and len(found[0]["sha256"]) == 64
    body = inicio_body(code="x", extra_files=None, inputs=entries, packages=[], assets=[], image="i",
                       dependencies=[{"task_name": "dividir_dados", "sessao": "s"}])
    assert body["dependencias"] == [{"task_name": "dividir_dados", "sessao": "s"}]


def test_sem_dependencia_o_corpo_nao_muda():
    body = inicio_body(code="x", extra_files=None, inputs=[], packages=[], assets=[], image="i")
    assert "dependencias" not in body


def test_troca_de_arquivo_entre_execucoes_muda_o_hash(tmp_path):
    root, mount = _setup(tmp_path)
    first = [e for e in _collect(root, [mount]) if e["caminho"].endswith("y_train.csv")][0]["sha256"]
    (mount.source / "y_train.csv").write_text("9\n9\n", encoding="utf-8")
    second = [e for e in _collect(root, [mount]) if e["caminho"].endswith("y_train.csv")][0]["sha256"]
    assert first != second


def test_sem_montagens_a_coleta_e_a_anterior(tmp_path):
    root, _ = _setup(tmp_path)
    assert _collect(root, []) == []
