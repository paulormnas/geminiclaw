"""Testes unitários de scientific_helpers.save_experiment_artifacts (Roadmap V15.2 / Spec G2)."""

import json
from pathlib import Path

import pytest

from src.skills.code.scientific_helpers import save_experiment_artifacts


@pytest.mark.unit
class TestSaveExperimentArtifacts:
    def test_gera_params_e_metrics_json(self, tmp_path: Path) -> None:
        save_experiment_artifacts(
            task_name="treinar_modelo",
            params={"seed": 42, "n_estimators": 100},
            metrics={"accuracy": 0.87},
            output_dir=str(tmp_path),
        )

        assert (tmp_path / "params.json").exists()
        assert (tmp_path / "metrics.json").exists()

    def test_metrics_json_contem_schema_padronizado(self, tmp_path: Path) -> None:
        save_experiment_artifacts(
            task_name="treinar_modelo",
            params={"n_estimators": 100},
            metrics={"accuracy": 0.87},
            output_dir=str(tmp_path),
            seed=42,
        )

        data = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
        assert data["task_name"] == "treinar_modelo"
        assert data["seed"] == 42
        assert data["parameters"] == {"n_estimators": 100}
        assert data["metrics"] == {"accuracy": 0.87}
        assert data["divergence_note"] is None
        assert "timestamp" in data

    def test_seed_lido_de_params_quando_nao_passado_explicitamente(self, tmp_path: Path) -> None:
        save_experiment_artifacts(
            task_name="t1",
            params={"seed": 7},
            metrics={},
            output_dir=str(tmp_path),
        )
        data = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
        assert data["seed"] == 7

    def test_divergence_note_registrada_quando_fornecida(self, tmp_path: Path) -> None:
        save_experiment_artifacts(
            task_name="t1",
            params={"seed": 42},
            metrics={"accuracy": 0.62},
            output_dir=str(tmp_path),
            divergence_note="Acurácia obtida (0.62) diverge do artigo (0.85); dataset pode ter sido pré-processado diferente.",
        )
        data = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
        assert data["divergence_note"] is not None
        assert "diverge" in data["divergence_note"]

    def test_params_json_nao_inclui_chave_metrics(self, tmp_path: Path) -> None:
        save_experiment_artifacts(
            task_name="t1", params={"seed": 1}, metrics={"accuracy": 0.9}, output_dir=str(tmp_path)
        )
        params_data = json.loads((tmp_path / "params.json").read_text(encoding="utf-8"))
        assert "metrics" not in params_data
        assert params_data["parameters"] == {"seed": 1}

    def test_cria_output_dir_se_nao_existir(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "dir"
        save_experiment_artifacts(
            task_name="t1", params={}, metrics={}, output_dir=str(target)
        )
        assert (target / "metrics.json").exists()
