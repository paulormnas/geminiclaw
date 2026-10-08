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
from typing import TYPE_CHECKING, Any

from src.egress.fragments import ContentOrigin, PromptFragment, mark_fragment
from src.logger import get_logger
from src.research_data.manifest import (
    MANIFEST_NAME,
    FileMarking,
    ResearchDataManifest,
    default_origin,
    file_sha256,
    load_manifest,
)
from src.research_data.summary import (
    FormatInfo,
    SafeDatasetSummary,
    build_safe_summary,
    detect_text_format,
)

if TYPE_CHECKING:
    from src.llm.vision import VisionTarget

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
    size_bytes: int = 0

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
    size_bytes: int = 0
    # v18.5-research-data-ingestion: resumo seguro (sem valores) que vai a qualquer destino permitido.
    safe: SafeDatasetSummary | None = None
    safe_text: str = ""

    def estimated_tokens(self) -> int:
        return len(json.dumps(self.sample_rows, default=str)) // _CHARS_PER_TOKEN_ESTIMATE


@dataclass
class ImageContext:
    """Descrição textual de uma imagem (OCR local ou Gemini Vision)."""

    source_path: Path
    description: str
    provider: str = "local"
    extraction_errors: list[str] = field(default_factory=list)
    size_bytes: int = 0
    dimensions: tuple[int, int] | None = None
    # Descrição produzida por modelo que aceita dados brutos: texto contaminado (ADR 019 §3.5).
    tainted: bool = False

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
    # v18.5-research-data-ingestion: classificação efetiva de cada arquivo (manifesto ou regra padrão).
    markings: dict[Path, FileMarking] = field(default_factory=dict)
    manifest: ResearchDataManifest | None = None
    manifest_warnings: list[str] = field(default_factory=list)
    min_group_size: int | None = None

    @property
    def total_files(self) -> int:
        return len(self.text_documents) + len(self.structured_data) + len(self.images) + len(self.raw_files)

    # --- marcações ------------------------------------------------------------------------------------------------

    def marking_for(self, path: Path) -> FileMarking:
        """Classificação efetiva de ``path``; sem registro, a regra padrão (negar: dado de pesquisa por extensão)."""
        marking = self.markings.get(path)
        if marking is not None:
            return marking
        return FileMarking(path.name, default_origin(path), None, None, "padrao")

    def research_data_markings(self) -> list[dict[str, Any]]:
        """Registros para ``payload["research_data_markings"]`` (um por arquivo, em ordem de caminho)."""
        return [m.to_payload() for _, m in sorted(self.markings.items(), key=lambda item: item[1].caminho)]

    def marking_counts(self) -> dict[str, int]:
        """Contagens para o banner: dados de pesquisa, compartilháveis e documentos."""
        research = shareable = documents = 0
        for marking in self.markings.values():
            if marking.compartilhavel:
                shareable += 1
            if marking.classe is ContentOrigin.DADO_DE_PESQUISA:
                research += 1
            else:
                documents += 1
        return {"pesquisa": research, "compartilhaveis": shareable, "documentos": documents}

    def shareable_markings(self) -> list[FileMarking]:
        return sorted((m for m in self.markings.values() if m.compartilhavel), key=lambda m: m.caminho)

    # --- trechos rotulados ----------------------------------------------------------------------------------------

    def to_fragments(self) -> list[PromptFragment]:
        """Trechos rotulados do bundle (design §3): ``esquema_agregado`` para qualquer destino e ``dado_de_pesquisa``
        (amostras, estatísticas exatas, texto de documentos marcados e de OCR) só para quem aceita dados brutos ou
        quando o arquivo é compartilhável (decisão do ``EgressGate``)."""
        if self.total_files == 0:
            return []
        out: list[PromptFragment] = [
            PromptFragment("[CONTEXTO CIENTÍFICO PRÉ-CURADO — input_context/]", ContentOrigin.INSTRUCAO)
        ]
        for doc in self.text_documents:
            out.extend(self._document_fragments(doc))
        for ds in self.structured_data:
            out.extend(self._dataset_fragments(ds))
        for img in self.images:
            out.extend(self._image_fragments(img))
        for path in self.raw_files:
            marking = self.marking_for(path)
            size = _size_of(path)
            out.append(
                PromptFragment(
                    f"### Arquivo não processado (disponível por caminho): {path.name} ({size} bytes)",
                    ContentOrigin.ESQUEMA_AGREGADO,
                    source=_source(marking),
                )
            )
        return out

    def _document_fragments(self, doc: ProcessedDocument) -> list[PromptFragment]:
        marking = self.marking_for(doc.source_path)
        source = _source(marking)
        if doc.extraction_errors:
            body = f"[erro de extração: {'; '.join(doc.extraction_errors)}]"
        elif doc.chunks:
            body = doc.chunks[0] + f"\n[... documento truncado em {len(doc.chunks)} blocos ...]"
        else:
            body = doc.text_content
        header = f"### Documento: {doc.title} ({doc.format})"
        if marking.classe is ContentOrigin.DOCUMENTO:
            return [PromptFragment(f"{header}\n{body}", ContentOrigin.DOCUMENTO, source=source)]
        pages = f", {doc.num_pages} páginas" if doc.num_pages else ""
        schema = (
            f"{header}\nFormato: {doc.format}{pages}, {doc.size_bytes} bytes (conteúdo marcado como dado de pesquisa)"
        )
        return [
            PromptFragment(schema, ContentOrigin.ESQUEMA_AGREGADO, source=source),
            PromptFragment(body, ContentOrigin.DADO_DE_PESQUISA, source=source),
        ]

    def _dataset_fragments(self, ds: DatasetSummary) -> list[PromptFragment]:
        marking = self.marking_for(ds.source_path)
        source = _source(marking)
        label = f"{ds.source_path.name}" + (f" [{ds.sheet_name}]" if ds.sheet_name else "")
        if ds.extraction_errors:
            text = f"### Dataset: {label} ({ds.format})\n[erro de extração: {'; '.join(ds.extraction_errors)}]"
            return [PromptFragment(text, ContentOrigin.ESQUEMA_AGREGADO, source=source)]
        schema_text = ds.safe_text or (
            f"Dataset: {label} ({ds.format}, {ds.size_bytes} bytes)\n"
            f"Linhas: {ds.num_rows} | Colunas: {ds.num_columns}"
        )
        fragments = [PromptFragment(f"### {schema_text}", ContentOrigin.ESQUEMA_AGREGADO, source=source)]
        exact: list[str] = []
        if ds.sample_rows:
            exact.append(f"Amostra ({len(ds.sample_rows)} primeiras linhas): "
                         f"{json.dumps(ds.sample_rows, ensure_ascii=False, default=str)}")
        if ds.stats:
            exact.append(f"Estatísticas: {json.dumps(ds.stats, ensure_ascii=False, default=str)}")
        if exact:
            fragments.append(
                PromptFragment(
                    f"### Dados de {label}\n" + "\n".join(exact),
                    ContentOrigin.DADO_DE_PESQUISA,
                    compartilhavel=marking.compartilhavel,
                    source=source,
                )
            )
        return fragments

    def _image_fragments(self, img: ImageContext) -> list[PromptFragment]:
        marking = self.marking_for(img.source_path)
        source = _source(marking)
        dims = f", {img.dimensions[0]}x{img.dimensions[1]} px" if img.dimensions else ""
        suffix = img.source_path.suffix.lower().lstrip(".")
        schema = f"### Imagem: {img.source_path.name} ({suffix}{dims}, {img.size_bytes} bytes)"
        notes = [f"[{error}]" for error in img.extraction_errors]
        fragments = [PromptFragment("\n".join([schema, *notes]), ContentOrigin.ESQUEMA_AGREGADO, source=source)]
        if img.description:
            text = f"### Descrição de {img.source_path.name} (via {img.provider})\n{img.description}"
            if marking.compartilhavel and img.provider != "local":
                fragments.append(PromptFragment(text, ContentOrigin.DOCUMENTO, tainted=img.tainted, source=source))
            else:
                fragments.append(
                    PromptFragment(
                        text,
                        ContentOrigin.DADO_DE_PESQUISA,
                        tainted=img.tainted,
                        compartilhavel=marking.compartilhavel,
                        source=source,
                    )
                )
        return fragments

    def to_marked_context(self) -> str:
        """Bloco de prompt com marcas em linha (origem, contaminação, ``compartilhavel``) para o ``EgressGate``."""
        parts: list[str] = []
        for frag in self.to_fragments():
            parts.append(frag.text if frag.origin is ContentOrigin.INSTRUCAO else mark_fragment(frag))
        return "\n".join(parts)

    def to_prompt_context(self) -> str:
        """Bloco de texto seguro: só os trechos que não são ``dado_de_pesquisa`` (sem amostras nem valores)."""
        return "\n".join(f.text for f in self.to_fragments() if f.origin is not ContentOrigin.DADO_DE_PESQUISA)

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


def _source(marking: FileMarking) -> str:
    return f"input_context/{marking.caminho}"


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


_INPUT_CONTEXT_README = """# input_context/

Deposite aqui os arquivos de contexto científico da sua sessão antes de executar
`geminiclaw`. O sistema carrega e processa automaticamente esta pasta antes de
iniciar a sessão — não é necessário nenhum flag no CLI.

Formatos suportados:
- `context.md`, `.txt`, `.rst` — objetivo, hipóteses, instruções (chunked se > 50.000 chars)
- `.pdf`, `.docx`, `.pptx` — artigos e documentos de referência
- `.csv`, `.tsv`, `.xlsx`, `.xls`, `.ods` — datasets (resumo seguro: esquema, formato e estatísticas agregadas)
- `.json`, `.jsonl` — dados estruturados ou schemas
- `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp` — imagens (OCR local ou modelo de visão, `VISION_MODEL`)

Marcação de dados (opcional) — `dados.yaml` nesta pasta:

```yaml
versao: 1
arquivos:
  - caminho: publicos/uci_air_quality.csv   # relativo a input_context/; aceita glob
    marcacao: compartilhavel                # dataset público; exige `motivo`
    motivo: "Dataset público, DOI 10.24432/C59K5F"
  - caminho: cadernos/*.pdf
    marcacao: dado_de_pesquisa              # documento que contém medições
```

Sem marcação vale a regra padrão: datasets, planilhas, JSON e imagens são `dado_de_pesquisa`; textos e documentos
(`.txt .md .rst .pdf .docx .pptx`) são `documento`. Dados de pesquisa só vão a modelos que aceitam dados brutos (ou se
o arquivo for `compartilhavel`); os demais modelos recebem esquema, descritores de formato e estatísticas agregadas.
`dados.yaml` não é processado como contexto.

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

    def __init__(self, context_dir: str | Path | None = None, *, min_group_size: int | None = None):
        from src.config import INPUT_CONTEXT_DIR

        self.context_dir = Path(context_dir) if context_dir is not None else Path(INPUT_CONTEXT_DIR)
        # k (LOCALITY_MIN_GROUP_SIZE) das estatísticas do resumo seguro; sem valor, toda coluna fica "abaixo de k".
        self._min_group_size = min_group_size
        self._vision_target: "VisionTarget | None" = None

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

        bundle = ContextBundle(min_group_size=self._effective_k())
        files = sorted(
            p
            for p in self.context_dir.rglob("*")
            if p.is_file() and p.name != "README.md" and not self._is_manifest(p)
        )

        # Manifesto e marcações antes de processar qualquer arquivo: manifesto inválido ou conflito impede a sessão.
        manifest = load_manifest(self.context_dir)
        bundle.manifest = manifest
        for path in files:
            marking = manifest.marking_for(path)
            bundle.markings[path] = FileMarking(
                marking.caminho, marking.classe, marking.marcacao, marking.motivo, marking.origem, file_sha256(path)
            )
        bundle.manifest_warnings = manifest.warn_unmatched(files)
        self._vision_target = self._resolve_vision_target()

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
                    bundle.images.append(self._process_image(path, bundle.marking_for(path)))
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

    # --- Manifesto, k e visão ---

    def _is_manifest(self, path: Path) -> bool:
        return path.name == MANIFEST_NAME and path.parent == self.context_dir

    def _effective_k(self) -> int | None:
        if self._min_group_size is not None:
            return self._min_group_size
        from src import config

        return config.LOCALITY_MIN_GROUP_SIZE

    @staticmethod
    def _resolve_vision_target() -> "VisionTarget | None":
        """Modelo de visão da sessão (``VISION_MODEL``), ou ``None``.

        Raises:
            VisionConfigError: ``VISION_MODEL`` fora do catálogo ou de provedor sem suporte a visão.
        """
        from src.llm import vision

        model_id = vision.configured_model_id()
        return vision.resolve_target(model_id) if model_id else None

    # --- Processadores por formato ---

    def _process_text(self, path: Path) -> ProcessedDocument:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")

        chunks = _chunk_text(text) if len(text) > _CHUNK_SIZE_CHARS else None
        fmt = path.suffix.lower().lstrip(".")
        return ProcessedDocument(
            source_path=path, format=fmt, title=path.name, text_content=text, chunks=chunks, size_bytes=_size_of(path)
        )

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
            size_bytes=_size_of(path),
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

        fmt = path.suffix.lower().lstrip(".")
        try:
            info = detect_text_format(path, fmt)
            try:
                df = pd.read_csv(
                    path,
                    sep=info.separador,
                    decimal=info.decimal,
                    encoding=info.codificacao,
                    header=0 if info.cabecalho else None,
                )
            except Exception:  # noqa: BLE001 — detecção falhou: leitura com a heurística do pandas, como antes
                df = pd.read_csv(path, sep=None, engine="python", encoding=info.codificacao)
            return self._dataframe_to_summary(df, path, fmt, format_info=info)
        except Exception as e:
            return DatasetSummary(
                source_path=path,
                format=path.suffix.lower().lstrip("."),
                extraction_errors=[str(e)],
                size_bytes=_size_of(path),
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
            size = _size_of(path)
            safe_text = (
                f"Dataset: {path.name} ({fmt}, {size} bytes)\n"
                f"Tipo de nível superior: {schema['type']}\nRegistros: {len(records)}"
            )
            return [
                DatasetSummary(
                    source_path=path,
                    format=fmt,
                    num_rows=len(records),
                    columns=list(schema.keys()),
                    dtypes=schema,
                    sample_rows=records[:5],
                    size_bytes=size,
                    safe_text=safe_text,
                )
            ]
        except Exception as e:
            return [DatasetSummary(source_path=path, format=fmt, extraction_errors=[str(e)])]

    def _dataframe_to_summary(
        self, df, path: Path, fmt: str, sheet_name: str | None = None, format_info: FormatInfo | None = None
    ) -> DatasetSummary:
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
        size = _size_of(path)
        safe = build_safe_summary(
            df,
            name=path.name,
            fmt=fmt,
            size_bytes=size,
            k=self._effective_k(),
            sheet=sheet_name,
            format_info=format_info,
        )

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
            size_bytes=size,
            safe=safe,
            safe_text=safe.render(),
        )

    def _process_image(self, path: Path, marking: FileMarking | None = None) -> ImageContext:
        """Imagem: visão pelo modelo de ``VISION_MODEL`` (após a camada de saída) ou OCR local."""
        marking = marking or FileMarking(path.name, default_origin(path), None, None, "padrao")
        if self._vision_target is not None:
            image = self._describe_image_via_vision(path, marking, self._vision_target)
        else:
            image = self._ocr_image_local(path)
        image.size_bytes = _size_of(path)
        image.dimensions = _image_dimensions(path)
        return image

    def _describe_image_via_vision(self, path: Path, marking: FileMarking, target: "VisionTarget") -> ImageContext:
        """Descrição por modelo de visão.

        Recusa da camada de saída (imagem de pesquisa a destino sem dados brutos) ou falha do provedor NÃO interrompem a
        sessão: cai para o OCR local e registra o motivo em ``extraction_errors``.
        """
        from src.egress.gate import EgressRefused, get_gate
        from src.llm import vision

        provider = f"{target.destination.provedor}/{target.destination.modelo}"
        try:
            get_gate().authorize_vision(path, marking.compartilhavel, target.destination)
        except EgressRefused as e:
            return self._ocr_with_note(path, f"visão recusada pela camada de saída: {e}")
        try:
            description = vision.describe_image(path, target)
        except Exception as e:  # noqa: BLE001 — rede, cota, dependência ausente: segue com o OCR local
            logger.error("Falha na visão; usando OCR local", extra={"path": str(path), "error": str(e)})
            return self._ocr_with_note(path, f"visão indisponível ({provider}): {e}")
        return ImageContext(
            source_path=path,
            description=description,
            provider=provider,
            tainted=target.destination.aceita_dados_brutos,
        )

    def _ocr_with_note(self, path: Path, note: str) -> ImageContext:
        image = self._ocr_image_local(path)
        image.extraction_errors.insert(0, note)
        return image

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


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as handle:
            width, height = handle.size
        return (int(width), int(height)) if isinstance(width, int) and isinstance(height, int) else None
    except Exception:  # noqa: BLE001 — dimensões são opcionais (arquivo corrompido ou PIL ausente)
        return None
