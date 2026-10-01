# Design: Indexação dos Insumos com Metadados

## 0. Estado atual (verificado em `dev`, commit `40419ea`, 2026-10-01)

| Ponto | Onde | Situação |
|---|---|---|
| Snapshot de insumos | `src/orchestrator.py` (`_snapshot_input_context`) | Copia `input_context/` para `outputs/<sessão>/input_snapshot/` (nomes achatados). |
| Leitura para o prompt | `src/orchestrator.py:230`, `src/context_loader.py` | `ContextLoader().load()`; não indexa. |
| Ingestão | `src/skills/document_processor/skill.py:105-120`; `indexer.py:107-118` | Só por ferramenta do agente; `uuid4` por chamada; sem deduplicação. |
| Texto vetorizado | `chunker.py:56-74`; `indexer.py:192-206` | `"Documento: <título> (<FORMATO>)"` + trecho; payload com `document_id`, `content`, `format`, `chunk_index` e campos de embedding. |
| Tabelas | `scripts/init_db.sql:245-269` | `documents` e `document_chunks` com `metadata_json JSONB`. |
| Contexto dos agentes | `agents/base/agent.py:306-321` | Lista os 10 últimos documentos de qualquer projeto. |
| Reindexação | `src/embeddings/reindex.py`; `geminiclaw embeddings reindex` | Reprocessa pontos por modelo/versão de embedding. |
| `Insumo` no grafo | `v17-structural-fact-ingestion` design §1-§2 | Um `Insumo` por arquivo, chave (`projeto_id`, `hash_conteudo`), `tipo` pela extensão. |

## 1. Momento da indexação

Logo depois do snapshot e da gravação dos `Insumo`s no grafo (`v17-structural-fact-ingestion`),
**antes do planejamento**, o orquestrador chama `index_input_snapshot(sessao, projeto)`:

1. Para cada arquivo de `input_snapshot/`: sha256 → procura em `documents` um registro com
   `metadata_json->>'projeto_id'` e `metadata_json->>'hash_conteudo'` iguais.
2. Já indexado com o `versao_enriquecimento` atual e o mesmo `hash_cabecalho_projeto` → pula.
3. Indexado com versão ou cabeçalho diferente → reenriquece e revetoriza os trechos existentes
   (mesmos IDs de trecho, `upsert`).
4. Não indexado → extrai, divide, enriquece, vetoriza e registra.

Limites: arquivos acima de `INPUT_INDEX_MAX_FILE_MB` (padrão 50) são registrados só com
descritor e um `WARNING`; o tempo total é limitado por `INPUT_INDEX_MAX_SECONDS` (padrão 300).
Ao estourar o tempo, os arquivos restantes ficam para a próxima sessão (a sessão segue) e o
payload registra `input_index.pendentes`. Embedding roda em `asyncio.to_thread` (como hoje).

Falha do Qdrant ou do modelo de embedding não impede a sessão: o arquivo fica registrado com
`vetorizacao: pendente` (mesmo padrão do ADR 015 §6, fluxo de escrita) e entra na próxima
reconciliação.

## 2. O que é indexado por tipo

| `tipo_insumo` (regra da `v17-structural-fact-ingestion`) | Indexação |
|---|---|
| `artigo` (`.pdf .docx .md .txt .rst`) e `.pptx` | Trechos de texto enriquecidos (§3) |
| `dataset` (`.csv .tsv .xlsx .xls .ods .json .jsonl .parquet`) | **Um descritor**, sem valores: nome, formato, para cada tabela/aba as colunas com tipo inferido, número de linhas e de colunas, codificação e separador detectados |
| imagens | **Um descritor**: nome, formato, dimensões; sem OCR nem descrição por modelo |
| `outro` | Descritor com nome, formato e tamanho |

PDFs escaneados: o texto vem do OCR local já existente (`context_loader.py:335-354`). A partir
da `v18.5-research-data-ingestion`, arquivos marcados `dado_de_pesquisa` no `dados.yaml` passam
a ter só descritor, qualquer que seja a extensão (requisito já escrito aqui para quando a
marcação existir).

## 3. Texto enriquecido

Modelo fixo (`versao_enriquecimento = 1`), montado sem LLM:

```
Documento: {titulo} | tipo: {tipo_insumo} | arquivo: {nome_arquivo}
Projeto: {projeto_titulo} | objetivo: {projeto_objetivo[:200]} | domínios: {dominios}
Seção: {secao}            ← só quando o extrator informa
---
{texto do trecho}
```

- `titulo`: título extraído do documento quando o extrator o fornece; senão, nome do arquivo.
- `dominios`: termos canônicos ligados ao projeto por `NO_DOMINIO` (vocabulário da
  `v17-controlled-vocabulary`); vazio se não houver.
- Origem: todo insumo de `input_context/` é material do pesquisador; não entra no texto, mas fica
  no payload (`origem: "input_context"` ou `"artefato"`).
- O `content` guardado em `document_chunks` e devolvido pela busca é **só o trecho**, sem
  cabeçalho (sai o prefixo atual de `chunker.py`). O cabeçalho é recalculável a qualquer
  momento a partir dos metadados.
- `hash_texto` (já gravado por `embedding_payload`) passa a ser calculado sobre o texto
  enriquecido; `hash_cabecalho_projeto` = sha256 da linha "Projeto:", para detectar mudança de
  título, objetivo ou domínios do projeto.

Limite de tamanho: o cabeçalho é truncado em `INPUT_INDEX_HEADER_MAX_CHARS` (padrão 400) para não
dominar o vetor de trechos curtos.

## 4. Payload e registros

Qdrant (coleção existente `geminiclaw_documents`), além dos campos atuais:

| Campo | Valor |
|---|---|
| `insumo_id` | ID do nó `Insumo` (mesmo ID do grafo); `null` se o grafo estiver indisponível |
| `projeto_id` | projeto da sessão |
| `tipo_insumo` | `artigo` / `dataset` / `outro` / `imagem` |
| `tipo_ponto` | `trecho` ou `descritor` |
| `hash_conteudo` | sha256 do arquivo |
| `dominios` | lista de termos |
| `visibilidade` | `privado` (padrão; ADR 015 §3) |
| `origem` | `input_context` ou `artefato` |
| `versao_enriquecimento` | inteiro |

Índices de payload novos: `projeto_id`, `insumo_id`. Em `documents.metadata_json`: `projeto_id`,
`hash_conteudo`, `insumo_id`, `tipo_insumo`, `versao_enriquecimento`, `hash_cabecalho_projeto`,
`vetorizacao`. O `document_id` passa a ser determinístico:
`uuid5(NAMESPACE, f"{projeto_id}:{hash_conteudo}")`, e o ID de cada trecho
`uuid5(NAMESPACE, f"{document_id}:{indice}")`, o que torna a reindexação idempotente.

## 5. Busca e contexto

- `DocumentIndexer.search(query, projeto_id=<sessão>, ...)` filtra por projeto por padrão; a
  skill aceita `todos_os_projetos: true` para busca sem filtro (o resultado informa o projeto de
  cada trecho).
- O resultado traz `titulo`, `tipo_insumo`, `tipo_ponto`, `insumo_id` e o trecho.
- `agents/base/agent.py` lista só os documentos do projeto da sessão.
- O texto devolvido segue a política de saída já existente: documentos textuais obedecem à
  `LLM_DATA_POLICY`; descritores não têm valores (ADR 019 §3.1).

## 6. Configuração (`src/config.py`, `.env.example`)

| Variável | Padrão | Uso |
|---|---|---|
| `INPUT_INDEX_ENABLED` | `true` | Liga a indexação automática |
| `INPUT_INDEX_MAX_SECONDS` | 300 | Tempo máximo por sessão |
| `INPUT_INDEX_MAX_FILE_MB` | 50 | Acima disso, só descritor |
| `INPUT_INDEX_HEADER_MAX_CHARS` | 400 | Tamanho máximo do cabeçalho |

## 7. Análise de impacto (6 eixos)

| Eixo | Impacto |
|---|---|
| Orquestrador & Loop | Etapa nova entre o snapshot e o planejamento, limitada por tempo. |
| Agentes & Prompts | Busca útil desde a primeira sessão; lista filtrada por projeto. Nenhum prompt muda. |
| Sandboxes & Containers | Nenhum. |
| Persistência | Campos novos em JSONB e no payload; índices de payload; IDs determinísticos. |
| Segurança | Datasets e imagens só como descritor; embeddings locais; nada sai do nó na indexação. |
| Testes & Telemetria | Testes com embedding falso determinístico e Qdrant de teste; evento `input_index` com contagens e tempo. |

## 8. Riscos

- **Tempo de embedding no Pi 5** com muitos PDFs: limitado por tempo, com pendentes para a
  próxima sessão.
- **Cabeçalho dominando o vetor:** truncado; a calibração deve comparar busca com e sem
  cabeçalho numa amostra rotulada pelo pesquisador (questão 3).
- **Projeto renomeado** obriga a revetorizar todos os trechos do projeto: detectado por
  `hash_cabecalho_projeto` e feito de forma incremental nas sessões seguintes.

## 9. Questões em aberto para o pesquisador

1. **Metadados do cabeçalho:** a proposta usa título, tipo, arquivo, título e objetivo do
   projeto, domínios e seção. Acrescentar autores e ano quando o extrator os encontrar?
2. **Momento:** indexar antes do planejamento (proposta, com limite de tempo) ou em segundo
   plano durante a sessão, aceitando que o primeiro plano não use a busca?
3. **Avaliação:** montar uma pequena amostra de consultas com trechos relevantes marcados pelo
   pesquisador para comparar "com cabeçalho" e "sem cabeçalho" antes de fixar o formato?
4. **Datasets:** só descritor (proposta) ou também estatísticas agregadas pela regra de k do
   ADR 019 §3.1? Estatísticas dependem do `LOCALITY_MIN_GROUP_SIZE`, que só existe na V18.5.
