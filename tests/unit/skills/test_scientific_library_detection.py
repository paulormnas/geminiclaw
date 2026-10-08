"""Testes unitários da detecção de bibliotecas científicas (Roadmap V15.2 / Spec G2)."""

import pytest

from src.skills.code.skill import _load_scientific_helpers_source, _uses_scientific_libraries


@pytest.mark.unit
class TestUsesScientificLibraries:
    def test_detecta_numpy(self) -> None:
        assert _uses_scientific_libraries("import numpy as np\nnp.array([1,2,3])")

    def test_detecta_pandas(self) -> None:
        assert _uses_scientific_libraries("import pandas as pd\ndf = pd.DataFrame()")

    def test_detecta_sklearn(self) -> None:
        assert _uses_scientific_libraries("from sklearn.ensemble import RandomForestClassifier")

    def test_nao_detecta_codigo_generico(self) -> None:
        assert not _uses_scientific_libraries("print('olá mundo')\nx = 1 + 1")


@pytest.mark.unit
def test_load_scientific_helpers_source_contem_funcao_publica() -> None:
    source = _load_scientific_helpers_source()
    assert "def save_experiment_artifacts" in source
