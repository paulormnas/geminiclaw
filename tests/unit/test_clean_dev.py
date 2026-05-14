"""Testes unitários para .agents/skills/clean_dev.py.

Valida a lógica de limpeza de logs, artefatos de output,
registros no PostgreSQL e coleções no Qdrant.

Markers: unit
"""
from __future__ import annotations

import os

# Necessário antes de qualquer import que carregue src.config
os.environ.setdefault("GEMINI_API_KEY", "dummy_key_for_testing")

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Garante que src/ e .agents/skills/ estão no path (padrão do projeto)
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))
_SKILLS_DIR = str(_ROOT / ".agents" / "skills")
if _SKILLS_DIR not in sys.path:
    sys.path.insert(0, _SKILLS_DIR)

# ---------------------------------------------------------------------------
# Import do módulo sob teste
# ---------------------------------------------------------------------------
import clean_dev  # noqa: E402 — importação após path fix


# ===========================================================================
# Fixtures compartilhadas
# ===========================================================================


@pytest.fixture()
def tmp_logs(tmp_path: Path) -> Path:
    """Cria estrutura de logs temporária."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "run_abc.log").write_text("linha de log\n")
    (logs / "run_def.log").write_text("outra linha\n")
    (logs / ".gitkeep").write_text("")
    return logs


@pytest.fixture()
def tmp_outputs(tmp_path: Path) -> Path:
    """Cria estrutura de outputs temporária com subdiretórios."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    session_dir = outputs / "20260514_090456_pipeline_teste"
    session_dir.mkdir()
    (session_dir / "resultado.md").write_text("# Resultado\n")
    (session_dir / "artefato.json").write_text("{}")
    nested = session_dir / "sub"
    nested.mkdir()
    (nested / "grafico.png").write_bytes(b"\x89PNG")
    return outputs


# ===========================================================================
# Testes: clean_logs
# ===========================================================================


@pytest.mark.unit
class TestCleanLogs:
    """Testes para a função clean_logs."""

    def test_remove_log_files(self, tmp_logs: Path) -> None:
        """Arquivos .log devem ser removidos; .gitkeep deve ser preservado."""
        result = clean_dev.clean_logs(tmp_logs)

        assert result["removed"] == 2
        assert not (tmp_logs / "run_abc.log").exists()
        assert not (tmp_logs / "run_def.log").exists()
        assert (tmp_logs / ".gitkeep").exists(), ".gitkeep deve ser preservado"

    def test_missing_dir_is_no_op(self, tmp_path: Path) -> None:
        """Diretório inexistente deve retornar removed=0 sem lançar exceção."""
        result = clean_dev.clean_logs(tmp_path / "nao_existe")

        assert result["removed"] == 0
        assert result["errors"] == 0

    def test_empty_dir_returns_zero(self, tmp_path: Path) -> None:
        """Diretório vazio deve retornar removed=0."""
        logs = tmp_path / "logs"
        logs.mkdir()

        result = clean_dev.clean_logs(logs)

        assert result["removed"] == 0

    def test_returns_error_count_on_permission_error(
        self, tmp_logs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Erros de I/O devem ser contados em 'errors', não lançados."""
        original_unlink = Path.unlink

        call_count = 0

        def failing_unlink(self: Path, missing_ok: bool = False) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PermissionError("acesso negado")
            original_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", failing_unlink)

        result = clean_dev.clean_logs(tmp_logs)

        assert result["errors"] == 1
        assert result["removed"] >= 1


# ===========================================================================
# Testes: clean_outputs
# ===========================================================================


@pytest.mark.unit
class TestCleanOutputs:
    """Testes para a função clean_outputs."""

    def test_removes_session_directories(self, tmp_outputs: Path) -> None:
        """Subdiretórios de sessão devem ser removidos recursivamente."""
        result = clean_dev.clean_outputs(tmp_outputs)

        assert result["removed"] == 1
        assert not any(tmp_outputs.iterdir())

    def test_missing_dir_is_no_op(self, tmp_path: Path) -> None:
        """Diretório de outputs inexistente deve retornar removed=0."""
        result = clean_dev.clean_outputs(tmp_path / "nao_existe")

        assert result["removed"] == 0
        assert result["errors"] == 0

    def test_empty_dir_returns_zero(self, tmp_path: Path) -> None:
        """Diretório de outputs vazio deve retornar removed=0."""
        outputs = tmp_path / "outputs"
        outputs.mkdir()

        result = clean_dev.clean_outputs(outputs)

        assert result["removed"] == 0

    def test_returns_error_count_on_failure(
        self, tmp_outputs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Erros ao remover subdiretórios devem ser contados em 'errors'."""
        import shutil

        def failing_rmtree(path: Path, **kwargs: object) -> None:
            raise OSError("disco cheio")

        monkeypatch.setattr(shutil, "rmtree", failing_rmtree)

        result = clean_dev.clean_outputs(tmp_outputs)

        assert result["errors"] >= 1


# ===========================================================================
# Testes: clean_postgres
# ===========================================================================


@pytest.mark.unit
class TestCleanPostgres:
    """Testes para a função clean_postgres."""

    EXPECTED_TABLES = [
        "agent_events",
        "tool_usage",
        "token_usage",
        "hardware_snapshots",
        "subtask_metrics",
        "execution_history",
        "agent_sessions",
        "long_term_memory",
        "deep_search_cache",
        "llm_cache",
        "documents",
        "document_chunks",
    ]

    def test_truncates_all_expected_tables(self) -> None:
        """TRUNCATE deve ser chamado para todas as tabelas definidas."""
        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("clean_dev.get_connection", return_value=mock_ctx):
            result = clean_dev.clean_postgres()

        executed_queries: list[str] = [
            str(c.args[0]).strip().upper()
            for c in mock_conn.execute.call_args_list
        ]

        for table in self.EXPECTED_TABLES:
            assert any(table.upper() in q for q in executed_queries), (
                f"TRUNCATE não executado para tabela: {table}"
            )

        assert result["tables_truncated"] == len(self.EXPECTED_TABLES)
        assert result["errors"] == 0

    def test_resets_llm_cache_stats(self) -> None:
        """A tabela llm_cache_stats deve ter seus contadores zerados."""
        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("clean_dev.get_connection", return_value=mock_ctx):
            clean_dev.clean_postgres()

        all_queries = " ".join(
            str(c.args[0]).upper() for c in mock_conn.execute.call_args_list
        )
        assert "LLM_CACHE_STATS" in all_queries

    def test_returns_error_on_db_failure(self) -> None:
        """Erro de banco deve ser registrado em result['errors']."""
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(side_effect=Exception("conexão recusada"))
        mock_ctx.__exit__ = MagicMock(return_value=False)

        with patch("clean_dev.get_connection", return_value=mock_ctx):
            result = clean_dev.clean_postgres()

        assert result["errors"] >= 1


# ===========================================================================
# Testes: clean_qdrant
# ===========================================================================


@pytest.mark.unit
class TestCleanQdrant:
    """Testes para a função clean_qdrant."""

    def test_deletes_all_collections(self) -> None:
        """Todas as coleções listadas devem ser deletadas."""
        mock_client = MagicMock()
        mock_col_a = MagicMock()
        mock_col_a.name = "deep_search_index"
        mock_col_b = MagicMock()
        mock_col_b.name = "documents_index"
        mock_client.get_collections.return_value.collections = [
            mock_col_a,
            mock_col_b,
        ]

        with patch("clean_dev._make_qdrant_client", return_value=mock_client):
            result = clean_dev.clean_qdrant()

        assert mock_client.delete_collection.call_count == 2
        mock_client.delete_collection.assert_any_call("deep_search_index")
        mock_client.delete_collection.assert_any_call("documents_index")
        assert result["collections_deleted"] == 2
        assert result["errors"] == 0

    def test_no_collections_is_no_op(self) -> None:
        """Qdrant sem coleções deve retornar collections_deleted=0."""
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = []

        with patch("clean_dev._make_qdrant_client", return_value=mock_client):
            result = clean_dev.clean_qdrant()

        assert result["collections_deleted"] == 0
        assert result["errors"] == 0

    def test_connection_error_returns_error(self) -> None:
        """Falha ao conectar no Qdrant deve ser registrada em result['errors']."""
        with patch(
            "clean_dev._make_qdrant_client",
            side_effect=Exception("qdrant offline"),
        ):
            result = clean_dev.clean_qdrant()

        assert result["errors"] >= 1

    def test_partial_failure_continues(self) -> None:
        """Falha em uma coleção não deve impedir a limpeza das demais."""
        mock_client = MagicMock()
        mock_col_a = MagicMock()
        mock_col_a.name = "col_a"
        mock_col_b = MagicMock()
        mock_col_b.name = "col_b"
        mock_client.get_collections.return_value.collections = [mock_col_a, mock_col_b]
        mock_client.delete_collection.side_effect = [Exception("timeout"), None]

        with patch("clean_dev._make_qdrant_client", return_value=mock_client):
            result = clean_dev.clean_qdrant()

        assert result["collections_deleted"] == 1
        assert result["errors"] == 1


# ===========================================================================
# Testes: clean_all (orquestrador principal)
# ===========================================================================


@pytest.mark.unit
class TestCleanAll:
    """Testes para a função clean_all que orquestra todas as limpezas."""

    def test_calls_all_subsystems(self, tmp_path: Path) -> None:
        """clean_all deve invocar todas as funções de limpeza."""
        with (
            patch("clean_dev.clean_logs", return_value={"removed": 2, "errors": 0}) as m_logs,
            patch("clean_dev.clean_outputs", return_value={"removed": 1, "errors": 0}) as m_out,
            patch("clean_dev.clean_postgres", return_value={"tables_truncated": 12, "errors": 0}) as m_pg,
            patch("clean_dev.clean_qdrant", return_value={"collections_deleted": 2, "errors": 0}) as m_qd,
        ):
            result = clean_dev.clean_all(
                logs_dir=tmp_path / "logs",
                outputs_dir=tmp_path / "outputs",
            )

        m_logs.assert_called_once()
        m_out.assert_called_once()
        m_pg.assert_called_once()
        m_qd.assert_called_once()

        assert result["logs"]["removed"] == 2
        assert result["outputs"]["removed"] == 1
        assert result["postgres"]["tables_truncated"] == 12
        assert result["qdrant"]["collections_deleted"] == 2

    def test_skips_postgres_when_flag_false(self, tmp_path: Path) -> None:
        """clean_all deve pular PostgreSQL quando skip_postgres=True."""
        with (
            patch("clean_dev.clean_logs", return_value={"removed": 0, "errors": 0}),
            patch("clean_dev.clean_outputs", return_value={"removed": 0, "errors": 0}),
            patch("clean_dev.clean_postgres") as m_pg,
            patch("clean_dev.clean_qdrant", return_value={"collections_deleted": 0, "errors": 0}),
        ):
            clean_dev.clean_all(
                logs_dir=tmp_path / "logs",
                outputs_dir=tmp_path / "outputs",
                skip_postgres=True,
            )

        m_pg.assert_not_called()

    def test_skips_qdrant_when_flag_false(self, tmp_path: Path) -> None:
        """clean_all deve pular Qdrant quando skip_qdrant=True."""
        with (
            patch("clean_dev.clean_logs", return_value={"removed": 0, "errors": 0}),
            patch("clean_dev.clean_outputs", return_value={"removed": 0, "errors": 0}),
            patch("clean_dev.clean_postgres", return_value={"tables_truncated": 0, "errors": 0}),
            patch("clean_dev.clean_qdrant") as m_qd,
        ):
            clean_dev.clean_all(
                logs_dir=tmp_path / "logs",
                outputs_dir=tmp_path / "outputs",
                skip_qdrant=True,
            )

        m_qd.assert_not_called()

    def test_total_errors_aggregated(self, tmp_path: Path) -> None:
        """clean_all deve agregar o total de erros de todos os subsistemas."""
        with (
            patch("clean_dev.clean_logs", return_value={"removed": 0, "errors": 1}),
            patch("clean_dev.clean_outputs", return_value={"removed": 0, "errors": 2}),
            patch("clean_dev.clean_postgres", return_value={"tables_truncated": 0, "errors": 1}),
            patch("clean_dev.clean_qdrant", return_value={"collections_deleted": 0, "errors": 0}),
        ):
            result = clean_dev.clean_all(
                logs_dir=tmp_path / "logs",
                outputs_dir=tmp_path / "outputs",
            )

        assert result["total_errors"] == 4
