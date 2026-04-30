# Roadmap V7 — Pré-processamento de Documentos e Base de Conhecimento

**Contexto:** Este roadmap implementa o pipeline de ingestão de documentos não estruturados fornecidos pelo usuário (CSV, PDF, TXT, XLSX, etc.), transformando-os em dados indexados nos bancos SQL e vetorial para enriquecer o contexto do sistema multi-agente durante pesquisas.

> **Pré-requisito:** Roadmaps V1–V4 concluídos. Deep Search skill (S2) funcional.
> **Relacionado:** Roadmap V6 (Autonomia de Pesquisa) — os documentos ingeridos alimentam as pesquisas autônomas dos agentes.

---

## Motivação

Atualmente, os agentes só têm acesso a informações via busca web (QuickSearch/DeepSearch) ou via contexto injetado no prompt. Não há mecanismo para o usuário fornecer seus próprios documentos (papers, datasets, relatórios) para que os agentes os consultem durante a pesquisa.

Um pipeline de pré-processamento resolve isso:

```
Usuário fornece arquivo (PDF, CSV, XLSX, TXT, MD)
    → Pipeline de extração (texto + metadados)
        → Chunking inteligente
            → Indexação no banco vetorial (Qdrant) para busca semântica
            → Registro de metadados no SQLite para busca estruturada
                → Agentes consultam automaticamente ao receber tarefas
```

---

## Etapa V7.1 — Extratores por Formato

**Objetivo:** Criar extratores especializados para cada formato de arquivo suportado.

### Análise de Bibliotecas: Docling vs Abordagem Modular

#### Docling (IBM)

O [Docling](https://github.com/DS4SD/docling) é uma biblioteca open-source da IBM para conversão de documentos, desenhada para preparar conteúdo para RAG e IA generativa.

**Formatos suportados:** PDF, DOCX, PPTX, XLSX, HTML, imagens (PNG, JPEG), Markdown.

**Vantagens:**
- Interface unificada `DoclingDocument` para todos os formatos
- Compreensão avançada de layout em PDFs (headers, tabelas, listas, fórmulas)
- OCR integrado (EasyOCR/Tesseract) para PDFs escaneados
- **Chunking nativo** com integração direta com LlamaIndex, LangChain e Haystack
- Suporte oficial a ARM64 (compatível com Pi 5)
- CLI disponível para ingestão via terminal

**Considerações para Pi 5:**
- Os modelos de layout analysis (TableFormer) podem consumir memória significativa
- Estratégias de mitigação recomendadas:
  - Usar `PyPdfiumDocumentBackend` (mais leve)
  - `generate_parsed_pages=False` para reduzir memória
  - Desabilitar features desnecessárias (`do_formula_enrichment=False`, `do_picture_classification=False`)
  - `batch_size=1` para limitar processamento simultâneo
  - Chamar `unload()` explicitamente após conversão

**Estimativa de memória:** ~200–300 MB para PDFs complexos (com modelos de layout), ~50 MB para formatos simples (XLSX, TXT).

#### Outras Bibliotecas Relevantes (2025/2026)

| Biblioteca | Foco | Formato Principal | Integração |
|---|---|---|---|
| **Unstructured** | Particionamento semântico de documentos | PDF, PPTX, HTML, imagens | LangChain, LlamaIndex |
| **LlamaIndex** | Indexação e retrieval para RAG | Multi-formato (via loaders) | Nativo |
| **pdfplumber** | Extração de texto e tabelas de PDFs | PDF | Independente |
| **openpyxl** | Leitura de planilhas Excel | XLSX | Independente |

#### Decisão Arquitetural: Docling como Extrator Principal + Fallbacks Leves

Dada a necessidade de suportar múltiplos formatos (PDF, CSV, XLSX, TXT, MD) com boa extração de estrutura, a abordagem recomendada é:

1. **Docling como backend principal** para PDF e XLSX — oferece a melhor extração de layout e tabelas
2. **Fallbacks leves (stdlib)** para TXT, MD e CSV — sem necessidade de modelos de IA
3. **Pipeline configurável** — o usuário pode desabilitar Docling se o Pi 5 estiver sob pressão de memória

```
src/skills/document_processor/
├── __init__.py
├── extractors/
│   ├── __init__.py
│   ├── base.py              # BaseExtractor + ExtractedDocument
│   ├── text_extractor.py    # .txt, .md — leitura direta (stdlib)
│   ├── csv_extractor.py     # .csv — stdlib csv module
│   ├── docling_extractor.py # .pdf, .xlsx, .docx, .pptx — via Docling
│   └── fallback_extractor.py # .pdf → pdfplumber, .xlsx → openpyxl (quando Docling indisponível)
├── chunker.py               # Divisão em chunks para indexação
├── indexer.py                # Indexação no Qdrant + SQLite
├── skill.py                  # DocumentProcessorSkill (ferramenta ADK)
└── registry.py               # Registro de extratores por extensão
```

### Interface Base

```python
# src/skills/document_processor/extractors/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class ExtractedDocument:
    """Documento extraído e normalizado, pronto para indexação."""
    source_path: str                  # Caminho do arquivo original
    format: str                       # pdf | csv | xlsx | txt | md
    title: str                        # Título extraído ou nome do arquivo
    text_content: str                 # Texto completo extraído
    metadata: dict = field(default_factory=dict)  # Metadados do formato
    tables: list[dict] = field(default_factory=list)  # Tabelas extraídas (CSV/XLSX)
    num_pages: int | None = None      # Número de páginas (PDF)
    language: str = "pt-BR"
    extraction_errors: list[str] = field(default_factory=list)

class BaseExtractor(ABC):
    """Interface para extratores de documentos."""

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Extensões suportadas (ex: ['.pdf', '.PDF'])."""
        ...

    @abstractmethod
    def extract(self, file_path: str) -> ExtractedDocument:
        """Extrai texto e metadados do arquivo."""
        ...

    def can_handle(self, file_path: str) -> bool:
        """Verifica se este extrator suporta o arquivo."""
        return any(file_path.lower().endswith(ext) for ext in self.supported_extensions)
```

### Escolha de Bibliotecas (considerando Pi 5)

| Formato | Backend Primário | Backend Fallback | RAM Estimada | Justificativa |
|---|---|---|---|---|
| TXT/MD | stdlib `open()` | — | ~0 MB | Sem dependência |
| CSV | stdlib `csv` | — | ~0 MB | Sem dependência; pandas é pesado para Pi 5 |
| XLSX | Docling | `openpyxl` | ~50 MB / ~20 MB | Docling extrai melhor a estrutura |
| PDF | Docling | `pdfplumber` | ~200 MB / ~50 MB | Docling tem OCR e layout analysis |
| DOCX/PPTX | Docling | — | ~100 MB | Suporte exclusivo via Docling |

> **Nota sobre Pi 5:** O Docling pode ser pesado para PDFs complexos. O `ExtractorRegistry` tentará Docling primeiro e cairá para o fallback leve se houver erro de memória ou se Docling não estiver instalado. A config `DOCLING_ENABLED=true|false` permite desabilitar globalmente.

### Tarefas V7.1

- [ ] Criar estrutura de diretórios `src/skills/document_processor/`
- [ ] Implementar `BaseExtractor` e `ExtractedDocument`
- [ ] Implementar `TextExtractor` (.txt, .md) usando stdlib
- [ ] Implementar `CsvExtractor` (.csv) usando stdlib `csv`
- [ ] Implementar `DoclingExtractor` (.pdf, .xlsx, .docx, .pptx) com opções otimizadas para Pi 5
- [ ] Implementar `FallbackExtractor` (.pdf → pdfplumber, .xlsx → openpyxl)
- [ ] Criar `ExtractorRegistry` com auto-detecção por extensão e fallback automático
- [ ] Adicionar `docling`, `openpyxl` e `pdfplumber` ao `pyproject.toml` (optional extras)
- [ ] Testes unitários para cada extrator com fixtures
- [ ] Commit: `feat(docs): implementa extratores de documentos com Docling e fallbacks`

---

## Etapa V7.2 — Chunking Inteligente

**Objetivo:** Dividir documentos extraídos em chunks otimizados para indexação vetorial, preservando coerência semântica.

### Estado da Arte em Chunking (2025/2026)

As melhores práticas atuais indicam que a **qualidade do chunking** tem maior impacto na precisão do RAG do que a escolha do modelo de embedding. As estratégias mais eficazes são:

| Estratégia | Descrição | Melhor Para |
|---|---|---|
| **Semantic Chunking** | Divide por significado semântico, não por tamanho fixo | Textos longos e complexos |
| **Structure-Aware** | Usa metadados do documento (headers, tabelas, listas) | Documentos com layout rico |
| **Recursive Character** | Divide por parágrafos → sentenças → palavras | Fallback para texto sem estrutura |
| **Contextual Retrieval** | Prepende resumo/título a cada chunk para dar contexto | Reduzir ambiguidade |
| **Late Chunking** | Embedding do documento inteiro primeiro, depois pooling | Preservar contexto global |

### Integração com Docling

O Docling possui **chunking nativo** que pode ser utilizado diretamente quando disponível. Ele produz chunks que respeitam a estrutura do documento detectada pelo layout analysis, sendo superior ao chunking por tamanho fixo.

Quando Docling não está disponível (ou para formatos simples como TXT/CSV), usamos chunking próprio com as estratégias acima.

### Implementação

```python
# src/skills/document_processor/chunker.py

class DocumentChunker:
    """Divide documentos em chunks para indexação vetorial.

    Estratégias (selecionadas automaticamente ou manualmente):
    1. Docling nativo: Usa o chunking do Docling (quando disponível)
    2. Por seção (Markdown headers): Respeita a estrutura do documento
    3. Por parágrafos: Para texto corrido sem headers
    4. Por tamanho fixo com overlap: Fallback para documentos sem estrutura
    5. Por linhas (CSV/tabelas): Cada N linhas = 1 chunk
    """

    def __init__(
        self,
        max_chunk_tokens: int = 512,    # Otimizado para embedding model
        overlap_tokens: int = 50,       # Overlap para contexto
        strategy: str = "auto",         # auto | docling | section | paragraph | fixed | tabular
        prepend_context: bool = True,   # Contextual Retrieval: prepende título/seção ao chunk
    ): ...

    def chunk(self, doc: ExtractedDocument) -> list[DocumentChunk]:
        """Divide o documento em chunks."""
        if self.strategy == "auto":
            return self._auto_chunk(doc)
        ...

    def _auto_chunk(self, doc: ExtractedDocument) -> list[DocumentChunk]:
        """Seleciona estratégia automaticamente com base no formato e disponibilidade."""
        # Se Docling está disponível e o documento foi extraído por ele, usar chunking nativo
        if doc.metadata.get("extractor") == "docling" and self._docling_available():
            return self._chunk_via_docling(doc)
        # Markdown com headers → dividir por seções
        if doc.format in ("md", "txt") and "# " in doc.text_content:
            return self._chunk_by_sections(doc)
        # Dados tabulares → dividir por linhas
        elif doc.format in ("csv", "xlsx"):
            return self._chunk_tabular(doc)
        # Fallback → dividir por parágrafos
        else:
            return self._chunk_by_paragraphs(doc)
```

```python
@dataclass
class DocumentChunk:
    """Um chunk de documento pronto para indexação."""
    chunk_id: str              # UUID
    document_id: str           # ID do documento pai
    content: str               # Texto do chunk
    chunk_index: int           # Posição no documento
    total_chunks: int          # Total de chunks do documento
    metadata: dict             # source_path, format, page, section, etc.
    token_count: int           # Estimativa de tokens
    context_prefix: str = ""   # Contextual Retrieval: "Documento: X | Seção: Y"
```

### Tarefas V7.2

- [ ] Implementar `DocumentChunker` com 5 estratégias (incluindo Docling nativo)
- [ ] Implementar `DocumentChunk` dataclass com campo `context_prefix`
- [ ] Implementar Contextual Retrieval: prepend de título/seção a cada chunk
- [ ] Implementar auto-detecção de estratégia por formato e disponibilidade do Docling
- [ ] Integrar com chunking nativo do Docling quando disponível
- [ ] Testes unitários: chunking de Markdown por seção
- [ ] Testes unitários: chunking de CSV por linhas
- [ ] Testes unitários: overlap entre chunks
- [ ] Testes unitários: Contextual Retrieval (context_prefix preenchido)
- [ ] Commit: `feat(docs): implementa chunking inteligente com 5 estratégias e Contextual Retrieval`

---

## Etapa V7.3 — Indexação Dual (SQLite + Qdrant)

**Objetivo:** Indexar chunks no banco vetorial (Qdrant) para busca semântica e registrar metadados no SQLite para busca estruturada.

### Schema SQLite para Documentos

```sql
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    source_path     TEXT NOT NULL,
    filename        TEXT NOT NULL,
    format          TEXT NOT NULL,      -- pdf | csv | xlsx | txt | md
    title           TEXT,
    num_chunks      INTEGER NOT NULL,
    num_pages       INTEGER,
    file_size_bytes INTEGER,
    language        TEXT DEFAULT 'pt-BR',
    ingested_at     TEXT NOT NULL,
    metadata_json   TEXT               -- Metadados adicionais do formato
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL,
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    token_count     INTEGER NOT NULL,
    metadata_json   TEXT,

    FOREIGN KEY (document_id) REFERENCES documents(id)
);

CREATE INDEX IF NOT EXISTS idx_docs_format ON documents(format);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
```

### Fluxo de Indexação

```python
class DocumentIndexer:
    """Indexa documentos processados no Qdrant e SQLite."""

    async def ingest(self, doc: ExtractedDocument) -> str:
        """Pipeline completo de ingestão.

        Returns:
            document_id gerado.
        """
        # 1. Registra documento no SQLite
        doc_id = self._register_document(doc)

        # 2. Divide em chunks
        chunks = self.chunker.chunk(doc)

        # 3. Registra chunks no SQLite (busca estruturada)
        self._register_chunks(doc_id, chunks)

        # 4. Indexa no Qdrant (busca semântica)
        await self._index_vectors(doc_id, chunks)

        return doc_id
```

### Tarefas V7.3

- [ ] Criar tabelas `documents` e `document_chunks` no schema SQLite
- [ ] Implementar `DocumentIndexer` com pipeline de ingestão dual
- [ ] Integrar com `VectorIndexer` existente (src/skills/search_deep/indexer.py)
- [ ] Criar collection Qdrant separada: `geminiclaw_documents` (distinta da web crawl)
- [ ] Testes de integração: ingerir documento → buscar via Qdrant → buscar via SQLite
- [ ] Commit: `feat(docs): implementa indexação dual SQLite + Qdrant para documentos`

---

## Etapa V7.4 — Skill `document_processor`

**Objetivo:** Expor o pipeline de ingestão como uma skill do framework, invocável pelos agentes ou via CLI.

### Interface da Skill

```python
class DocumentProcessorSkill(BaseSkill):
    """Skill de processamento de documentos do usuário.

    Ações:
    - ingest: Processa e indexa um arquivo fornecido pelo usuário
    - search: Busca no índice de documentos do usuário
    - list: Lista documentos já indexados
    - info: Retorna metadados de um documento específico
    """

    name = "document_processor"
    description = (
        "Processa documentos fornecidos pelo usuário (PDF, CSV, XLSX, TXT, MD) "
        "e os indexa para consulta durante pesquisas. "
        "Use 'ingest' para processar um novo arquivo. "
        "Use 'search' para buscar informações nos documentos do usuário."
    )

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["ingest", "search", "list", "info"],
                "description": "Ação a executar"
            },
            "file_path": {
                "type": "string",
                "description": "Caminho do arquivo para ingest (obrigatório para 'ingest')"
            },
            "query": {
                "type": "string",
                "description": "Texto de busca (obrigatório para 'search')"
            },
            "document_id": {
                "type": "string",
                "description": "ID do documento (para 'info')"
            },
            "top_k": {
                "type": "integer",
                "description": "Número máximo de resultados (para 'search')",
                "default": 5
            }
        },
        "required": ["action"]
    }
```

### Tarefas V7.4

- [ ] Implementar `DocumentProcessorSkill` com ações ingest, search, list, info
- [ ] Registrar no `SkillRegistry` com flag `SKILL_DOCUMENT_PROCESSOR_ENABLED`
- [ ] Adicionar config ao `.env.example`: `SKILL_DOCUMENT_PROCESSOR_ENABLED=false`
- [ ] Adicionar comando CLI: `geminiclaw ingest <arquivo>` para ingestão direta
- [ ] Testes unitários: cada ação da skill
- [ ] Testes de integração: ingerir PDF → buscar conteúdo via skill search
- [ ] Commit: `feat(skills): cria skill document_processor para ingestão de documentos`

---

## Etapa V7.5 — Consulta Automática de Documentos nos Prompts

**Objetivo:** Quando o usuário fornece documentos, os agentes devem consultar automaticamente o índice de documentos antes de iniciar suas tarefas.

### Implementação

Na instrução dinâmica do agente (`_get_agent_instruction()`), adicionar seção de documentos disponíveis:

```python
# agents/base/agent.py — _get_agent_instruction()

# --- Documentos do usuário indexados ---
try:
    from src.skills.document_processor.indexer import DocumentIndexer
    indexer = DocumentIndexer()
    docs = indexer.list_documents(limit=10)

    if docs:
        doc_lines = []
        for d in docs:
            doc_lines.append(f"  - [{d.format.upper()}] {d.title} ({d.filename}, {d.num_chunks} chunks)")
        context_sections.append(
            "**DOCUMENTOS DO USUÁRIO DISPONÍVEIS** (consulte via `document_processor` ação 'search'):\n"
            + "\n".join(doc_lines)
        )
except Exception as e:
    logger.debug(f"Não foi possível listar documentos do usuário: {e}")
```

### Integração com o Researcher

Adicionar ao prompt do Researcher:

```
DOCUMENTOS DO USUÁRIO:
Antes de buscar na web, verifique se há documentos indexados via a skill `document_processor` (ação 'list').
Se existirem documentos relevantes, consulte-os com ação 'search' antes de iniciar buscas externas.
Isso garante que o conhecimento do usuário é priorizado sobre fontes externas.
```

### Tarefas V7.5

- [ ] Injetar lista de documentos disponíveis na instrução dos agentes
- [ ] Atualizar prompt do Researcher para priorizar consulta a documentos indexados
- [ ] Implementar auto-detecção: se documentos existem no índice, sugerir consulta
- [ ] Testes de integração: pipeline com documento indexado → consulta pelo researcher
- [ ] Commit: `feat(docs): integra documentos indexados ao contexto dos agentes`

---

## Dependências a Adicionar

```toml
# pyproject.toml — novo grupo opcional
[project.optional-dependencies]
# ...existentes...
documents = [
    "docling>=2.0.0",
    "openpyxl>=3.1.0",
    "pdfplumber>=0.11.0",
]

# Instalar com Docling: uv sync --extra documents
# Instalar tudo: uv sync --all-extras
```

---

## Ordem de Implementação

```
V7.1 (Extratores) → V7.2 (Chunking) → V7.3 (Indexação) → V7.4 (Skill) → V7.5 (Auto-consulta)
```

Cada etapa depende da anterior — pipeline sequencial.

---

## Critérios de Aceite

1. `geminiclaw ingest paper.pdf` processa o PDF e indexa no Qdrant + SQLite
2. O agente Researcher, ao receber uma tarefa de pesquisa, consulta automaticamente os documentos do usuário antes de buscar na web
3. Formatos suportados: `.txt`, `.md`, `.csv`, `.xlsx`, `.pdf` (+ `.docx`, `.pptx` via Docling)
4. A busca semântica retorna chunks relevantes com score e metadados
5. O uso de memória durante ingestão de um PDF de 50 páginas não excede 200 MB adicionais no Pi 5
6. Quando Docling não está disponível, o sistema usa fallbacks leves sem erro
