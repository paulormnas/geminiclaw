"""Cenários da spec `input-documents` (v17-input-document-index): indexação automática dos insumos."""

from __future__ import annotations

import logging

import pytest

from src.knowledge.input_index import index_input_snapshot
from tests.unit.input_index.conftest import PROJ_A, PROJ_B, DownStore, StubStore, all_points, make_session
from tests.unit.input_index.test_descriptors import _png

ARTIGO = "As pétalas medem entre dois e cinco centímetros.\n\nO caule é ereto e ramificado."
CSV = "id,massa_g\n" + "\n".join(f"{i},{777.5 + i}" for i in range(150)) + "\n"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_primeira_sessao_do_projeto(tmp_path, indexer, extractors):
    """Cenário: Primeira sessão do projeto (sem chamada de LLM: só embedding local)."""
    session = make_session(tmp_path, {"artigo.txt": ARTIGO, "dados.csv": CSV})

    report = await index_input_snapshot(session, PROJ_A, store=StubStore(), indexer=indexer, extractors=extractors)

    assert report["indexados"] == 2 and report["falhas"] == [] and report["pendentes"] == []
    points = all_points(indexer)
    by_file = {}
    for p in points:
        by_file.setdefault(p.payload["nome_arquivo"], []).append(p.payload)
    assert {x["tipo_ponto"] for x in by_file["artigo.txt"]} == {"trecho"}
    assert [x["tipo_ponto"] for x in by_file["dados.csv"]] == ["descritor"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mesmo_arquivo_na_sessao_seguinte(tmp_path, indexer, extractors, provider):
    """Cenário: Mesmo arquivo na sessão seguinte."""
    s1 = make_session(tmp_path, {"artigo.txt": ARTIGO}, "s1")
    s2 = make_session(tmp_path, {"artigo.txt": ARTIGO}, "s2")
    await index_input_snapshot(s1, PROJ_A, indexer=indexer, extractors=extractors)
    before_points = len(all_points(indexer))
    before_inputs = len(provider.inputs)

    report = await index_input_snapshot(s2, PROJ_A, indexer=indexer, extractors=extractors)

    assert report["ja_indexados"] == 1 and report["indexados"] == 0 and report["revetorizados"] == 0
    assert len(provider.inputs) == before_inputs
    assert len(all_points(indexer)) == before_points


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mesmo_arquivo_em_outro_projeto(tmp_path, indexer, extractors):
    """Cenário: Mesmo arquivo em outro projeto."""
    s1 = make_session(tmp_path, {"artigo.txt": ARTIGO}, "s1")
    s2 = make_session(tmp_path, {"artigo.txt": ARTIGO}, "s2")
    await index_input_snapshot(s1, PROJ_A, indexer=indexer, extractors=extractors)
    ids_a = {str(p.id) for p in all_points(indexer)}

    report = await index_input_snapshot(s2, PROJ_B, indexer=indexer, extractors=extractors)

    assert report["indexados"] == 1
    ids_b = {str(p.id) for p in all_points(indexer)} - ids_a
    assert ids_b and not ids_b & ids_a
    assert {p.payload["projeto_id"] for p in all_points(indexer) if str(p.id) in ids_b} == {"proj-b"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_limite_de_tempo(tmp_path, indexer, extractors):
    """Cenário: Limite de tempo (prazo esgotado: nada é indexado e os arquivos ficam em pendentes)."""
    session = make_session(tmp_path, {"a.txt": ARTIGO, "b.txt": ARTIGO + "x", "c.csv": CSV})

    report = await index_input_snapshot(session, PROJ_A, indexer=indexer, extractors=extractors, max_seconds=0)

    assert report["pendentes"] == ["a.txt", "b.txt", "c.csv"]
    assert report["indexados"] == 0
    assert all_points(indexer) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_texto_enviado_ao_modelo_de_embedding(tmp_path, indexer, extractors, provider):
    """Cenário: Texto enviado ao modelo de embedding."""
    session = make_session(tmp_path, {"artigo.txt": "As pétalas medem…"})

    await index_input_snapshot(session, PROJ_A, indexer=indexer, extractors=extractors)

    (text,) = provider.inputs
    assert text.startswith("Documento: ")
    assert "Projeto: Classificação de flores" in text
    assert "domínios: botânica" in text
    assert text.endswith("As pétalas medem…")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_busca_devolve_so_o_trecho(tmp_path, indexer, extractors):
    """Cenário: Busca devolve só o trecho."""
    session = make_session(tmp_path, {"artigo.txt": "As pétalas medem…"})
    await index_input_snapshot(session, PROJ_A, indexer=indexer, extractors=extractors)

    results = indexer.search("qualquer coisa", projeto_id="proj-a")

    assert results and results[0]["content"] == "As pétalas medem…"
    assert "Projeto:" not in results[0]["content"]
    rows = indexer.registry.get_chunks(results[0]["document_id"])
    assert all("Projeto:" not in r["content"] for r in rows)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mudanca_de_metadados_do_projeto(tmp_path, indexer, extractors, provider):
    """Cenário: Mudança de metadados do projeto."""
    from dataclasses import replace

    s1 = make_session(tmp_path, {"artigo.txt": ARTIGO}, "s1")
    s2 = make_session(tmp_path, {"artigo.txt": ARTIGO}, "s2")
    await index_input_snapshot(s1, PROJ_A, indexer=indexer, extractors=extractors)
    ids_before = {str(p.id) for p in all_points(indexer)}
    (doc,) = indexer.registry.list_documents(10, "proj-a")
    hash_before = doc["metadata_json"]["hash_cabecalho_projeto"]
    provider.inputs.clear()

    report = await index_input_snapshot(
        s2, replace(PROJ_A, objetivo="Novo objetivo da pesquisa"), indexer=indexer, extractors=extractors
    )

    assert report["revetorizados"] == 1
    assert {str(p.id) for p in all_points(indexer)} == ids_before
    assert provider.inputs and all("Novo objetivo da pesquisa" in t for t in provider.inputs)
    (doc,) = indexer.registry.list_documents(10, "proj-a")
    assert doc["metadata_json"]["hash_cabecalho_projeto"] != hash_before


@pytest.mark.unit
@pytest.mark.asyncio
async def test_csv_e_imagem_so_como_descritor(tmp_path, indexer, extractors):
    """Cenários CSV e Imagem: um único ponto descritor, sem valores nem OCR."""
    session = make_session(tmp_path, {"dados.csv": CSV})
    _png(session / "input_snapshot" / "foto.png", 7, 5)

    await index_input_snapshot(session, PROJ_A, indexer=indexer, extractors=extractors)

    points = {p.payload["nome_arquivo"]: p.payload for p in all_points(indexer)}
    assert len(points) == 2
    csv_payload = points["dados.csv"]
    assert csv_payload["tipo_ponto"] == "descritor" and "150 linhas" in csv_payload["content"]
    assert "777" not in str(csv_payload)
    assert "7x5 px" in points["foto.png"]["content"] and points["foto.png"]["tipo_ponto"] == "descritor"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_payload_completo(tmp_path, indexer, extractors):
    """Cenário: Payload completo."""
    session = make_session(tmp_path, {"artigo.txt": ARTIGO})

    await index_input_snapshot(session, PROJ_A, store=StubStore(), indexer=indexer, extractors=extractors)

    for p in all_points(indexer):
        pl = p.payload
        assert pl["insumo_id"].startswith("insumo-") and pl["projeto_id"] == "proj-a"
        assert pl["tipo_insumo"] == "artigo" and pl["visibilidade"] == "privado"
        assert pl["origem"] == "input_context" and pl["versao_enriquecimento"] == 1
        assert pl["dominios"] == ["botânica"] and len(pl["hash_conteudo"]) == 64


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("store", [None, DownStore()])
async def test_grafo_indisponivel(tmp_path, indexer, extractors, caplog, store):
    """Cenário: Grafo indisponível."""
    session = make_session(tmp_path, {"artigo.txt": ARTIGO})

    with caplog.at_level(logging.WARNING):
        report = await index_input_snapshot(session, PROJ_A, store=store, indexer=indexer, extractors=extractors)

    assert report["indexados"] == 1
    assert all(p.payload["insumo_id"] is None for p in all_points(indexer))
    assert any("insumo_id nulo" in r.message for r in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_busca_dois_projetos_e_todos_os_projetos(tmp_path, indexer, extractors):
    """Cenários: Dois projetos e Busca em todos os projetos."""
    s1 = make_session(tmp_path, {"a.txt": "texto do projeto A"}, "s1")
    s2 = make_session(tmp_path, {"b.txt": "texto do projeto B"}, "s2")
    await index_input_snapshot(s1, PROJ_A, indexer=indexer, extractors=extractors)
    await index_input_snapshot(s2, PROJ_B, indexer=indexer, extractors=extractors)

    only_a = indexer.search("texto", limit=10, projeto_id="proj-a")
    everything = indexer.search("texto", limit=10)

    assert {r["projeto_id"] for r in only_a} == {"proj-a"}
    assert {r["projeto_id"] for r in everything} == {"proj-a", "proj-b"}
    assert [d["metadata_json"]["projeto_id"] for d in indexer.list_documents(10, "proj-b")] == ["proj-b"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_qdrant_fora_do_ar_e_recuperacao(tmp_path, indexer, extractors, monkeypatch):
    """Cenários: Qdrant fora do ar e Recuperação."""
    s1 = make_session(tmp_path, {"artigo.txt": ARTIGO}, "s1")
    s2 = make_session(tmp_path, {}, "s2")
    real_upsert = indexer.qdrant.upsert

    def down(*args, **kwargs):
        raise ConnectionError("qdrant fora do ar")

    monkeypatch.setattr(indexer.qdrant, "upsert", down)
    report = await index_input_snapshot(s1, PROJ_A, indexer=indexer, extractors=extractors)

    assert report["indexados"] == 1 and report["vetorizacao_pendente"] == 1
    (doc,) = indexer.registry.list_documents(10, "proj-a")
    assert doc["metadata_json"]["vetorizacao"] == "pendente"
    assert all_points(indexer) == []

    monkeypatch.setattr(indexer.qdrant, "upsert", real_upsert)
    report = await index_input_snapshot(s2, PROJ_A, indexer=indexer, extractors=extractors)

    assert report["recuperados"] == 1
    (doc,) = indexer.registry.list_documents(10, "proj-a")
    assert doc["metadata_json"]["vetorizacao"] == "ok"
    assert len(all_points(indexer)) == 1
