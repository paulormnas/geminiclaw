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


def _in_data_directory(path: Path, output_roots: Iterable[Path]) -> bool:
    if any(part in DATA_DIRECTORY_NAMES for part in path.parts):
        return True
    resolved = path.resolve()
    return any(resolved == root or root in resolved.parents for root in output_roots)


def classify_path(path: Path | str, *, output_roots: Iterable[Path] | None = None) -> ContentOrigin:
    """Origem do conteúdo de ``path``: ``dado_de_pesquisa`` para dados em diretórios de dados, senão ``documento``.

    Args:
        path: Caminho do arquivo (existente ou não; só o nome e a localização contam).
        output_roots: Raízes dos diretórios de saída das execuções (padrão: ``OUTPUT_BASE_DIR``).
    """
    candidate = Path(path)
    if candidate.suffix.lower() not in DATA_EXTENSIONS:
        return ContentOrigin.DOCUMENTO
    roots = list(output_roots) if output_roots is not None else _output_roots()
    return ContentOrigin.DADO_DE_PESQUISA if _in_data_directory(candidate, roots) else ContentOrigin.DOCUMENTO


def ensure_not_research_data(path: Path | str, *, compartilhavel: bool = False) -> None:
    """Recusa o arquivo se ele é ``dado_de_pesquisa`` não compartilhável (design §6).

    Raises:
        ResearchDataRefused: Com a mensagem de que dados de pesquisa entram só pela ingestão de ``input_context/``.
    """
    if compartilhavel:
        return
    if classify_path(path) is ContentOrigin.DADO_DE_PESQUISA:
        raise ResearchDataRefused(
            "dados de pesquisa entram só pela ingestão de input_context/; o código no sandbox pode lê-los"
        )
