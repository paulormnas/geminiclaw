import os
from typing import List

from src.skills.document_processor.extractors.base import BaseExtractor, ExtractedDocument
from src.logger import get_logger

logger = get_logger(__name__)

class DoclingExtractor(BaseExtractor):
    """Extrator avançado usando IBM Docling para PDFs, DOCX, PPTX e XLSX."""

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf", ".docx", ".pptx", ".xlsx"]

    def extract(self, file_path: str) -> ExtractedDocument:
        filename = os.path.basename(file_path)
        format_str = file_path.lower().split('.')[-1]
        
        try:
            from docling.document_converter import DocumentConverter
            
            # Otimização para Pi 5: limitar features pesadas se necessário
            # A classe DocumentConverter possui configurações. Aqui instanciamos o padrão.
            converter = DocumentConverter()
            doc = converter.convert(file_path)
            
            # Exporta para Markdown para indexar o text_content
            text_content = doc.document.export_to_markdown()
            
            # Extrair tabelas, se houver
            tables = []
            for table in doc.document.tables:
                tables.append({"data": table.export_to_dataframe().to_dict(orient="records")})
                
            return ExtractedDocument(
                source_path=file_path,
                format=format_str,
                title=filename,
                text_content=text_content,
                metadata={"extractor": "DoclingExtractor"},
                tables=tables,
            )
        except ImportError:
            return ExtractedDocument(
                source_path=file_path,
                format=format_str,
                title=filename,
                text_content="",
                extraction_errors=["docling não está instalado."],
            )
        except Exception as e:
            logger.error(f"Erro no DoclingExtractor para {file_path}: {e}")
            return ExtractedDocument(
                source_path=file_path,
                format=format_str,
                title=filename,
                text_content="",
                extraction_errors=[str(e)],
            )
