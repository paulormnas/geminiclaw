# Proposta: Indexação dos Insumos com Metadados

**ID:** `v17-input-document-index` · **Versão:** V17 · **Capacidade:** `input-documents`
**ADRs de origem:** [ADR 015](../../../docs/decisions/adr_015_modelo_dados_grafo_conhecimento.md) §6
("Documentos de entrada (`Insumo`)": vetorização em trechos enriquecidos com metadados; decisão
de princípio de 2026-10-01) e §2/§4 (nó `Insumo`); [ADR 011](../../../docs/decisions/adr_011_provedores_agnosticos.md) §3
(embeddings locais); [ADR 019](../../../docs/decisions/adr_019_localidade_dados_proveniencia_resultados.md) §3
(dados de pesquisa não saem do nó)
**Depende de:** `v16-local-embeddings` (concluída), `v17-research-project` (`projeto_id`,
domínios), `v17-structural-fact-ingestion` (nó `Insumo` por `projeto_id` + `hash_conteudo`)

> O ADR 015 deixou para "spec e discussão posterior" a escolha dos metadados, o formato do texto
> enriquecido e o momento da indexação. Este documento traz uma proposta para cada um; as
> alternativas ficam em "Questões em aberto" no `design.md`.

## Por quê

Os documentos que o pesquisador coloca em `input_context/` (artigos, relatórios, protocolos,
conjuntos de dados) não chegam à busca semântica:

- A ingestão na coleção `geminiclaw_documents` só acontece se um agente chamar
  `document_processor` com `action="ingest"` (`src/skills/document_processor/skill.py:105-120`).
  Nenhum fluxo faz isso sozinho, e a coleção está com **0 pontos** (levantamento de
  2026-10-01, `docs/decisions/README.md`).
- O `ContextLoader` lê `input_context/` para montar o prompt do planejamento
  (`src/orchestrator.py:230`), mas não indexa nada.
- Cada ingestão gera um `document_id` novo (`uuid4`, `indexer.py:109`): o mesmo arquivo em duas
  sessões vira dois documentos.
- O texto vetorizado é o trecho com um prefixo mínimo (`"Documento: <título> (PDF)"`,
  `chunker.py:58-60`); nada diz a que projeto, tipo de material ou área o trecho pertence.
- Documentos não têm `projeto_id`; a busca e a lista injetada no contexto dos agentes
  (`agents/base/agent.py:306-321`) misturam projetos.
- Conjuntos de dados seriam fatiados como texto, o que poria valores brutos no índice e, pela
  busca, no prompt (ADR 019 §3).

## O que muda

- **Novo:** indexação automática e determinística (sem LLM) dos arquivos de `input_snapshot/` no
  início da sessão, idempotente por (`projeto_id`, `hash_conteudo`).
- **Novo:** texto enriquecido por trecho: um cabeçalho fixo com metadados do documento e do
  projeto, seguido do trecho, é o que vai ao modelo de embedding. O texto original do trecho
  continua sendo o que a busca devolve.
- **Novo:** para `dataset` e imagens, um único **descritor** sem valores (nome, formato, colunas e
  tipos, número de linhas; dimensões da imagem), conforme o ADR 019 §3.1.
- **Novo:** payload dos pontos com `insumo_id`, `projeto_id`, `tipo_insumo`, `hash_conteudo`,
  `dominios`, `visibilidade` e `versao_enriquecimento`, além dos campos de embedding já
  existentes.
- **Modificado:** busca e lista de documentos filtradas pelo projeto da sessão por padrão.
- **Modificado:** `document_processor ingest` reaproveita o mesmo caminho (deduplicação e
  enriquecimento) para arquivos de `artifacts/`.
- **Modificado:** reindexação (`geminiclaw embeddings reindex`) refaz o texto enriquecido quando
  `versao_enriquecimento` ou os metadados do projeto mudam.
- **Fora do escopo:** busca bibliográfica (ADR 010); vetorização dos nós do grafo
  (`v17-knowledge-semantic-index`); manifesto `dados.yaml` e marcação `dado_de_pesquisa`
  (`v18.5-research-data-ingestion`, que passará a alimentar a regra de descritor).

## Impacto

- **Código:** `src/knowledge/input_index.py` (novo: orquestra a indexação do snapshot),
  `src/skills/document_processor/chunker.py` (cabeçalho), `indexer.py` (deduplicação, payload,
  filtro por projeto), `skill.py`, `src/orchestrator.py` (chamada após o snapshot),
  `agents/base/agent.py` (lista filtrada), `src/embeddings/reindex.py`, `src/config.py`,
  `.env.example`.
- **Dados:** campos novos em `documents.metadata_json` e `document_chunks.metadata_json`
  (JSONB, sem alteração de schema) e no payload do Qdrant; índices de payload novos na coleção
  (`projeto_id`, `insumo_id`).
- **Custo:** tempo de embedding local no início da sessão (Pi 5); nenhuma chamada de LLM.

## Aprovações necessárias

- Nenhuma alteração de schema SQL, Dockerfile ou compose. A criação de índices de payload no
  Qdrant é aditiva.
- Pontos antigos da coleção (hoje 0) sem `projeto_id` continuam buscáveis só sem filtro de
  projeto; nenhum ponto é apagado.
