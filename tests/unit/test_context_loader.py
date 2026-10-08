"""Testes unitários do pipeline de contexto `input_context/` (Roadmap V15.5 / Spec G9)."""

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.context_loader import (
    ContextLoader,
    ContextBundle,
    ProcessedDocument,
    DatasetSummary,
    ImageContext,
)


@pytest.mark.unit
class TestContextLoaderDirLifecycle:
    """Criação automática de input_context/ com README."""

    def test_cria_diretorio_e_readme_quando_ausente(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        assert not context_dir.exists()

        bundle = ContextLoader(context_dir).load()

        assert context_dir.is_dir()
        assert (context_dir / "README.md").exists()
        assert bundle.total_files == 0

    def test_nao_recria_readme_se_diretorio_ja_existe(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "README.md").write_text("conteúdo customizado", encoding="utf-8")

        ContextLoader(context_dir).load()

        assert (context_dir / "README.md").read_text(encoding="utf-8") == "conteúdo customizado"

    def test_readme_nao_e_contado_como_arquivo_de_contexto(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "README.md").write_text("x", encoding="utf-8")

        bundle = ContextLoader(context_dir).load()
        assert bundle.total_files == 0


@pytest.mark.unit
class TestTextProcessing:
    """Processamento de .txt/.md/.rst, incluindo chunking."""

    def test_processa_markdown_simples(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "context.md").write_text("# Objetivo\nReproduzir a Tabela 3.", encoding="utf-8")

        bundle = ContextLoader(context_dir).load()

        assert len(bundle.text_documents) == 1
        doc = bundle.text_documents[0]
        assert doc.format == "md"
        assert "Reproduzir a Tabela 3" in doc.text_content
        assert doc.chunks is None

    def test_chunking_para_arquivo_grande_com_overlap(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        big_text = "a" * 120_000
        (context_dir / "grande.txt").write_text(big_text, encoding="utf-8")

        bundle = ContextLoader(context_dir).load()

        doc = bundle.text_documents[0]
        assert doc.chunks is not None
        assert len(doc.chunks) >= 2
        # Overlap: o fim de um chunk deve reaparecer no início do próximo
        assert doc.chunks[0][-500:] == doc.chunks[1][:500]

    def test_fallback_latin1_quando_utf8_falha(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        path = context_dir / "legado.txt"
        path.write_bytes("café com açúcar".encode("latin-1"))

        bundle = ContextLoader(context_dir).load()

        assert len(bundle.text_documents) == 1
        assert "caf" in bundle.text_documents[0].text_content

    def test_rst_tratado_como_texto(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "notas.rst").write_text("Título\n======\nConteúdo.", encoding="utf-8")

        bundle = ContextLoader(context_dir).load()
        assert len(bundle.text_documents) == 1
        assert bundle.text_documents[0].format == "rst"


@pytest.mark.unit
class TestTabularProcessing:
    """DatasetSummary para CSV/TSV."""

    def test_csv_gera_dataset_summary_com_schema_e_amostra(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        csv_path = context_dir / "dados.csv"
        csv_path.write_text(
            "idade,especie\n1,setosa\n2,setosa\n3,versicolor\n,virginica\n5,virginica\n6,virginica\n",
            encoding="utf-8",
        )

        bundle = ContextLoader(context_dir).load()

        assert len(bundle.structured_data) == 1
        ds = bundle.structured_data[0]
        assert ds.format == "csv"
        assert ds.num_rows == 6
        assert ds.num_columns == 2
        assert set(ds.columns) == {"idade", "especie"}
        assert len(ds.sample_rows) == 5
        assert ds.stats["idade"]["nulls"] == 1

    def test_csv_invalido_retorna_extraction_errors(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        bad_path = context_dir / "vazio.csv"
        bad_path.write_bytes(b"")

        bundle = ContextLoader(context_dir).load()

        assert len(bundle.structured_data) == 1
        assert bundle.structured_data[0].extraction_errors


@pytest.mark.unit
class TestExcelProcessing:
    """DatasetSummary por aba para XLSX."""

    def test_xlsx_multiplas_abas_gera_summary_por_sheet(self, tmp_path: Path) -> None:
        pd = pytest.importorskip("pandas")
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        xlsx_path = context_dir / "planilha.xlsx"

        with pd.ExcelWriter(xlsx_path) as writer:
            pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_excel(writer, sheet_name="Sheet1", index=False)
            pd.DataFrame({"x": [5, 6, 7]}).to_excel(writer, sheet_name="Sheet2", index=False)

        bundle = ContextLoader(context_dir).load()

        assert len(bundle.structured_data) == 2
        sheet_names = {ds.sheet_name for ds in bundle.structured_data}
        assert sheet_names == {"Sheet1", "Sheet2"}


@pytest.mark.unit
class TestJsonProcessing:
    """DatasetSummary/text para JSON e JSONL."""

    def test_jsonl_trata_como_dataset_linha_a_linha(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        jsonl_path = context_dir / "registros.jsonl"
        jsonl_path.write_text(
            '{"nome": "a", "valor": 1}\n{"nome": "b", "valor": 2}\n', encoding="utf-8"
        )

        bundle = ContextLoader(context_dir).load()

        assert len(bundle.structured_data) == 1
        ds = bundle.structured_data[0]
        assert ds.num_rows == 2
        assert set(ds.columns) == {"nome", "valor"}

    def test_json_lista_de_dicts_tratado_como_dataset(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        json_path = context_dir / "dados.json"
        json_path.write_text(json.dumps([{"a": 1}, {"a": 2}]), encoding="utf-8")

        bundle = ContextLoader(context_dir).load()

        assert len(bundle.structured_data) == 1
        assert bundle.structured_data[0].num_rows == 2

    def test_json_nao_tabular_gera_schema_simples(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        json_path = context_dir / "config.json"
        json_path.write_text(json.dumps({"chave": "valor"}), encoding="utf-8")

        bundle = ContextLoader(context_dir).load()

        assert len(bundle.structured_data) == 1
        ds = bundle.structured_data[0]
        assert ds.num_rows == 1


@pytest.mark.unit
class TestImageProcessing:
    """OCR local (pytesseract) e Gemini Vision (mockados)."""

    def test_ocr_local_usado_por_padrao(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OCR_PROVIDER", "local")
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        img_path = context_dir / "grafico.png"
        img_path.write_bytes(b"fake-png-bytes")

        with patch("pytesseract.image_to_string", return_value="Texto extraído do gráfico") as mock_ocr, \
             patch("PIL.Image.open", return_value=MagicMock()):
            bundle = ContextLoader(context_dir).load()

        assert len(bundle.images) == 1
        assert bundle.images[0].provider == "local"
        assert bundle.images[0].description == "Texto extraído do gráfico"
        mock_ocr.assert_called_once()

    def test_gemini_vision_usado_quando_configurado(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OCR_PROVIDER", "gemini")
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        img_path = context_dir / "microscopia.jpg"
        img_path.write_bytes(b"fake-jpg-bytes")

        mock_response = MagicMock(text="Imagem mostra estrutura celular.")
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        # v18.5-egress-gate: a visão passa por `authorize_vision`; aqui o arquivo é liberado pelo portão.
        with patch("google.genai.Client", return_value=mock_client), \
             patch("src.egress.gate.EgressGate.authorize_vision", return_value=None) as authorize:
            bundle = ContextLoader(context_dir).load()

        authorize.assert_called_once()
        assert len(bundle.images) == 1
        assert bundle.images[0].provider == "gemini"
        assert "estrutura celular" in bundle.images[0].description

    def test_gemini_vision_recusada_para_imagem_de_pesquisa_nao_compartilhavel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cenário "Imagem de pesquisa a terceiro": a recusa vira erro de extração e nada é enviado."""
        monkeypatch.setenv("OCR_PROVIDER", "gemini")
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "microscopia.jpg").write_bytes(b"fake-jpg-bytes")
        mock_client = MagicMock()

        with patch("google.genai.Client", return_value=mock_client):
            bundle = ContextLoader(context_dir).load()

        mock_client.models.generate_content.assert_not_called()
        assert bundle.images[0].description == ""
        assert "recusado" in bundle.images[0].extraction_errors[0]

    def test_ocr_local_indisponivel_registra_erro_sem_crash(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OCR_PROVIDER", "local")
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "img.bmp").write_bytes(b"fake")

        with patch("src.context_loader.ContextLoader._ocr_image_local") as mock_ocr:
            mock_ocr.return_value = ImageContext(
                source_path=context_dir / "img.bmp",
                description="",
                provider="local",
                extraction_errors=["OCR local indisponível: dependência ausente"],
            )
            bundle = ContextLoader(context_dir).load()

        assert bundle.images[0].extraction_errors


@pytest.mark.unit
class TestPdfProcessing:
    """Extração de PDF via ExtractorRegistry, com fallback de OCR para PDFs escaneados."""

    def test_pdf_com_texto_nativo_nao_aciona_ocr(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        pdf_path = context_dir / "artigo.pdf"
        pdf_path.write_bytes(b"%PDF-fake")

        fake_extracted = MagicMock(
            text_content="Texto nativo do PDF " * 20,
            extraction_errors=[],
            format="pdf",
            title="artigo.pdf",
            num_pages=3,
        )
        with patch(
            "src.skills.document_processor.extractors.registry.ExtractorRegistry.extract",
            return_value=fake_extracted,
        ), patch("src.context_loader.ContextLoader._ocr_scanned_pdf") as mock_ocr:
            bundle = ContextLoader(context_dir).load()

        mock_ocr.assert_not_called()
        assert "Texto nativo do PDF" in bundle.text_documents[0].text_content

    def test_pdf_escaneado_aciona_ocr_fallback(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        pdf_path = context_dir / "escaneado.pdf"
        pdf_path.write_bytes(b"%PDF-fake")

        fake_extracted = MagicMock(
            text_content="",  # menos de 100 chars -> aciona OCR
            extraction_errors=[],
            format="pdf",
            title="escaneado.pdf",
            num_pages=1,
        )
        with patch(
            "src.skills.document_processor.extractors.registry.ExtractorRegistry.extract",
            return_value=fake_extracted,
        ), patch(
            "src.context_loader.ContextLoader._ocr_scanned_pdf",
            return_value=("Texto reconhecido via OCR", []),
        ) as mock_ocr:
            bundle = ContextLoader(context_dir).load()

        mock_ocr.assert_called_once()
        assert bundle.text_documents[0].text_content == "Texto reconhecido via OCR"


@pytest.mark.unit
class TestUnrecognizedFiles:
    def test_extensao_desconhecida_vira_raw_file(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "modelo.pkl").write_bytes(b"\x80\x04binary")

        bundle = ContextLoader(context_dir).load()

        assert len(bundle.raw_files) == 1
        assert bundle.raw_files[0].name == "modelo.pkl"


@pytest.mark.unit
class TestTokenEstimation:
    def test_total_tokens_estimated_soma_todas_as_fontes(self, tmp_path: Path) -> None:
        context_dir = tmp_path / "input_context"
        context_dir.mkdir()
        (context_dir / "a.md").write_text("x" * 400, encoding="utf-8")
        (context_dir / "b.csv").write_text("col\n1\n2\n", encoding="utf-8")

        bundle = ContextLoader(context_dir).load()

        assert bundle.total_tokens_estimated > 0
        assert bundle.total_tokens_estimated == sum(
            d.estimated_tokens() for d in bundle.text_documents
        ) + sum(d.estimated_tokens() for d in bundle.structured_data)


@pytest.mark.unit
class TestContextBundleRendering:
    def test_bundle_vazio_renderiza_string_vazia(self) -> None:
        assert ContextBundle().to_prompt_context() == ""

    def test_bundle_com_conteudo_inclui_secoes(self, tmp_path: Path) -> None:
        bundle = ContextBundle(
            text_documents=[
                ProcessedDocument(
                    source_path=tmp_path / "a.md", format="md", title="a.md", text_content="Hipótese X."
                )
            ],
            structured_data=[
                DatasetSummary(
                    source_path=tmp_path / "d.csv",
                    format="csv",
                    num_rows=10,
                    num_columns=2,
                    columns=["a", "b"],
                    dtypes={"a": "int64", "b": "object"},
                    sample_rows=[{"a": 1, "b": "x"}],
                    stats={"a": {"min": 1, "max": 9, "mean": 5.0, "nulls": 0}},
                )
            ],
            images=[ImageContext(source_path=tmp_path / "i.png", description="Gráfico de barras.")],
            raw_files=[tmp_path / "modelo.pkl"],
        )

        text = bundle.to_prompt_context()

        assert "Hipótese X." in text
        assert "d.csv" in text
        assert "Gráfico de barras." in text
        assert "modelo.pkl" in text

    def test_to_dict_serializa_paths_como_string(self, tmp_path: Path) -> None:
        bundle = ContextBundle(raw_files=[tmp_path / "x.bin"])
        data = bundle.to_dict()
        assert data["raw_files"] == [str(tmp_path / "x.bin")]
        json.dumps(data)  # não deve lançar exceção de serialização
