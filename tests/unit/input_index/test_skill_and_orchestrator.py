"""Skill `document_processor`, orquestrador, lista dos agentes e reindexação (v17-input-document-index)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_runtime.context import AgentContext, current_context
from src.embeddings.reindex import CollectionReindexer, text_to_embed
from src.orchestrator import Orchestrator
from src.skills.document_processor.extractors.registry import ExtractorRegistry
from src.skills.document_processor.indexer import DocumentIndexer
from src.skills.document_processor.registry_store import InMemoryDocumentRegistry
from src.skills.document_processor.skill import DocumentProcessorSkill
from tests.support.fake_embedding_provider import FakeEmbeddingProvider
from tests.unit.input_index.conftest import PROJ_A, PROJ_B


@pytest.fixture(autouse=True)
def _clear_context():
    token = current_context.set(None)
    yield
    current_context.reset(token)


class _Skill(DocumentProcessorSkill):
    """`DocumentProcessorSkill` não implementa `run` (abstrato) e não instancia; só `execute_async` importa aqui."""

    async def run(self, **kwargs):  # pragma: no cover
        raise NotImplementedError


def _skill(provider) -> DocumentProcessorSkill:
    skill = _Skill.__new__(_Skill)
    skill.extractor_registry = ExtractorRegistry()
    skill.indexer = DocumentIndexer(url=":memory:", embedding_provider=provider, registry=InMemoryDocumentRegistry())
    return skill


def _bind(tmp_path: Path, project_id: str | None, meta=None) -> AgentContext:
    ctx = AgentContext(
        session_id="s", agent_session_id="s-a", agent_id="researcher", mode="auto",
        output_dir=tmp_path / "outputs" / "s", model="m", project_id=project_id,
        extra={"project_meta": meta} if meta else {},
    )
    current_context.set(ctx)
    return ctx


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingest_de_artefato_usa_o_mesmo_caminho_com_deduplicacao(tmp_path, provider):
    skill = _skill(provider)
    ctx = _bind(tmp_path, "proj-a", PROJ_A)
    art = ctx.output_dir / "artifacts" / "resumo.md"
    art.parent.mkdir(parents=True)
    art.write_text("Resumo dos resultados da pesquisa.")

    first = await skill.execute_async(action="ingest", file_path=str(art))
    second = await skill.execute_async(action="ingest", file_path=str(art))

    assert first["success"] and first["status"] == "indexado"
    assert second["status"] == "ja_indexado" and second["document_id"] == first["document_id"]
    (doc,) = skill.indexer.registry.list_documents(10, "proj-a")
    assert doc["metadata_json"]["origem"] == "artefato"
    assert "Projeto: Classificação de flores" in provider.inputs[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_busca_e_lista_do_agente_restritas_ao_projeto_da_sessao(tmp_path, provider):
    """Cenários Dois projetos e Busca em todos os projetos, pela skill."""
    skill = _skill(provider)
    for pid, meta, name in (("proj-a", PROJ_A, "a.md"), ("proj-b", PROJ_B, "b.md")):
        ctx = _bind(tmp_path, pid, meta)
        f = ctx.output_dir / "artifacts" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"texto de {pid}")
        await skill.execute_async(action="ingest", file_path=str(f))

    _bind(tmp_path, "proj-a", PROJ_A)
    only = await skill.execute_async(action="search", query="texto")
    todos = await skill.execute_async(action="search", query="texto", todos_os_projetos=True)
    listed = await skill.execute_async(action="list")

    assert {r["projeto_id"] for r in only["results"]} == {"proj-a"}
    assert {r["projeto_id"] for r in todos["results"]} == {"proj-a", "proj-b"}
    assert [d["projeto_id"] for d in listed["documents"]] == ["proj-a"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_index_inputs_grava_relatorio_no_payload(tmp_path):
    orch = Orchestrator(session_manager=MagicMock(), agent_runtime=MagicMock())
    orch._open_knowledge_store = MagicMock(return_value=None)
    orch.session_manager.get.return_value = MagicMock(payload={"mode": "auto"})
    report = {"indexados": 1, "pendentes": []}

    with patch("src.knowledge.input_index.index_input_snapshot", AsyncMock(return_value=report)):
        with patch("src.knowledge.input_index.load_project_meta", MagicMock(return_value=PROJ_A)):
            result = await orch._index_inputs("sess", "proj-a")

    assert result == report
    update = orch.session_manager.update.call_args
    assert update.kwargs["payload"]["input_index"] == report and update.kwargs["payload"]["mode"] == "auto"
    assert orch._project_metas["sess"].projeto_id == "proj-a"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_index_inputs_nunca_interrompe_a_sessao():
    orch = Orchestrator(session_manager=MagicMock(), agent_runtime=MagicMock())
    orch._open_knowledge_store = MagicMock(side_effect=RuntimeError("sem grafo"))

    with patch("src.knowledge.input_index.index_input_snapshot", AsyncMock(side_effect=RuntimeError("boom"))):
        report = await orch._index_inputs("sess", "proj-a")
        assert report is not None and report["erro"] == "RuntimeError"

    assert await orch._index_inputs("sess", None) is None
    with patch("src.config.INPUT_INDEX_ENABLED", False):
        assert await orch._index_inputs("sess", "proj-a") is None


@pytest.mark.unit
def test_reindex_refaz_texto_enriquecido():
    payload = {"content": "trecho", "cabecalho": "Documento: x"}
    assert text_to_embed(payload).startswith("Documento: x") and text_to_embed(payload).endswith("trecho")
    assert text_to_embed({"content": "trecho"}) == "trecho"

    point = MagicMock()
    point.id = "p1"
    point.payload = {**payload, "embedding_model": "velho", "embedding_version": "0"}
    client = MagicMock()
    existing = MagicMock()
    existing.name = "geminiclaw_documents"
    client.get_collections.return_value.collections = [existing]
    client.scroll.return_value = ([point], None)
    client.get_collection.return_value.config.params.vectors.size = 8
    seen: list[str] = []

    class Rec(FakeEmbeddingProvider):
        def embed_documents(self, texts):
            seen.extend(texts)
            return super().embed_documents(texts)

    report = CollectionReindexer("geminiclaw_documents", embedding_provider=Rec(dimension=8), client=client).run()

    assert report.updated == 1 and seen == ["Documento: x\n---\ntrecho"]
