"""Manifesto ``dados.yaml`` e classificação padrão (spec research-data)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.context_loader import ContextLoader
from src.egress.classification import classify_path
from src.egress.fragments import ContentOrigin
from src.research_data.manifest import ManifestError, load_manifest

from .conftest import write_manifest

pytestmark = pytest.mark.unit

CSV = "a,b\n1,2\n3,4\n"


def test_dataset_publico_vem_do_manifesto(context_dir: Path):
    (context_dir / "publicos").mkdir()
    (context_dir / "publicos" / "uci.csv").write_text(CSV, encoding="utf-8")
    write_manifest(
        context_dir,
        "versao: 1\narquivos:\n  - caminho: publicos/uci.csv\n    marcacao: compartilhavel\n"
        "    motivo: Dataset público, DOI 10.24432/C59K5F\n",
    )
    bundle = ContextLoader(context_dir).load()
    marking = bundle.marking_for(context_dir / "publicos" / "uci.csv")
    assert marking.classe is ContentOrigin.DADO_DE_PESQUISA
    assert marking.compartilhavel and marking.origem == "manifesto"
    assert marking.motivo == "Dataset público, DOI 10.24432/C59K5F"


def test_caminho_fora_do_diretorio(context_dir: Path):
    write_manifest(
        context_dir, "versao: 1\narquivos:\n  - caminho: ../segredos.csv\n    marcacao: dado_de_pesquisa\n"
    )
    with pytest.raises(ManifestError) as info:
        load_manifest(context_dir)
    assert "../segredos.csv" in str(info.value) and "linha 3" in str(info.value)


def test_caminho_absoluto(context_dir: Path):
    write_manifest(context_dir, "versao: 1\narquivos:\n  - caminho: /etc/passwd\n    marcacao: dado_de_pesquisa\n")
    with pytest.raises(ManifestError, match="absoluto"):
        load_manifest(context_dir)


def test_marcacoes_conflitantes(context_dir: Path):
    (context_dir / "medicoes.csv").write_text(CSV, encoding="utf-8")
    write_manifest(
        context_dir,
        "versao: 1\narquivos:\n"
        "  - caminho: '*.csv'\n    marcacao: compartilhavel\n    motivo: público\n"
        "  - caminho: medicoes.csv\n    marcacao: dado_de_pesquisa\n",
    )
    with pytest.raises(ManifestError) as info:
        ContextLoader(context_dir).load()
    message = str(info.value)
    assert "*.csv" in message and "medicoes.csv" in message and "conflitantes" in message


def test_compartilhavel_sem_motivo(context_dir: Path):
    write_manifest(context_dir, "versao: 1\narquivos:\n  - caminho: x.csv\n    marcacao: compartilhavel\n")
    with pytest.raises(ManifestError, match="motivo"):
        load_manifest(context_dir)


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("versao: 2\narquivos: []\n", "versao"),
        ("versao: 1\nextra: 1\n", "chave desconhecida"),
        ("versao: 1\narquivos:\n  - caminho: a.csv\n    marcacao: publico\n", "marcacao"),
        (
            "versao: 1\narquivos:\n  - caminho: a.csv\n    marcacao: dado_de_pesquisa\n    cor: azul\n",
            "chave desconhecida",
        ),
        ("versao: 1\narquivos: texto\n", "lista"),
        ("- a\n- b\n", "mapa"),
    ],
)
def test_esquema_estrito(context_dir: Path, text: str, fragment: str):
    write_manifest(context_dir, text)
    with pytest.raises(ManifestError, match=fragment):
        load_manifest(context_dir)


def test_symlink_que_sai_do_diretorio_e_recusado(context_dir: Path, tmp_path: Path):
    outside = tmp_path / "fora.csv"
    outside.write_text(CSV, encoding="utf-8")
    (context_dir / "link.csv").symlink_to(outside)
    write_manifest(
        context_dir, "versao: 1\narquivos:\n  - caminho: link.csv\n    marcacao: compartilhavel\n    motivo: x\n"
    )
    with pytest.raises(ManifestError, match="resolve fora"):
        ContextLoader(context_dir).load()


def test_padrao_sem_arquivo_gera_warning(context_dir: Path):
    (context_dir / "a.csv").write_text(CSV, encoding="utf-8")
    write_manifest(context_dir, "versao: 1\narquivos:\n  - caminho: nao_existe/*.csv\n    marcacao: dado_de_pesquisa\n")
    bundle = ContextLoader(context_dir).load()
    assert any("nao_existe/*.csv" in w for w in bundle.manifest_warnings)


def test_manifesto_nao_e_contexto(context_dir: Path):
    (context_dir / "a.csv").write_text(CSV, encoding="utf-8")
    write_manifest(context_dir, "versao: 1\narquivos: []\n")
    bundle = ContextLoader(context_dir).load()
    assert bundle.total_files == 1
    assert all(m.caminho != "dados.yaml" for m in bundle.markings.values())


def test_sem_manifesto_todos_com_origem_padrao(context_dir: Path):
    (context_dir / "a.csv").write_text(CSV, encoding="utf-8")
    (context_dir / "nota.md").write_text("texto", encoding="utf-8")
    bundle = ContextLoader(context_dir).load()
    records = {r["caminho"]: r for r in bundle.research_data_markings()}
    assert records["a.csv"]["origem"] == "padrao" and records["a.csv"]["classe_efetiva"] == "dado_de_pesquisa"
    assert records["nota.md"]["classe_efetiva"] == "documento"
    assert all(r["sha256"] for r in records.values())


@pytest.mark.parametrize(
    "name, expected",
    [
        ("a.csv", ContentOrigin.DADO_DE_PESQUISA),
        ("a.xlsx", ContentOrigin.DADO_DE_PESQUISA),
        ("a.jsonl", ContentOrigin.DADO_DE_PESQUISA),
        ("a.png", ContentOrigin.DADO_DE_PESQUISA),
        ("a.bin", ContentOrigin.DADO_DE_PESQUISA),
        ("a.txt", ContentOrigin.DOCUMENTO),
        ("a.pdf", ContentOrigin.DOCUMENTO),
        ("a.docx", ContentOrigin.DOCUMENTO),
    ],
)
def test_classificacao_padrao(context_dir: Path, name: str, expected: ContentOrigin):
    (context_dir / name).write_bytes(b"x")
    manifest = load_manifest(context_dir)
    assert classify_path(context_dir / name, manifest=manifest) is expected


def test_marcacao_explicita_vence_a_regra_padrao(context_dir: Path):
    (context_dir / "caderno.pdf").write_bytes(b"x")
    write_manifest(context_dir, "versao: 1\narquivos:\n  - caminho: cadernos/*.pdf\n    marcacao: dado_de_pesquisa\n")
    (context_dir / "cadernos").mkdir()
    (context_dir / "cadernos" / "lab.pdf").write_bytes(b"x")
    manifest = load_manifest(context_dir)
    assert classify_path(context_dir / "cadernos" / "lab.pdf", manifest=manifest) is ContentOrigin.DADO_DE_PESQUISA
    assert classify_path(context_dir / "caderno.pdf", manifest=manifest) is ContentOrigin.DOCUMENTO
