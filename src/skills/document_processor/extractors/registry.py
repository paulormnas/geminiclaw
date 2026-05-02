import os
from typing import Optional

from src.skills.document_processor.extractors.base import BaseExtractor, ExtractedDocument
from src.skills.document_processor.extractors.text_extractor import TextExtractor
from src.skills.document_processor.extractors.csv_extractor import CsvExtractor
from src.skills.document_processor.extractors.docling_extractor import DoclingExtractor
from src.skills.document_processor.extractors.fallback_extractor import FallbackExtractor
from src.logger import get_logger

logger = get_logger(__name__)

class ExtractorRegistry:
    """Gerencia a seleção e execução dos extratores com suporte a fallback."""

    def __init__(self):
        # A ordem de registro importa: preferimos o Docling primeiro, e depois Fallback
        self.extractors: list[BaseExtractor] = [
            TextExtractor(),
            CsvExtractor(),
            DoclingExtractor(),
            FallbackExtractor(),
        ]

    def extract(self, file_path: str) -> ExtractedDocument:
        """Tenta extrair o documento usando os extratores disponíveis com fallback."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

        errors = []
        for extractor in self.extractors:
            if extractor.can_handle(file_path):
                logger.debug(f"Tentando extração de {file_path} usando {extractor.__class__.__name__}")
                doc = extractor.extract(file_path)
                
                # Se não houve erros de extração, retorna
                if not doc.extraction_errors:
                    return doc
                
                # Se houve erros (ex: biblioteca não instalada), guarda o erro e tenta o próximo
                errors.extend(doc.extraction_errors)
                logger.warning(
                    f"Falha ao extrair com {extractor.__class__.__name__}",
                    extra={"file_path": file_path, "errors": doc.extraction_errors}
                )

        # Se nenhum extrator funcionou (ou se nenhum era compatível)
        filename = os.path.basename(file_path)
        format_str = file_path.lower().split('.')[-1]
        
        error_msg = f"Nenhum extrator conseguiu processar o arquivo. Erros: {'; '.join(errors)}" if errors else "Formato não suportado."
        logger.error(error_msg, extra={"file_path": file_path})
        
        return ExtractedDocument(
            source_path=file_path,
            format=format_str,
            title=filename,
            text_content="",
            extraction_errors=[error_msg],
        )
