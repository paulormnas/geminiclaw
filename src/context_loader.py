"""Pipeline de ingestão de contexto científico via `input_context/` (Roadmap V15.5 / Spec G9).

Permite ao pesquisador depositar arquivos de múltiplos formatos em uma pasta
dedicada antes de iniciar a sessão. O `ContextLoader` os processa
automaticamente, converte para texto/estatísticas estruturadas, e produz um
`ContextBundle` pronto para ser injetado no contexto inicial do Researcher
Agent — sem necessidade de flags no CLI ou reformatação manual.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.logger import get_logger

logger = get_logger(__name__)

_TEXT_EXTENSIONS = {".txt", ".md", ".rst"}
_TABULAR_EXTENSIONS = {".csv", ".tsv"}
_EXCEL_EXTENSIONS = {".xlsx", ".xls", ".ods"}
_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".pptx"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
_JSON_EXTENSIONS = {".json", ".jsonl"}

_CHUNK_SIZE_CHARS = 50_000
_CHUNK_OVERLAP_CHARS = 500
_PDF_NATIVE_TEXT_MIN_CHARS = 100
# Regra prática ~4 caracteres por token para estimativa rápida sem tokenizer.
_CHARS_PER_TOKEN_ESTIMATE = 4


@dataclass
class ProcessedDocument:
    """Documento textual processado (Markdown/TXT/RST/PDF/DOCX/PPTX)."""

    source_path: Path
    format: str
    title: str
    text_content: str
    chunks: list[str] | None = None
    num_pages: int | None = None
    extraction_errors: list[str] = field(default_factory=list)

    def estimated_tokens(self) -> int:
        return len(self.text_content) // _CHARS_PER_TOKEN_ESTIMATE


@dataclass
class DatasetSummary:
    """Resumo estatístico de um dataset tabular (CSV/TSV/XLSX/JSON/JSONL)."""

    source_path: Path
    format: str
    sheet_name: str | None = None
    num_rows: int = 0
    num_columns: int = 0
    columns: list[str] = field(default_factory=list)
    dtypes: dict[str, str] = field(default_factory=dict)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    extraction_errors: list[str] = field(default_factory=list)

    def estimated_tokens(self) -> int:
        return len(json.dumps(self.sample_rows, default=str)) // _CHARS_PER_TOKEN_ESTIMATE


@dataclass
class ImageContext:
    """Descrição textual de uma imagem (OCR local ou Gemini Vision)."""

    source_path: Path
    description: str
    provider: str = "local"
    extraction_errors: list[str] = field(default_factory=list)

    def estimated_tokens(self) -> int:
        return len(self.description) // _CHARS_PER_TOKEN_ESTIMATE


@dataclass
class ContextBundle:
    """Pacote consolidado de todo o contexto carregado de `input_context/`."""

    text_documents: list[ProcessedDocument] = field(default_factory=list)
    structured_data: list[DatasetSummary] = field(default_factory=list)
    images: list[ImageContext] = field(default_factory=list)
    raw_files: list[Path] = field(default_factory=list)
    total_tokens_estimated: int = 0

    @property
    def total_files(self) -> int:
        return len(self.text_documents) + len(self.structured_data) + len(self.images) + len(self.raw_files)

    def to_prompt_context(self) -> str:
        """Renderiza o bundle como bloco de texto para injeção no prompt do Researcher."""
        if self.total_files == 0:
            return ""

        parts: list[str] = ["[CONTEXTO CIENTÍFICO PRÉ-CURADO — input_context/]"]

        for doc in self.text_documents:
            parts.append(f"\n### Documento: {doc.title} ({doc.format})")
            if doc.extraction_errors:
                parts.append(f"[erro de extração: {'; '.join(doc.extraction_errors)}]")
            elif doc.chunks:
                parts.append(doc.chunks[0] + f"\n[... documento truncado em {len(doc.chunks)} blocos ...]")
            else:
                parts.append(doc.text_content)

        for ds in self.structured_data:
            label = f"{ds.source_path.name}" + (f" [{ds.sheet_name}]" if ds.sheet_name else "")
            parts.append(f"\n### Dataset: {label} ({ds.format})")
            if ds.extraction_errors:
                parts.append(f"[erro de extração: {'; '.join(ds.extraction_errors)}]")
                continue
            parts.append(f"Linhas: {ds.num_rows} | Colunas: {ds.num_columns}")
            parts.append(f"Tipos: {json.dumps(ds.dtypes, ensure_ascii=False)}")
            parts.append(f"Amostra (5 primeiras linhas): {json.dumps(ds.sample_rows, ensure_ascii=False, default=str)}")
            parts.append(f"Estatísticas: {json.dumps(ds.stats, ensure_ascii=False, default=str)}")

        for img in self.images:
            parts.append(f"\n### Imagem: {img.source_path.name} (via {img.provider})")
            if img.extraction_errors:
                parts.append(f"[erro de extração: {'; '.join(img.extraction_errors)}]")
            else:
                parts.append(img.description)

        if self.raw_files:
            names = ", ".join(p.name for p in self.raw_files)
            parts.append(f"\n### Arquivos não processados (disponíveis por caminho): {names}")

        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serializa o bundle para JSON (payload IPC inicial do Researcher)."""

        def _doc(d: ProcessedDocument) -> dict[str, Any]:
            return {
                "source_path": str(d.source_path),
                "format": d.format,
                "title": d.title,
                "text_content": d.text_content,
                "chunks": d.chunks,
                "num_pages": d.num_pages,
                "extraction_errors": d.extraction_errors,
            }

        def _ds(d: DatasetSummary) -> dict[str, Any]:
            return {
                "source_path": str(d.source_path),
                "format": d.format,
                "sheet_name": d.sheet_name,
                "num_rows": d.num_rows,
                "num_columns": d.num_columns,
                "columns": d.columns,
                "dtypes": d.dtypes,
                "sample_rows": d.sample_rows,
                "stats": d.stats,
                "extraction_errors": d.extraction_errors,
            }

        def _img(d: ImageContext) -> dict[str, Any]:
            return {
                "source_path": str(d.source_path),
                "description": d.description,
                "provider": d.provider,
                "extraction_errors": d.extraction_errors,
            }

        return {
            "text_documents": [_doc(d) for d in self.text_documents],
            "structured_data": [_ds(d) for d in self.structured_data],
            "images": [_img(d) for d in self.images],
            "raw_files": [str(p) for p in self.raw_files],
            "total_tokens_estimated": self.total_tokens_estimated,
        }


_INPUT_CONTEXT_README = """# input_context/

Deposite aqui os arquivos de contexto científico da sua sessão antes de executar
`geminiclaw`. O sistema carrega e processa automaticamente esta pasta antes de
iniciar a sessão — não é necessário nenhum flag no CLI.

Formatos suportados:
- `context.md`, `.txt`, `.rst` — objetivo, hipóteses, instruções (chunked se > 50.000 chars)
- `.pdf`, `.docx`, `.pptx` — artigos e documentos de referência
- `.csv`, `.tsv`, `.xlsx`, `.xls`, `.ods` — datasets (resumidos: schema, amostra, estatísticas)
- `.json`, `.jsonl` — dados estruturados ou schemas
- `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp` — imagens (OCR local ou Gemini Vision)

Após a sessão, uma cópia imutável do que foi usado fica em
`outputs/<session_id>/input_snapshot/`. Esta pasta (`input_context/`) NÃO é
limpa automaticamente — rode `geminiclaw clear-context` quando quiser
prepará-la para a próxima sessão.
"""


def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE_CHARS, overlap: int = _CHUNK_OVERLAP_CHARS) -> list[str]:
    """Divide texto longo em blocos com sobreposição para não perder contexto nas bordas."""
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


class ContextLoader:
    """Escaneia `input_context/`, classifica e processa arquivos por tipo."""

    def __init__(self, context_dir: str | Path | None = None):
        from src.config import INPUT_CONTEXT_DIR

        self.context_dir = Path(context_dir) if context_dir is not None else Path(INPUT_CONTEXT_DIR)

    def _ensure_dir(self) -> bool:
        """Garante que o diretório exista, criando-o com um README na primeira vez.

        Returns:
            True se o diretório já existia, False se foi criado agora.
        """
        existed = self.context_dir.is_dir()
        if not existed:
            self.context_dir.mkdir(parents=True, exist_ok=True)
            (self.context_dir / "README.md").write_text(_INPUT_CONTEXT_README, encoding="utf-8")
            logger.info(
                "input_context/ criado automaticamente com README",
                extra={"path": str(self.context_dir)},
            )
        return existed

    def load(self) -> ContextBundle:
        """Escaneia recursivamente `input_context/` e retorna o `ContextBundle` processado."""
        self._ensure_dir()

        bundle = ContextBundle()
        files = sorted(p for p in self.context_dir.rglob("*") if p.is_file() and p.name != "README.md")

        for path in files:
            ext = path.suffix.lower()
            size_bytes = path.stat().st_size
            try:
                if ext in _TEXT_EXTENSIONS:
                    bundle.text_documents.append(self._process_text(path))
                elif ext in _DOCUMENT_EXTENSIONS:
                    bundle.text_documents.append(self._process_document(path))
                elif ext in _TABULAR_EXTENSIONS:
                    bundle.structured_data.append(self._process_tabular(path))
                elif ext in _EXCEL_EXTENSIONS:
                    bundle.structured_data.extend(self._process_excel(path))
                elif ext in _JSON_EXTENSIONS:
                    bundle.structured_data.extend(self._process_json(path))
                elif ext in _IMAGE_EXTENSIONS:
                    bundle.images.append(self._process_image(path))
                else:
                    bundle.raw_files.append(path)
                    logger.info(
                        "Arquivo não processado (formato sem processador dedicado)",
                        extra={"path": str(path), "size_bytes": size_bytes},
                    )
                    continue
                logger.info(
                    "Arquivo de contexto processado",
                    extra={"path": str(path), "size_bytes": size_bytes, "extension": ext},
                )
            except Exception as e:
                logger.error(
                    "Falha ao processar arquivo de contexto — adicionado como raw_file",
                    extra={"path": str(path), "error": str(e)},
                )
                bundle.raw_files.append(path)

        bundle.total_tokens_estimated = (
            sum(d.estimated_tokens() for d in bundle.text_documents)
            + sum(d.estimated_tokens() for d in bundle.structured_data)
            + sum(d.estimated_tokens() for d in bundle.images)
        )

        logger.info(
            "ContextLoader.load concluído",
            extra={
                "total_files": bundle.total_files,
                "total_tokens_estimated": bundle.total_tokens_estimated,
            },
        )
        return bundle

    # --- Processadores por formato ---

    def _process_text(self, path: Path) -> ProcessedDocument:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")

        chunks = _chunk_text(text) if len(text) > _CHUNK_SIZE_CHARS else None
        fmt = path.suffix.lower().lstrip(".")
        return ProcessedDocument(source_path=path, format=fmt, title=path.name, text_content=text, chunks=chunks)

    def _process_document(self, path: Path) -> ProcessedDocument:
        """PDF/DOCX/PPTX via ExtractorRegistry (V7), com fallback de OCR para PDFs escaneados."""
        from src.skills.document_processor.extractors.registry import ExtractorRegistry

        extracted = ExtractorRegistry().extract(str(path))
        text_content = extracted.text_content
        errors = list(extracted.extraction_errors)

        if path.suffix.lower() == ".pdf" and len(text_content.strip()) < _PDF_NATIVE_TEXT_MIN_CHARS:
            ocr_text, ocr_errors = self._ocr_scanned_pdf(path)
            if ocr_text:
                text_content = ocr_text
            errors.extend(ocr_errors)

        chunks = _chunk_text(text_content) if len(text_content) > _CHUNK_SIZE_CHARS else None
        return ProcessedDocument(
            source_path=path,
            format=extracted.format,
            title=extracted.title,
            text_content=text_content,
            chunks=chunks,
            num_pages=extracted.num_pages,
            extraction_errors=errors,
        )

    def _ocr_scanned_pdf(self, path: Path) -> tuple[str, list[str]]:
        """Renderiza páginas de um PDF escaneado e aplica OCR local via pytesseract."""
        try:
            import io

            import pymupdf as fitz
            import pytesseract
            from PIL import Image
        except ImportError as e:
            return "", [f"OCR indisponível para PDF escaneado: dependência ausente ({e})"]

        try:
            text_parts: list[str] = []
            with fitz.open(str(path)) as doc:
                for page in doc:
                    pix = page.get_pixmap()
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    text_parts.append(pytesseract.image_to_string(img))
            return "\n\n".join(text_parts).strip(), []
        except Exception as e:
            return "", [f"Falha no OCR de PDF escaneado: {e}"]

    def _process_tabular(self, path: Path) -> DatasetSummary:
        import pandas as pd

        try:
            df = pd.read_csv(path, sep=None, engine="python")
            return self._dataframe_to_summary(df, path, path.suffix.lower().lstrip("."))
        except Exception as e:
            return DatasetSummary(
                source_path=path,
                format=path.suffix.lower().lstrip("."),
                extraction_errors=[str(e)],
            )

    def _process_excel(self, path: Path) -> list[DatasetSummary]:
        import pandas as pd

        fmt = path.suffix.lower().lstrip(".")
        try:
            sheets = pd.read_excel(path, sheet_name=None)
        except Exception as e:
            return [DatasetSummary(source_path=path, format=fmt, extraction_errors=[str(e)])]

        return [
            self._dataframe_to_summary(df, path, fmt, sheet_name=name)
            for name, df in sheets.items()
        ]

    def _process_json(self, path: Path) -> list[DatasetSummary]:
        import pandas as pd

        fmt = path.suffix.lower().lstrip(".")
        try:
            if fmt == "jsonl":
                records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
                records = data if isinstance(data, list) else [data]

            if records and isinstance(records[0], dict):
                df = pd.DataFrame(records)
                return [self._dataframe_to_summary(df, path, fmt)]

            # Não-tabular: schema simples com as chaves de nível superior.
            schema = {"type": type(records[0]).__name__ if records else "empty"}
            return [
                DatasetSummary(
                    source_path=path,
                    format=fmt,
                    num_rows=len(records),
                    columns=list(schema.keys()),
                    dtypes=schema,
                    sample_rows=records[:5] if isinstance(records[0], dict) else [],
                )
            ]
        except Exception as e:
            return [DatasetSummary(source_path=path, format=fmt, extraction_errors=[str(e)])]

    def _dataframe_to_summary(self, df, path: Path, fmt: str, sheet_name: str | None = None) -> DatasetSummary:
        import pandas as pd

        stats: dict[str, dict[str, Any]] = {}
        numeric_desc = df.describe(include="all").to_dict()
        nulls = df.isnull().sum().to_dict()
        for col in df.columns:
            col_stats: dict[str, Any] = {"nulls": int(nulls.get(col, 0))}
            desc = numeric_desc.get(col, {})
            for key in ("min", "max", "mean"):
                value = desc.get(key)
                if value is not None and not (isinstance(value, float) and pd.isna(value)):
                    col_stats[key] = value
            stats[str(col)] = col_stats

        sample = json.loads(df.head(5).to_json(orient="records"))

        return DatasetSummary(
            source_path=path,
            format=fmt,
            sheet_name=sheet_name,
            num_rows=len(df),
            num_columns=len(df.columns),
            columns=[str(c) for c in df.columns],
            dtypes={str(c): str(t) for c, t in df.dtypes.items()},
            sample_rows=sample,
            stats=stats,
        )

    def _process_image(self, path: Path) -> ImageContext:
        import os

        from src.config import OCR_PROVIDER

        # Lê a variável de ambiente diretamente (não o valor cacheado em src.config no
        # import inicial), permitindo sobrescrita em runtime/testes via monkeypatch.
        provider = os.environ.get("OCR_PROVIDER", OCR_PROVIDER)

        if provider == "gemini":
            return self._describe_image_via_gemini(path)
        return self._ocr_image_local(path)

    def _ocr_image_local(self, path: Path) -> ImageContext:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as e:
            return ImageContext(
                source_path=path,
                description="",
                provider="local",
                extraction_errors=[f"OCR local indisponível: dependência ausente ({e})"],
            )

        try:
            text = pytesseract.image_to_string(Image.open(path))
            return ImageContext(source_path=path, description=text.strip(), provider="local")
        except Exception as e:
            return ImageContext(source_path=path, description="", provider="local", extraction_errors=[str(e)])

    def _describe_image_via_gemini(self, path: Path) -> ImageContext:
        try:
            from google import genai

            from src.config import GEMINI_API_KEY
            from src.egress.gate import Destination, EgressRefused, get_gate

            # v18.5-egress-gate (ADR 019 §3.5): visão é saída externa; imagem de pesquisa só vai a destino com dados
            # brutos ou se o arquivo for compartilhável (a marcação vem da ingestão, v18.5-research-data-ingestion).
            destination = Destination(
                canal="visao", provedor="google", modelo=_GEMINI_VISION_MODEL, trust="third_party",
                localidade="fora_do_no", aceita_dados_brutos=False, papel="ingestao",
            )
            try:
                get_gate().authorize_vision(path, False, destination)
            except EgressRefused as e:
                return ImageContext(source_path=path, description="", provider="gemini", extraction_errors=[str(e)])

            client = genai.Client(api_key=GEMINI_API_KEY)
            image_bytes = path.read_bytes()
            response = client.models.generate_content(
                model=_GEMINI_VISION_MODEL,
                contents=[
                    "Descreva o conteúdo desta imagem em detalhes (gráficos, tabelas, texto visível, "
                    "estruturas de microscopia, etc.) para uso como contexto científico.",
                    genai.types.Part.from_bytes(data=image_bytes, mime_type=_mime_type_for(path)),
                ],
            )
            description = (response.text or "").strip()
            return ImageContext(source_path=path, description=description, provider="gemini")
        except ImportError as e:
            return ImageContext(
                source_path=path,
                description="",
                provider="gemini",
                extraction_errors=[f"Gemini Vision indisponível: dependência ausente ({e})"],
            )
        except Exception as e:
            return ImageContext(source_path=path, description="", provider="gemini", extraction_errors=[str(e)])


_GEMINI_VISION_MODEL = "gemini-3.8-flash"


def _mime_type_for(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".bmp": "image/bmp",
    }.get(path.suffix.lower(), "application/octet-stream")
