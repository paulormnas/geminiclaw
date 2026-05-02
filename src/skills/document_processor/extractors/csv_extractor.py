import os
import csv
from typing import List

from src.skills.document_processor.extractors.base import BaseExtractor, ExtractedDocument


class CsvExtractor(BaseExtractor):
    """Extrator leve para arquivos CSV usando stdlib."""

    @property
    def supported_extensions(self) -> List[str]:
        return [".csv"]

    def extract(self, file_path: str) -> ExtractedDocument:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = [row for row in reader]

            filename = os.path.basename(file_path)
            
            # Converter a tabela para um dicionário para a lista de tables e string formatada para text_content
            text_lines = []
            for row in rows:
                text_lines.append(",".join(row))
            text_content = "\n".join(text_lines)

            tables = []
            if rows:
                header = rows[0]
                data = rows[1:]
                tables.append({"header": header, "data": data})

            return ExtractedDocument(
                source_path=file_path,
                format="csv",
                title=filename,
                text_content=text_content,
                metadata={"extractor": "CsvExtractor", "rows": len(rows)},
                tables=tables,
            )
        except Exception as e:
            filename = os.path.basename(file_path)
            return ExtractedDocument(
                source_path=file_path,
                format="csv",
                title=filename,
                text_content="",
                extraction_errors=[str(e)],
            )
