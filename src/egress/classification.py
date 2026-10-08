"""Classificação de arquivos do host por origem de conteúdo (v18.5-egress-gate, design §6).

Regra padrão desta mudança: arquivos com extensões tabulares, de planilha, JSON/JSONL e imagem em ``input_context/``,
``input_snapshot/`` e nos diretórios de saída das execuções são ``dado_de_pesquisa``; os demais são ``documento``.
A ``v18.5-research-data-ingestion`` estende a classificação com as marcações do manifesto (``compartilhavel``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from src.egress.fragments import ContentOrigin

DATA_EXTENSIONS: frozenset[str] = frozenset(
    {
        # tabulares e planilhas
        ".csv", ".tsv", ".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".parquet", ".feather", ".dat",
        # estruturados
        ".json", ".jsonl", ".ndjson",
        # imagem
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp",
    }
)
DATA_DIRECTORY_NAMES: frozenset[str] = frozenset({"input_context", "input_snapshot"})


class ResearchDataRefused(PermissionError):
    """Ferramenta do host recusada: dados de pesquisa entram só pela ingestão de ``input_context/``."""


def _output_roots() -> list[Path]:
    from src import config

    return [Path(config.OUTPUT_BASE_DIR).resolve()]


def _in_data_directory(path: Path) -> bool:
    return any(part in DATA_DIRECTORY_NAMES for part in path.parts)


def _under_output_roots(path: Path, output_roots: Iterable[Path]) -> bool:
    return any(path == root or root in path.parents for root in output_roots)


def classify_path(
    path: Path | str,
    *,
    output_roots: Iterable[Path] | None = None,
    documents: Iterable[Path | str] = (),
) -> ContentOrigin:
    """Origem do conteúdo de ``path``.

    Padrão **negar**: tudo em ``input_context/`` e ``input_snapshot/`` é ``dado_de_pesquisa``, qualquer que seja a
    extensão, exceto os arquivos listados em ``documents`` (documentos explicitamente marcados, ex.: pelo manifesto da
    ingestão). Nos diretórios de saída das execuções vale a regra de extensões de dados. Symlinks são resolvidos: o
    caminho léxico e o destino são ambos avaliados, e basta um deles cair em diretório de dados.

    Args:
        path: Caminho do arquivo (existente ou não).
        output_roots: Raízes dos diretórios de saída das execuções (padrão: ``OUTPUT_BASE_DIR``).
        documents: Arquivos marcados explicitamente como documento.
    """
    candidate = Path(path)
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate
    marked = set()
    for doc in documents:
        try:
            marked.add(Path(doc).resolve())
        except OSError:
            continue
    if resolved in marked:
        return ContentOrigin.DOCUMENTO
    variants = {candidate, resolved}
    if any(_in_data_directory(v) for v in variants):
        return ContentOrigin.DADO_DE_PESQUISA
    roots = [r.resolve() for r in output_roots] if output_roots is not None else _output_roots()
    is_data_ext = any(v.suffix.lower() in DATA_EXTENSIONS for v in variants)
    if is_data_ext and any(_under_output_roots(v, roots) for v in variants):
        return ContentOrigin.DADO_DE_PESQUISA
    return ContentOrigin.DOCUMENTO


# Agregados escritos pelos helpers científicos: saída de execução (filtrada), não dado de pesquisa.
AGGREGATE_OUTPUT_NAMES: frozenset[str] = frozenset({"metrics.json", "params.json"})


def artifact_origin(path: Path | str) -> ContentOrigin:
    """Origem do conteúdo de um artefato produzido por execução: dado de pesquisa (tabular, JSON, imagem) ou saída.

    ``metrics.json`` e ``params.json`` são agregados (saída de execução); demais arquivos de dados dos diretórios de
    saída são ``dado_de_pesquisa``; texto e logs são ``saida_execucao``.
    """
    candidate = Path(path)
    if candidate.name in AGGREGATE_OUTPUT_NAMES:
        return ContentOrigin.SAIDA_EXECUCAO
    if candidate.suffix.lower() in DATA_EXTENSIONS:
        return ContentOrigin.DADO_DE_PESQUISA
    return ContentOrigin.SAIDA_EXECUCAO


def ensure_not_research_data(
    path: Path | str, *, compartilhavel: bool = False, documents: Iterable[Path | str] = ()
) -> None:
    """Recusa o arquivo se ele é ``dado_de_pesquisa`` não compartilhável (design §6).

    Raises:
        ResearchDataRefused: Com a mensagem de que dados de pesquisa entram só pela ingestão de ``input_context/``.
    """
    if compartilhavel:
        return
    if classify_path(path, documents=documents) is ContentOrigin.DADO_DE_PESQUISA:
        raise ResearchDataRefused(
            "dados de pesquisa entram só pela ingestão de input_context/; o código no sandbox pode lê-los"
        )
