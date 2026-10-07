"""Texto enriquecido dos trechos (v17-input-document-index, requisito "Texto enriquecido com metadados")."""

import pytest

from src.skills.document_processor.enrichment import (
    ProjectMeta,
    build_header,
    enriched_text,
    hash_cabecalho_projeto,
)

META = ProjectMeta(
    projeto_id="p1", titulo="Classificação de flores", objetivo="Classificar espécies", dominios=("botânica",)
)


@pytest.mark.unit
def test_header_starts_with_documento_and_has_project_and_domains():
    header = build_header(titulo="artigo.pdf", tipo_insumo="artigo", nome_arquivo="artigo.pdf", meta=META)
    text = enriched_text(header, "As pétalas medem…")

    assert text.startswith("Documento: ")
    assert "Projeto: Classificação de flores" in text
    assert "domínios: botânica" in text
    assert text.endswith("As pétalas medem…")


@pytest.mark.unit
def test_header_includes_section_only_when_given():
    sem = build_header(titulo="a", tipo_insumo="artigo", nome_arquivo="a", meta=META)
    com = build_header(titulo="a", tipo_insumo="artigo", nome_arquivo="a", meta=META, secao="Métodos")

    assert "Seção:" not in sem
    assert com.endswith("Seção: Métodos")


@pytest.mark.unit
def test_header_is_truncated_keeping_domains():
    meta = ProjectMeta(projeto_id="p1", titulo="T", objetivo="x" * 1000, dominios=("botânica",))
    header = build_header(titulo="a", tipo_insumo="artigo", nome_arquivo="a", meta=meta, max_chars=150)

    assert len(header) <= 150
    assert "domínios: botânica" in header


@pytest.mark.unit
def test_project_hash_changes_with_objective_and_domains():
    base = hash_cabecalho_projeto(META)
    assert base == hash_cabecalho_projeto(META)
    assert base != hash_cabecalho_projeto(ProjectMeta("p1", META.titulo, "Outro objetivo", META.dominios))
    assert base != hash_cabecalho_projeto(ProjectMeta("p1", META.titulo, META.objetivo, ("zoologia",)))
