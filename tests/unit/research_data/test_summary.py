"""Resumo seguro de datasets e amostras só para destinos permitidos (spec research-data)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.context_loader import ContextLoader
from src.research_data.summary import ceil_1sig, floor_1sig

from .conftest import write_manifest

pytestmark = pytest.mark.unit


def _safe_text(context_dir: Path, name: str, k: int = 10) -> str:
    bundle = ContextLoader(context_dir, min_group_size=k).load()
    ds = next(d for d in bundle.structured_data if d.source_path.name == name)
    return ds.safe_text


def test_descritores_de_formato_sem_valores(context_dir: Path):
    linhas = "\n".join(f"{i};{20 + i * 0.5:.1f}".replace(".", ",") for i in range(1, 31))
    (context_dir / "medicoes.csv").write_bytes(
        ("instante;temperatura (°C)\n" + linhas + "\n").encode("latin-1")
    )
    bundle = ContextLoader(context_dir, min_group_size=10).load()
    ds = bundle.structured_data[0]
    assert not ds.extraction_errors
    text = ds.safe_text
    assert "codificação utf-8" in text or "codificação latin-1" in text
    assert "separador ';'" in text and "decimal ','" in text and "cabeçalho presente" in text
    assert "[unidade °C]" in text
    # Nenhum valor de célula no resumo seguro.
    for value in ("20,5", "35,0", "21,0"):
        assert value not in text


def test_codificacao_latin1_detectada(context_dir: Path):
    rows = "\n".join(f"{i};açúcar{i}" for i in range(30))
    (context_dir / "nomes.csv").write_bytes(("id;descrição\n" + rows + "\n").encode("latin-1"))
    bundle = ContextLoader(context_dir, min_group_size=10).load()
    assert not bundle.structured_data[0].extraction_errors
    assert "codificação latin-1" in bundle.structured_data[0].safe_text


def test_coluna_abaixo_de_k_so_traz_n_e_tipo(context_dir: Path):
    linhas = "\n".join(str(i + 0.123) for i in range(5))
    (context_dir / "pequeno.csv").write_text("x\n" + linhas + "\n", encoding="utf-8")
    text = _safe_text(context_dir, "pequeno.csv", k=10)
    line = next(line for line in text.splitlines() if line.startswith("- x"))
    assert "n=5" in line and "float64" in line
    assert "média" not in line and "faixa" not in line
    for value in ("0.123", "4.123"):
        assert value not in text


def test_extremos_em_faixa(context_dir: Path):
    valores = [12.3, 38.9] + [20.0 + i * 0.4 for i in range(28)]
    (context_dir / "temp.csv").write_text("t\n" + "\n".join(str(v) for v in valores) + "\n", encoding="utf-8")
    text = _safe_text(context_dir, "temp.csv")
    assert "faixa ≈ [10, 40]" in text
    assert "12.3" not in text and "38.9" not in text
    assert "média" in text and "desvio" in text


def test_categorica_traz_so_o_numero_de_distintos(context_dir: Path):
    rotulos = ["alfa", "beta", "gama", "delta", "epsilon", "zeta"]
    (context_dir / "sensores.csv").write_text(
        "sensor\n" + "\n".join(rotulos[i % 6] for i in range(30)) + "\n", encoding="utf-8"
    )
    text = _safe_text(context_dir, "sensores.csv")
    assert "6 valores distintos" in text
    assert not any(label in text for label in rotulos)


def test_data_traz_so_anos(context_dir: Path):
    datas = [f"{(i % 28) + 1:02d}/{(i % 12) + 1:02d}/{2024 + (i % 2)}" for i in range(30)]
    (context_dir / "datas.csv").write_text("quando\n" + "\n".join(datas) + "\n", encoding="utf-8")
    text = _safe_text(context_dir, "datas.csv")
    assert "anos 2024–2025" in text and "%d/%m/%Y" in text
    assert "05/05/2024" not in text


def test_regressao_nenhum_valor_de_celula_no_resumo_seguro(context_dir: Path):
    """Tarefa 5.2: o resumo seguro não contém nenhum valor de célula do dataset."""
    import pandas as pd

    rng_values = [round(101.3721 + i * 3.14159 + (i % 7) * 0.00731, 4) for i in range(60)]
    frame = pd.DataFrame(
        {
            "leitura": rng_values,
            "inteiro": [100003 + i * 17 for i in range(60)],
            "origem": [f"estacao_secreta_{i % 8}" for i in range(60)],
            "dia": [f"2024-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}" for i in range(60)],
        }
    )
    frame.to_csv(context_dir / "dados.csv", index=False)
    text = _safe_text(context_dir, "dados.csv")
    for column in frame.columns:
        for value in frame[column].astype(str):
            if value in (column,) or not re.search(r"\d|_", value):
                continue
            assert value not in text, f"valor de célula vazou no resumo seguro: {value}"
    assert "estacao_secreta" not in text


def test_faixa_a_um_algarismo_significativo():
    assert (floor_1sig(12.3), ceil_1sig(38.9)) == ("10", "40")
    assert (floor_1sig(-12.3), ceil_1sig(-3.2)) == ("-20", "-3")
    assert (floor_1sig(0.0123), ceil_1sig(0.0187)) == ("0.01", "0.02")
    assert (floor_1sig(0), ceil_1sig(0)) == ("0", "0")


def test_sem_k_configurado_toda_coluna_fica_abaixo_de_k(context_dir: Path, monkeypatch):
    monkeypatch.setattr("src.config.LOCALITY_MIN_GROUP_SIZE", None)
    (context_dir / "x.csv").write_text("v\n" + "\n".join(str(i) for i in range(50)) + "\n", encoding="utf-8")
    bundle = ContextLoader(context_dir).load()
    assert "média" not in bundle.structured_data[0].safe_text


def test_json_nao_tabular_traz_tipo_e_contagem(context_dir: Path):
    (context_dir / "lista.json").write_text("[1, 2, 3, 4, 5, 6, 7]", encoding="utf-8")
    bundle = ContextLoader(context_dir).load()
    ds = bundle.structured_data[0]
    assert "Tipo de nível superior: int" in ds.safe_text and "Registros: 7" in ds.safe_text
    assert ds.sample_rows == [1, 2, 3, 4, 5]


# --- amostras só para destinos permitidos ---------------------------------------------------------------------------

def _planner_prompt(bundle, gate, dest) -> str:
    from src.egress.fragments import ContentOrigin, PromptFragment, labeled

    message = labeled("user", PromptFragment("plano\n" + bundle.to_marked_context(), ContentOrigin.INSTRUCAO))
    prepared = gate.prepare_llm([message], None, dest)
    return prepared.messages[0]["content"]


def _write_sensitive_csv(context_dir: Path, name: str = "medicoes.csv") -> None:
    rows = "\n".join(f"{i},{777.0 + i}" for i in range(30))
    (context_dir / name).write_text("id,leitura\n" + rows + "\n", encoding="utf-8")


def test_planejador_de_terceiro_nao_ve_as_linhas(context_dir: Path, gate, third_party):
    _write_sensitive_csv(context_dir)
    bundle = ContextLoader(context_dir, min_group_size=10).load()
    prompt = _planner_prompt(bundle, gate, third_party)
    assert "Dataset: medicoes.csv" in prompt  # resumo seguro
    assert "dado de pesquisa retido" in prompt  # aviso de retenção
    assert "777.0" not in prompt and "778.0" not in prompt


def test_planejador_com_dados_brutos_ve_o_resumo_e_a_amostra(context_dir: Path, gate, local_node):
    _write_sensitive_csv(context_dir)
    bundle = ContextLoader(context_dir, min_group_size=10).load()
    prompt = _planner_prompt(bundle, gate, local_node)
    assert "Dataset: medicoes.csv" in prompt
    assert "777.0" in prompt and "Amostra (5 primeiras linhas)" in prompt


def test_dataset_compartilhavel_vai_ao_terceiro(context_dir: Path, gate, third_party):
    _write_sensitive_csv(context_dir, "publico.csv")
    write_manifest(
        context_dir,
        "versao: 1\narquivos:\n  - caminho: publico.csv\n    marcacao: compartilhavel\n    motivo: DOI 10.1/x\n",
    )
    bundle = ContextLoader(context_dir, min_group_size=10).load()
    prompt = _planner_prompt(bundle, gate, third_party)
    assert "777.0" in prompt and "dado de pesquisa retido" not in prompt


def test_to_prompt_context_devolve_so_a_versao_segura(context_dir: Path):
    _write_sensitive_csv(context_dir)
    text = ContextLoader(context_dir, min_group_size=10).load().to_prompt_context()
    assert "Dataset: medicoes.csv" in text and "777.0" not in text and "Amostra" not in text


def test_pdf_marcado_como_dado_vira_trecho_de_dado(context_dir: Path, gate, third_party):
    from unittest.mock import MagicMock, patch

    (context_dir / "cadernos").mkdir()
    (context_dir / "cadernos" / "lab.pdf").write_bytes(b"%PDF-fake")
    write_manifest(context_dir, "versao: 1\narquivos:\n  - caminho: cadernos/*.pdf\n    marcacao: dado_de_pesquisa\n")
    extracted = MagicMock(
        text_content="Medição 4242.5 mV na amostra 7. " * 10, extraction_errors=[], format="pdf",
        title="Caderno de laboratório", num_pages=12,
    )
    with patch(
        "src.skills.document_processor.extractors.registry.ExtractorRegistry.extract", return_value=extracted
    ):
        bundle = ContextLoader(context_dir, min_group_size=10).load()
    fragments = bundle.to_fragments()
    from src.egress.fragments import ContentOrigin

    origins = [f.origin for f in fragments]
    assert ContentOrigin.DADO_DE_PESQUISA in origins and ContentOrigin.DOCUMENTO not in origins
    safe = next(f for f in fragments if f.origin is ContentOrigin.ESQUEMA_AGREGADO)
    assert "Caderno de laboratório" in safe.text and "12 páginas" in safe.text and "4242.5" not in safe.text
    prompt = _planner_prompt(bundle, gate, third_party)
    assert "4242.5" not in prompt and "12 páginas" in prompt


def test_documento_padrao_vai_como_trecho_documento(context_dir: Path):
    from src.egress.fragments import ContentOrigin

    (context_dir / "objetivo.md").write_text("Objetivo da pesquisa", encoding="utf-8")
    fragments = ContextLoader(context_dir, min_group_size=10).load().to_fragments()
    doc = next(f for f in fragments if f.origin is ContentOrigin.DOCUMENTO)
    assert "Objetivo da pesquisa" in doc.text and doc.source == "input_context/objetivo.md"
