import uuid
from dataclasses import dataclass, field
from typing import List

from src.skills.document_processor.extractors.base import ExtractedDocument

# Namespace fixo dos IDs determinísticos de documento e trecho (v17-input-document-index, design §4).
NAMESPACE_DOCUMENTOS = uuid.UUID("5f0c1c7e-6d52-4d0e-9c53-3b1f7f4d2a10")


def document_id_for(projeto_id: str, hash_conteudo: str) -> str:
    """ID determinístico do documento: o mesmo arquivo no mesmo projeto tem sempre o mesmo ID."""
    return str(uuid.uuid5(NAMESPACE_DOCUMENTOS, f"{projeto_id}:{hash_conteudo}"))


def chunk_id_for(document_id: str, indice: int) -> str:
    """ID determinístico do trecho; torna a reindexação idempotente (``upsert`` sobre os mesmos IDs)."""
    return str(uuid.uuid5(NAMESPACE_DOCUMENTOS, f"{document_id}:{indice}"))


@dataclass
class DocumentChunk:
    """Um chunk de documento pronto para indexação.

    ``content`` é só o texto do trecho (é o que se guarda e a busca devolve); o texto enviado ao
    modelo de embedding é ``embed_text`` (cabeçalho enriquecido + trecho), quando informado.
    """
    chunk_id: str              # UUID determinístico
    document_id: str           # ID do documento pai
    content: str               # Texto do trecho, sem cabeçalho
    chunk_index: int           # Posição no documento
    total_chunks: int          # Total de chunks do documento
    metadata: dict             # source_path, format, page, section, etc.
    token_count: int           # Estimativa de tokens
    embed_text: str = ""       # Texto vetorizado (cabeçalho + trecho); vazio = ``content``
    payload_extra: dict = field(default_factory=dict)  # Campos extras do ponto no Qdrant


class DocumentChunker:
    """Divide documentos em chunks para indexação vetorial.
    
    Estratégias:
    - paragraph: Divide por parágrafos duplos.
    - fixed: Tamanho fixo com overlap.
    """

    def __init__(
        self,
        max_chunk_size: int = 1500,    # Aproximadamente tokens / caracteres
        overlap: int = 150,            # Overlap de contexto
        strategy: str = "auto",        # auto | paragraph | fixed
    ):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.strategy = strategy

    def chunk(self, doc: ExtractedDocument, document_id: str) -> List[DocumentChunk]:
        """Divide o documento em chunks e retorna uma lista de DocumentChunk."""
        
        # Estratégia auto escolhe entre fixo ou parágrafo dependendo do tamanho/formato
        text = doc.text_content
        
        if not text.strip():
            return []

        if self.strategy == "paragraph" or (self.strategy == "auto" and "\n\n" in text):
            raw_chunks = self._chunk_by_paragraphs(text)
        else:
            raw_chunks = self._chunk_fixed(text)

        chunks: List[DocumentChunk] = []
        total_chunks = len(raw_chunks)
        
        for i, text_chunk in enumerate(raw_chunks):
            chunk_id = chunk_id_for(document_id, i)
            content = text_chunk

            # Estimativa básica: 1 token ~ 4 chars
            token_count = len(content) // 4
            
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                content=content,
                chunk_index=i,
                total_chunks=total_chunks,
                metadata={"source_path": doc.source_path, "format": doc.format},
                token_count=token_count,
            ))

        return chunks

    def _chunk_fixed(self, text: str) -> List[str]:
        """Estratégia de divisão por tamanho fixo com sobreposição."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.max_chunk_size
            chunks.append(text[start:end])
            start += self.max_chunk_size - self.overlap
        return chunks

    def _chunk_by_paragraphs(self, text: str) -> List[str]:
        """Estratégia de divisão por blocos de parágrafos."""
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for p in paragraphs:
            if not p.strip():
                continue
            if len(current_chunk) + len(p) < self.max_chunk_size:
                current_chunk += p + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = p + "\n\n"
                
        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks
