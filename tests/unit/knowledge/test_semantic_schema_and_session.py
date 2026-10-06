"""Schema (``estado_vetorizacao``), DDL idempotente e reconciliação no início da sessão."""

from pathlib import Path

import pytest

from src.knowledge import schema, validation
from src.knowledge.errors import InvalidEnumValueError
from src.knowledge.semantic_runtime import SemanticRuntime, reconcile_on_session_start
from tests.support.controlled_embedding_provider import pair_vectors
from tests.unit.knowledge.conftest import DIM

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.unit
class TestSchemaVetorizacao:
    @pytest.mark.parametrize("label", sorted(schema.VECTORIZABLE_LABELS))
    def test_rotulos_vetorizados_tem_estado_vetorizacao(self, label):
        prop = schema.NODE_SCHEMAS[label].properties["estado_vetorizacao"]
        assert prop.enum == ("pendente", "ok") and not prop.required

    @pytest.mark.parametrize("label", ["Sessao", "Insumo", "Experimento", "Resultado"])
    def test_rotulos_nao_vetorizados_nao_tem(self, label):
        assert "estado_vetorizacao" not in schema.NODE_SCHEMAS[label].properties

    def test_valor_invalido_e_rejeitado(self):
        with pytest.raises(InvalidEnumValueError):
            validation.validate_node_update("Problema", {"estado_vetorizacao": "talvez"})


@pytest.mark.unit
class TestDdl:
    def test_init_db_cria_similarity_queue_de_forma_idempotente(self):
        sql = (ROOT / "scripts" / "init_db.sql").read_text(encoding="utf-8")
        assert "CREATE TABLE IF NOT EXISTS similarity_queue" in sql
        assert "CREATE INDEX IF NOT EXISTS idx_simq_pendente ON similarity_queue (status, prioridade DESC)" in sql
        trecho = sql[sql.index("similarity_queue") :]
        assert "DROP " not in trecho.upper() and "DELETE " not in trecho.upper()


def _raise(exc):
    def _inner(*args, **kwargs):
        raise exc

    return _inner


@pytest.mark.unit
class TestReconciliacaoNaSessao:
    def test_reconcilia_pendentes(self, env, monkeypatch):
        va, _ = pair_vectors(DIM, 0, 1.0)
        env.provider.vectors["titulo: P1"] = va
        env.index.ensure_collection()
        original = env.client.upsert
        monkeypatch.setattr(env.client, "upsert", _raise(ConnectionError("fora")))
        node_id = env.make("Problema", titulo="P1")
        monkeypatch.setattr(env.client, "upsert", original)
        runtime = SemanticRuntime(store=env.store, raw_store=env.raw, index=env.index, queue=env.queue)

        report = reconcile_on_session_start(runtime)

        assert report is not None and report.reindexed == 1
        assert env.node(node_id).properties["estado_vetorizacao"] == "ok"

    def test_falha_do_qdrant_nao_impede_a_sessao(self, env, monkeypatch):
        monkeypatch.setattr(env.client, "get_collections", _raise(ConnectionError("fora")))
        runtime = SemanticRuntime(store=env.store, raw_store=env.raw, index=env.index, queue=env.queue)
        assert reconcile_on_session_start(runtime) is None
