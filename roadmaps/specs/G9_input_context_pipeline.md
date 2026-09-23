# Spec G9 — Pipeline de Contexto via `input_context/`

**Versão:** V15.5
**Status:** Proposta aprovada — aguardando implementação de V14
**Gap:** G9 — Ausência de interface de input de contexto estruturado
**ADRs relacionados:**
  - [ADR 001](../../docs/decisions/adr_001_proposito_harness_pesquisa_cientifica.md) — Propósito: contexto pré-curado
  - [ADR 005](../../docs/decisions/adr_005_estrategia_persistencia.md) — Estratégia de persistência

---

## Objetivo

Criar um pipeline de ingestão de contexto científico que permita ao pesquisador depositar arquivos
de múltiplos formatos em uma pasta dedicada (`input_context/`) antes de iniciar a sessão. O sistema
os processa automaticamente, converte para texto estruturado, e injeta no contexto inicial do
Researcher Agent — sem necessidade de flags no CLI ou reformatação manual.

---

## Dependências

- **V14 concluído:** Researcher Agent com container próprio e capacidade de receber contexto via IPC
- **V7 concluído:** `DocumentProcessor` skill disponível para PDFs e formatos de texto

---

## Contexto e Problema

Atualmente o pesquisador só pode fornecer contexto via prompt de texto no CLI. Para uma sessão
de pesquisa real isso é impraticável:

- Um artigo de 20 páginas não cabe em um prompt
- Um dataset CSV de 10.000 linhas não pode ser colado no terminal
- Uma imagem de microscopia não tem representação textual no CLI

O resultado é que o pesquisador ou fornece contexto insuficiente (o agente infere erroneamente)
ou precisa fazer uma preparação manual muito trabalhosa antes de cada sessão.

---

## Tarefas

### Tarefa 1: Criar estrutura `input_context/` e `ContextLoader`

- **Módulos afetados:** `src/context_loader.py` (novo), `src/config.py`
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] Variável de configuração `INPUT_CONTEXT_DIR` em `src/config.py` com default `./input_context`
  - [ ] `ContextLoader` criado com método `load() -> ContextBundle`
  - [ ] `ContextBundle` é um dataclass com campos:
        ```python
        @dataclass
        class ContextBundle:
            text_documents: list[ProcessedDocument]  # MDs, TXTs, PDFs convertidos
            structured_data: list[DatasetSummary]    # CSVs, XLSXs com schema inferido
            images: list[ImageContext]               # Imagens com descrição/OCR
            raw_files: list[Path]                    # Arquivos não processados (passados como path)
            total_tokens_estimated: int              # Estimativa de tokens para alertar se muito grande
        ```
  - [ ] `ContextLoader` escaneia recursivamente `input_context/` e classifica arquivos por tipo
  - [ ] Se `input_context/` não existe: criado automaticamente com `README.md` explicando como usar
  - [ ] `ContextLoader.load()` loga cada arquivo processado e seu tamanho estimado em tokens
  - [ ] Testes unitários com pasta mock contendo 1 arquivo de cada tipo

### Tarefa 2: Implementar processadores por formato

- **Módulos afetados:** `src/context_loader.py`, `src/skills/document/processors/` (novos ou extensão do V7)
- **Complexidade estimada:** Alta
- **Critérios de aceite:**

  **Texto/Markdown (`.md`, `.txt`, `.rst`):**
  - [ ] Leitura direta com encoding UTF-8; fallback para latin-1
  - [ ] Chunking automático se arquivo > 50.000 caracteres (com overlap de 500 chars entre chunks)

  **PDF (`.pdf`):**
  - [ ] Extração de texto via `pymupdf` (PyMuPDF/fitz) — preferência por texto nativo
  - [ ] Se PDF é scan/imagem (texto extraído < 100 chars): fallback para OCR via `pytesseract`
  - [ ] Testes: PDF com texto nativo → extração direta; PDF escaneado → OCR aplicado

  **Dados estruturados (`.csv`, `.tsv`):**
  - [ ] Leitura via `pandas.read_csv()` com detecção automática de delimitador e encoding
  - [ ] `DatasetSummary` inclui: número de linhas, colunas, tipos, amostra das 5 primeiras linhas,
        estatísticas descritivas básicas (min, max, mean, nulls por coluna)
  - [ ] Dataset completo disponível em `/outputs/<session>/input_snapshot/` para o Developer Agent usar
  - [ ] Testes: CSV com 10.000 linhas → `DatasetSummary` gerado em < 2s

  **Excel (`.xlsx`, `.xls`, `.ods`):**
  - [ ] Leitura via `openpyxl`; múltiplas abas tratadas como datasets separados
  - [ ] Mesmo `DatasetSummary` que CSV

  **Imagens (`.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`):**
  - [ ] Estratégia 1 (padrão): OCR via `pytesseract` — extrai texto da imagem se houver
  - [ ] Estratégia 2 (fallback/configurável): enviar imagem para Gemini Vision API para
        descrição em linguagem natural do conteúdo (gráficos, tabelas, microscopia)
  - [ ] `OCR_PROVIDER` em `.env`: `"local"` (pytesseract) ou `"gemini"` — default `"local"`
  - [ ] `ImageContext.description` contém o resultado (OCR ou descrição do Vision)
  - [ ] Testes: imagem de gráfico → descrição gerada sem erro

  **JSON (`.json`, `.jsonl`):**
  - [ ] Leitura e validação; se `.jsonl`, trata como dataset linha a linha
  - [ ] Schema inferido e incluído no contexto

### Tarefa 3: Integrar `ContextLoader` ao Orchestrator

- **Módulos afetados:** `src/autonomous_loop.py`, `src/orchestrator.py`
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] `ContextLoader.load()` é chamado **antes** de iniciar a sessão (antes de subir containers)
  - [ ] `ContextBundle` é serializado para JSON e injetado como payload IPC inicial para o Researcher Agent
  - [ ] CLI exibe: `"📂 Contexto carregado: <N> arquivos (<X> tokens estimados)"`
  - [ ] Se `ContextBundle.total_tokens_estimated > CONTEXT_TOKEN_WARNING_THRESHOLD`:
        aviso ao pesquisador: "Contexto muito grande (~X tokens). Recomendado: remover arquivos
        menos relevantes ou usar chunking. Continuar? [s/N]"
  - [ ] `CONTEXT_TOKEN_WARNING_THRESHOLD` configurável via `.env` (default: 100.000)
  - [ ] Cópia de todos os arquivos de `input_context/` salva em `/outputs/<session>/input_snapshot/`
        para rastreabilidade imutável da sessão
  - [ ] Testes: Orchestrator com `input_context/` vazio → sessão inicia com aviso "nenhum contexto encontrado"

### Tarefa 4: Gestão do ciclo de vida do `input_context/`

- **Módulos afetados:** `src/context_loader.py`, `src/cli.py`
- **Complexidade estimada:** Baixa
- **Critérios de aceite:**
  - [ ] `input_context/` **não é limpa automaticamente** após a sessão — o pesquisador gerencia
  - [ ] CLI exibe no final da sessão: "Contexto salvo em /outputs/<session>/input_snapshot/.
        Execute 'geminiclaw clear-context' para limpar input_context/ para a próxima sessão."
  - [ ] Comando `geminiclaw clear-context` limpa `input_context/` após confirmação do pesquisador
  - [ ] Testes: sessão concluída → `input_snapshot/` contém cópia fiel dos arquivos usados

### Tarefa 5: Testes de integração do pipeline de contexto

- **Módulos afetados:** `tests/integration/test_context_loader.py` (novo)
- **Complexidade estimada:** Média
- **Critérios de aceite:**
  - [ ] Cenário: `input_context/` com PDF + CSV + PNG → `ContextBundle` gerado com 3 documentos
  - [ ] Cenário: PDF scan (sem texto nativo) → OCR aplicado com `pytesseract`
  - [ ] Cenário: CSV com 5 colunas → `DatasetSummary` contém tipos e estatísticas corretas
  - [ ] Cenário: `input_context/` vazio → aviso, sessão inicia normalmente
  - [ ] Cenário: contexto > threshold → aviso exibido, pesquisador pode escolher continuar ou não

---

## Validação da Etapa

- [ ] `uv run pytest -m "unit or integration" -v` — todos os testes passam
- [ ] Smoke test: sessão com PDF + CSV + texto → Researcher Agent recebe contexto estruturado via IPC
- [ ] `input_snapshot/` criado corretamente ao final da sessão
- [ ] OCR funcional localmente sem chamadas externas (quando `OCR_PROVIDER=local`)
- [ ] PR merged em `dev`

---

## Arquivos

| Arquivo | Ação | Descrição |
|---|---|---|
| `src/context_loader.py` | NEW | `ContextLoader`, `ContextBundle`, processadores por formato |
| `src/config.py` | MODIFY | `INPUT_CONTEXT_DIR`, `CONTEXT_TOKEN_WARNING_THRESHOLD`, `OCR_PROVIDER` |
| `.env.example` | MODIFY | Adicionar variáveis de contexto com comentários |
| `src/autonomous_loop.py` | MODIFY | Chamar `ContextLoader.load()` antes de iniciar sessão; passar bundle ao Researcher |
| `src/cli.py` | MODIFY | Exibir arquivos carregados; adicionar `clear-context` command |
| `input_context/README.md` | NEW | Instrução de uso da pasta para o pesquisador |
| `tests/unit/test_context_loader.py` | NEW | Testes unitários dos processadores |
| `tests/integration/test_context_pipeline.py` | NEW | Testes de integração end-to-end |
