import os
from typing import List

from src.skills.document_processor.extractors.base import BaseExtractor, ExtractedDocument


class TextExtractor(BaseExtractor):
    """Extrator leve para arquivos de texto simples (.txt, .md)."""

    @property
    def supported_extensions(self) -> List[str]:
        return [".txt", ".md"]

    def extract(self, file_path: str) -> ExtractedDocument:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            filename = os.path.basename(file_path)
            format_str = "md" if file_path.lower().endswith(".md") else "txt"
            
            return ExtractedDocument(
                source_path=file_path,
                format=format_str,
                title=filename,
                text_content=content,
                metadata={"extractor": "TextExtractor"},
            )
        except Exception as e:
            filename = os.path.basename(file_path)
            return ExtractedDocument(
                source_path=file_path,
                format="txt",
                title=filename,
                text_content="",
                extraction_errors=[str(e)],
            )
