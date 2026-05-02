from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class ExtractedDocument:
    """Documento extraído e normalizado, pronto para indexação."""
    source_path: str                  # Caminho do arquivo original
    format: str                       # pdf | csv | xlsx | txt | md | docx | pptx
    title: str                        # Título extraído ou nome do arquivo
    text_content: str                 # Texto completo extraído
    metadata: dict = field(default_factory=dict)  # Metadados do formato
    tables: List[Dict] = field(default_factory=list)  # Tabelas extraídas (CSV/XLSX)
    num_pages: Optional[int] = None      # Número de páginas (PDF)
    language: str = "pt-BR"
    extraction_errors: List[str] = field(default_factory=list)


class BaseExtractor(ABC):
    """Interface para extratores de documentos."""

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Extensões suportadas (ex: ['.pdf', '.PDF'])."""
        pass

    @abstractmethod
    def extract(self, file_path: str) -> ExtractedDocument:
        """Extrai texto e metadados do arquivo."""
        pass

    def can_handle(self, file_path: str) -> bool:
        """Verifica se este extrator suporta o arquivo."""
        return any(file_path.lower().endswith(ext) for ext in self.supported_extensions)
