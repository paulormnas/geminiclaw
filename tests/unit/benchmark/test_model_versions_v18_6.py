"""Versão dos modelos por execução, matriz oficial e recriação das coleções do Qdrant (v18.6-models-gemini4-gpt6)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from scripts.benchmark import model_versions, report
from scripts.benchmark.run_benchmark import anomalies
from src.knowledge.graph_store import InMemoryGraphStore
from src.knowledge.semantic_index import SemanticIndex
from tests.support.controlled_embedding_provider import ControlledEmbeddingProvider

pytestmark = pytest.mark.unit


def _profile(dev_version: str = "gemini-4-argon-001", val_version: str = "desconhecida") -> dict:
    return {"papeis": {
        "developer": {"provedor_modelo": "google/gemini-4-argon", "familia_modelo": "gemini",
                      "versao_efetiva": dev_version},
        "validator": {"provedor_modelo": "anthropic/claude-sonnet-5-5", "familia_modelo": "claude",
                      "versao_efetiva": val_version},
    }}


def test_versoes_gravadas() -> None:
    record = model_versions.execution_record(_profile(), now=datetime(2026, 10, 15, tzinfo=timezone.utc))
    assert record["modelos"]["developer"] == {
        "pedido": "google/gemini-4-argon", "familia": "gemini", "versao_efetiva": "gemini-4-argon-001"}
    assert record["data_execucao"] == "2026-10-15"
    assert record["precos"]["google/gemini-4-argon"]["vigencia_ate"] == "2026-11-30"


def test_versao_nao_informada_vira_aviso_e_nao_e_anomalia() -> None:
    models = model_versions.collect_models(_profile())
    assert models["validator"]["versao_efetiva"] == "desconhecida"
    assert model_versions.version_marks(models) == ["versao_desconhecida:validator"]
    result = {"status": "exit 0", "session": "s", "outcome": {"subtasks": 2}, "stop_reason": "criterio_pesquisa",
              "operation_metrics": {}, "routing_check": {"ok": True},
              "anomalias_placar": ["versao_desconhecida:validator"]}
    assert anomalies(result) == []


def _result(rep: int, dev_version: str) -> dict:
    record = model_versions.execution_record(_profile(dev_version), now=datetime(2026, 10, 15, tzinfo=timezone.utc))
    return {"name": "c1", "repeticao": rep, "status": "exit 0", **record}


def test_tabela_no_relatorio() -> None:
    table = model_versions.render_models([_result(1, "v1"), _result(2, "v1")])
    assert "| c1 | 1 | developer | google/gemini-4-argon | v1 | 2026-10-15 |" in table
    assert "2.0/10.0/0.1, até 2026-11-30" in table


def test_versoes_diferentes_entre_repeticoes() -> None:
    warnings = model_versions.version_warnings([_result(1, "v1"), _result(2, "v2")])
    assert len(warnings) == 1 and "c1" in warnings[0] and "developer" in warnings[0]
    assert "v1" in warnings[0] and "v2" in warnings[0]
    assert model_versions.version_warnings([_result(1, "v1"), _result(2, "v1")]) == []


def test_resultado_antigo_sem_os_campos() -> None:
    old = {"name": "c0", "repeticao": 1, "status": "exit 0"}
    assert "n/d" in model_versions.render_models([old])
    assert model_versions.version_warnings([old]) == []
    assert "Modelos e versões" not in report.render([])  # o relatório antigo continua renderizando sem erro


def test_matriz_oficial() -> None:
    text = Path("scripts/benchmark/matrix_modelos_v18_6.json").read_text(encoding="utf-8")
    matrix = json.loads(text)
    assert matrix["budget_usd"] == {"anthropic": 14.0, "openai": 14.0, "google": 14.0}
    assert "gemini-3.8-flash" not in text and "gpt-5.6-terra" not in text
    assert "gemini-4-argon" in text and "gpt-6.1-sol" in text


def test_indice_semantico_recria_a_colecao_depois_do_reset() -> None:
    client = QdrantClient(location=":memory:")
    provider = ControlledEmbeddingProvider(dimension=64)
    index = SemanticIndex(InMemoryGraphStore(), client, provider=provider)
    index.ensure_collection()
    client.delete_collection(index.collection)  # o reset apaga as coleções do sistema
    fresh = SemanticIndex(InMemoryGraphStore(), client, provider=provider)
    fresh.ensure_collection()
    assert client.get_collection(fresh.collection).config.params.vectors.size == provider.info.dimension


def test_indexador_de_documentos_recria_a_colecao_depois_do_reset() -> None:
    from src.documents.indexer import DocumentIndexer
    from tests.support.fake_embedding_provider import FakeEmbeddingProvider

    kwargs = {"embedding_provider": FakeEmbeddingProvider(), "registry": object()}
    first = DocumentIndexer(":memory:", **kwargs)
    first.qdrant.delete_collection(DocumentIndexer.COLLECTION_NAME)
    first._ensure_collection()
    assert DocumentIndexer.COLLECTION_NAME in {c.name for c in first.qdrant.get_collections().collections}


def test_teto_do_google_atingido() -> None:
    from scripts.benchmark.run_benchmark import budget_skip_reason

    combo = {"roles": {"*": "google/gemini-4-argon", "VALIDATOR": "anthropic/claude-sonnet-5-5"}}
    reason = budget_skip_reason(combo, {"google": 14.0, "anthropic": 14.0}, {"google": 14.2})
    assert reason == "orçamento de google esgotado ($14.20 de $14.00)"
    assert budget_skip_reason(combo, {"google": 14.0}, {"google": 1.0}) is None


def test_teto_vale_por_rodada() -> None:
    from scripts.benchmark.run_benchmark import add_spent, budget_skip_reason

    combo = {"roles": {"*": "google/gemini-4-argon"}}
    spent: dict[int, dict[str, float]] = {}
    add_spent(spent, {"repeticao": 1, "tokens": {"cost_by_provider": {"google": 14.2}}})
    add_spent(spent, {"repeticao": 2, "tokens": {"cost_by_provider": {"google": 3.0}}})
    budget = {"google": 14.0}
    assert budget_skip_reason(combo, budget, spent[1]) is not None
    assert budget_skip_reason(combo, budget, spent[2]) is None
    assert budget_skip_reason(combo, budget, spent.get(3, {})) is None


def test_matriz_usa_esforco_de_raciocinio_aceito_pelo_gpt_sol() -> None:
    """O gpt-6.1-sol recusa `reasoning_effort=none` com HTTP 400; a matriz precisa de um valor aceito."""
    text = Path("scripts/benchmark/matrix_modelos_v18_6.json").read_text(encoding="utf-8")
    matrix = json.loads(text)
    assert "gpt-6.1-sol" in text
    assert matrix["env"]["OPENAI_REASONING_EFFORT"] in {"low", "medium", "high", "xhigh"}
