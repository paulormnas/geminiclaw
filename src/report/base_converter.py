"""Interface base e factory dos conversores de formato do relatório científico
(Roadmap V15.4 / Spec G8).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ReportConverter(ABC):
    """Interface para conversores de ``relatorio_final.md`` para outros formatos."""

    @abstractmethod
    def convert(self, markdown_path: Path, output_path: Path) -> None:
        """Converte o Markdown de entrada e salva o resultado em ``output_path``.

        Args:
            markdown_path: Caminho do ``relatorio_final.md`` de origem.
            output_path: Caminho onde salvar o arquivo convertido.
        """
        raise NotImplementedError


class ReportConverterFactory:
    """Fábrica de conversores por formato (``latex`` | ``html`` | ``docx``)."""

    @staticmethod
    def create(format: str) -> ReportConverter:
        """Cria o conversor apropriado para o formato solicitado.

        Args:
            format: Um de ``"latex"``, ``"html"`` ou ``"docx"``.

        Returns:
            Instância do conversor correspondente.

        Raises:
            ValueError: Se o formato não for suportado.
        """
        normalized = format.lower().strip()
        if normalized == "latex":
            from src.report.latex_converter import LaTeXConverter
            return LaTeXConverter()
        if normalized == "html":
            from src.report.html_converter import HTMLConverter
            return HTMLConverter()
        if normalized == "docx":
            from src.report.docx_converter import DOCXConverter
            return DOCXConverter()
        raise ValueError(
            f"Formato não suportado: '{format}'. Formatos disponíveis: latex, html, docx."
        )
