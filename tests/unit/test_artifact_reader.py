"""Testes unitários do ArtifactReader (Roadmap V15.4 / Spec G8)."""

import json
from pathlib import Path

import pytest

from src.report.artifact_reader import ArtifactReader


@pytest.mark.unit
class TestReadSubtaskMetrics:
    def test_le_metrics_json_de_multiplas_subtarefas(self, tmp_path: Path) -> None:
        (tmp_path / "sess_treinar" / "treinar").mkdir(parents=True)
        (tmp_path / "sess_treinar" / "treinar" / "metrics.json").write_text(
            json.dumps({"task_name": "treinar", "seed": 42, "metrics": {"accuracy": 0.87}, "divergence_note": None}),
            encoding="utf-8",
        )
        (tmp_path / "sess_validar" / "validar").mkdir(parents=True)
        (tmp_path / "sess_validar" / "validar" / "metrics.json").write_text(
            json.dumps({"task_name": "validar", "seed": 42, "metrics": {"f1": 0.9}, "divergence_note": None}),
            encoding="utf-8",
        )

        reader = ArtifactReader(tmp_path)
        metrics = reader.read_subtask_metrics()

        assert set(metrics.keys()) == {"treinar", "validar"}
        assert metrics["treinar"]["metrics"]["accuracy"] == 0.87

    def test_diretorio_sem_metrics_retorna_vazio(self, tmp_path: Path) -> None:
        reader = ArtifactReader(tmp_path / "nao_existe")
        assert reader.read_subtask_metrics() == {}

    def test_metrics_json_invalido_e_ignorado(self, tmp_path: Path) -> None:
        (tmp_path / "t1").mkdir()
        (tmp_path / "t1" / "metrics.json").write_text("{invalido", encoding="utf-8")

        reader = ArtifactReader(tmp_path)
        assert reader.read_subtask_metrics() == {}


@pytest.mark.unit
class TestReadSubtaskParams:
    def test_le_params_json(self, tmp_path: Path) -> None:
        (tmp_path / "t1").mkdir()
        (tmp_path / "t1" / "params.json").write_text(
            json.dumps({"task_name": "t1", "seed": 7, "parameters": {"n_estimators": 100}}), encoding="utf-8"
        )
        reader = ArtifactReader(tmp_path)
        params = reader.read_subtask_params()
        assert params["t1"]["parameters"]["n_estimators"] == 100


@pytest.mark.unit
class TestReadInputSnapshotFiles:
    def test_lista_arquivos_do_snapshot(self, tmp_path: Path) -> None:
        snapshot = tmp_path / "input_snapshot"
        snapshot.mkdir()
        (snapshot / "artigo.pdf").write_text("x")
        (snapshot / "dados.csv").write_text("x")

        reader = ArtifactReader(tmp_path)
        files = reader.read_input_snapshot_files()

        assert files == ["artigo.pdf", "dados.csv"]

    def test_sem_snapshot_retorna_lista_vazia(self, tmp_path: Path) -> None:
        reader = ArtifactReader(tmp_path)
        assert reader.read_input_snapshot_files() == []


@pytest.mark.unit
class TestReadSessionMetadata:
    def test_le_session_metadata_existente(self, tmp_path: Path) -> None:
        (tmp_path / "session_metadata.json").write_text(json.dumps({"session_id": "s1"}), encoding="utf-8")
        reader = ArtifactReader(tmp_path)
        assert reader.read_session_metadata() == {"session_id": "s1"}

    def test_sem_session_metadata_retorna_vazio(self, tmp_path: Path) -> None:
        reader = ArtifactReader(tmp_path)
        assert reader.read_session_metadata() == {}


@pytest.mark.unit
class TestBuildMetricsContextBlock:
    def test_bloco_contem_dados_reais(self, tmp_path: Path) -> None:
        (tmp_path / "t1").mkdir()
        (tmp_path / "t1" / "metrics.json").write_text(
            json.dumps({"task_name": "t1", "seed": 42, "metrics": {"accuracy": 0.87}, "divergence_note": None}),
            encoding="utf-8",
        )
        reader = ArtifactReader(tmp_path)
        block = reader.build_metrics_context_block()

        assert "t1" in block
        assert "0.87" in block
        assert "42" in block

    def test_bloco_vazio_quando_sem_metrics(self, tmp_path: Path) -> None:
        reader = ArtifactReader(tmp_path)
        block = reader.build_metrics_context_block()
        assert "Nenhum metrics.json" in block
